import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_ev_option_prob(
    market_cap: float,
    core_fair_mcap: float,
    ev_peer_snapshots: pd.DataFrame,
    prev_p_ewma: Optional[float],
) -> Tuple[Dict[str, float], str]:
    """Compute EV narrative option probability metrics."""
    ev_mcap_series = ev_peer_snapshots.get("market_cap") if "market_cap" in ev_peer_snapshots.columns else None
    if ev_mcap_series is None:
        logger.warning("EV peers missing market cap data.")
        return {
            "option_value": max(market_cap - core_fair_mcap, 0.0),
            "ev_mcap_med": 0.0,
            "k": 0.0,
            "success_value": 0.0,
            "p_raw": prev_p_ewma or 0.0,
            "p_ewma": prev_p_ewma or 0.0,
        }, "low"

    ev_mcap_series = ev_mcap_series.dropna()
    if len(ev_mcap_series) < max(1, len(ev_peer_snapshots) // 2):
        logger.warning("Too many missing EV peer market caps, carry forward p_ewma.")
        p = prev_p_ewma or 0.0
        return {
            "option_value": max(market_cap - core_fair_mcap, 0.0),
            "ev_mcap_med": 0.0,
            "k": 0.0,
            "success_value": 0.0,
            "p_raw": p,
            "p_ewma": p,
        }, "low"

    ev_mcap_med = float(ev_mcap_series.median())
    if ev_mcap_med <= 0:
        p = prev_p_ewma or 0.0
        return {
            "option_value": max(market_cap - core_fair_mcap, 0.0),
            "ev_mcap_med": 0.0,
            "k": 0.0,
            "success_value": 0.0,
            "p_raw": p,
            "p_ewma": p,
        }, "low"

    option_value = max(market_cap - core_fair_mcap, 0.0)
    r = market_cap / ev_mcap_med if ev_mcap_med else 0.0
    k = float(np.clip(0.75 + 0.15 * np.log(1 + r), 0.6, 1.2))
    success_value = k * ev_mcap_med
    if success_value <= 0:
        p = prev_p_ewma or 0.0
        return {
            "option_value": option_value,
            "ev_mcap_med": ev_mcap_med,
            "k": k,
            "success_value": success_value,
            "p_raw": p,
            "p_ewma": p,
        }, "low"

    p_raw = float(np.clip(option_value / success_value, 0.0, 1.0))
    p_ewma = p_raw
    if prev_p_ewma is not None:
        p_ewma = 0.5 * p_raw + 0.5 * prev_p_ewma

    return {
        "option_value": option_value,
        "ev_mcap_med": ev_mcap_med,
        "k": k,
        "success_value": success_value,
        "p_raw": p_raw,
        "p_ewma": p_ewma,
    }, "medium"
