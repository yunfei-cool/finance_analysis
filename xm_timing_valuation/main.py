import argparse
import json
import logging
import os
from datetime import datetime
from typing import Dict, List

import pandas as pd
import yaml

from core_valuation import compute_core_valuation
from data_futu import FutuConfig, FutuDataClient, extract_snapshot_fields, normalize_snapshot
from ev_option_prob import compute_ev_option_prob
from indicators import ewma, sma
from market_regime import RegimeState, evaluate_regime
from position_engine import compute_position
from report import append_csv, print_console
from risk_model import compute_risk_score

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"


def load_config(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_state(path: str) -> Dict:
    if not os.path.exists(path):
        return {"current_pos": 0.0, "regime": "NEUTRAL", "regime_streak": 0, "p_history": []}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(path: str, state: Dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Xiaomi timing & valuation")
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--config", type=str, default="config.yaml", help="Config file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = args.config
    config = load_config(config_path)

    logging.basicConfig(level=getattr(logging, config["logging"]["level"]), format=LOG_FORMAT)

    date = args.date or datetime.now().strftime("%Y-%m-%d")

    outputs = config["outputs"]
    state = load_state(outputs["state_path"])

    futu_config = FutuConfig(
        host=config["futu"]["host"],
        port=config["futu"]["port"],
        max_retry=config["futu"]["max_retry"],
        retry_sleep=config["futu"]["retry_sleep"],
        cache_dir=outputs["cache_dir"],
    )

    client = FutuDataClient(futu_config)
    try:
        codes = [
            config["symbols"]["target"],
            *config["symbols"]["ev_peers"],
            *config["symbols"]["core_peers"],
        ]
        snapshot = normalize_snapshot(client.get_snapshot(codes))

        target_code = config["symbols"]["target"]
        target_snapshot = extract_snapshot_fields(snapshot, target_code)

        core_peer_snapshot = snapshot[snapshot["code"].isin(config["symbols"]["core_peers"])]
        ev_peer_snapshot = snapshot[snapshot["code"].isin(config["symbols"]["ev_peers"])]

        core_fair_mcap, core_cheapness, confidence_core = compute_core_valuation(
            target_snapshot, core_peer_snapshot
        )

        market_cap = float(target_snapshot.get("market_cap") or 0.0)
        price = float(target_snapshot.get("price") or 0.0)
        core_fair_price = price * (1 + core_cheapness) if price else 0.0

        p_history = state.get("p_history", [])
        prev_p_ewma = p_history[-1] if p_history else None

        p_metrics, confidence_p = compute_ev_option_prob(
            market_cap,
            core_fair_mcap,
            ev_peer_snapshot,
            prev_p_ewma,
        )

        if prev_p_ewma is not None:
            alpha = 1 - pow(0.5, 1 / config["p_ewma"]["half_life"])
            p_ewma = alpha * p_metrics["p_raw"] + (1 - alpha) * prev_p_ewma
            p_metrics["p_ewma"] = p_ewma

        p_history.append(p_metrics["p_ewma"])
        p_history = p_history[-200:]

        target_kline = client.get_kline(target_code, max(config["kline"]["target_days"]))
        if "close" not in target_kline.columns:
            raise RuntimeError("Target kline missing close column")
        target_closes = target_kline["close"].astype(float)

        hstech_code = config["symbols"]["hstech"]
        hstech_kline = client.get_kline(hstech_code, config["kline"]["hstech_days"])
        if "close" not in hstech_kline.columns:
            raise RuntimeError("HSTECH kline missing close column. Update config with correct index code.")
        hstech_closes = hstech_kline["close"].astype(float)

        regime_state = RegimeState(state.get("regime", "NEUTRAL"), state.get("regime_streak", 0))
        regime, h_regime, regime_metrics, regime_state = evaluate_regime(
            hstech_closes,
            config["regime"],
            regime_state,
        )

        risk_metrics = compute_risk_score(target_closes)

        p_series = pd.Series(p_history)
        p_sma60 = sma(p_series, 60) if len(p_series) >= 1 else p_metrics["p_ewma"]

        pos_metrics = compute_position(
            price=price,
            core_fair_price=core_fair_price,
            p_ewma=p_metrics["p_ewma"],
            p_sma60=p_sma60,
            risk_score=risk_metrics["risk_score"],
            regime=regime,
            h_regime=h_regime,
            current_pos=state.get("current_pos", 0.0),
            cap=config["position"]["cap"],
            min_trade_delta=config["position"]["min_trade_delta"],
            add_step=config["position"]["add_step"],
            reduce_step=config["position"]["reduce_step"],
        )

        state.update(
            {
                "current_pos": pos_metrics["target_pos"],
                "regime": regime_state.regime,
                "regime_streak": regime_state.streak,
                "p_history": p_history,
            }
        )
        save_state(outputs["state_path"], state)

        fieldnames = [
            "date",
            "price",
            "mcap",
            "core_fair_mcap",
            "core_cheapness",
            "option_value",
            "ev_mcap_med",
            "k",
            "p_ewma",
            "hstech_regime",
            "h_regime",
            "volratio",
            "dd120",
            "risk_score",
            "target_pos",
            "current_pos",
            "delta_pos",
            "action",
            "confidence_core",
            "confidence_p",
        ]

        row = {
            "date": date,
            "price": price,
            "mcap": market_cap,
            "core_fair_mcap": core_fair_mcap,
            "core_cheapness": core_cheapness,
            "option_value": p_metrics["option_value"],
            "ev_mcap_med": p_metrics["ev_mcap_med"],
            "k": p_metrics["k"],
            "p_ewma": p_metrics["p_ewma"],
            "hstech_regime": regime,
            "h_regime": h_regime,
            "volratio": regime_metrics["vol_ratio"],
            "dd120": regime_metrics["dd120"],
            "risk_score": risk_metrics["risk_score"],
            "target_pos": pos_metrics["target_pos"],
            "current_pos": state.get("current_pos"),
            "delta_pos": pos_metrics["delta_pos"],
            "action": pos_metrics["action"],
            "confidence_core": confidence_core,
            "confidence_p": confidence_p,
        }

        append_csv(outputs["csv_path"], fieldnames, row)

        summary = [
            f"{date} Xiaomi ({target_code}) price={price:.2f} mcap={market_cap:.2f}",
            f"Core fair MCAP={core_fair_mcap:.2f} cheapness={core_cheapness:.2%} conf={confidence_core}",
            f"EV option p_ewma={p_metrics['p_ewma']:.2f} option_value={p_metrics['option_value']:.2f}",
            f"HSTECH regime={regime} h={h_regime:.2f} vol_ratio={regime_metrics['vol_ratio']:.2f} dd120={regime_metrics['dd120']:.2%}",
            f"Risk score={risk_metrics['risk_score']:.1f}",
            f"Position target={pos_metrics['target_pos']:.2f} delta={pos_metrics['delta_pos']:.2f} action={pos_metrics['action']}",
        ]
        print_console(summary)
    finally:
        client.close()


if __name__ == "__main__":
    main()
