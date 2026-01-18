from typing import Dict, Tuple

import numpy as np

from indicators import safe_clip


def compute_position(
    price: float,
    core_fair_price: float,
    p_ewma: float,
    p_sma60: float,
    risk_score: float,
    regime: str,
    h_regime: float,
    current_pos: float,
    cap: float,
    min_trade_delta: float,
    add_step: float,
    reduce_step: float,
) -> Dict[str, float]:
    cheapness = safe_clip((core_fair_price / price - 1) / 0.25, 0, 1)
    f_value = 0.5 + 0.9 * cheapness

    p_trend = safe_clip((p_ewma - p_sma60) / 0.15, -1, 1)
    g_trend = 1.0 + 0.2 * p_trend

    r_risk = safe_clip(1 - (risk_score - 40) / 60, 0.4, 1.0)

    target_pos = cap * h_regime * f_value * g_trend * r_risk

    if regime == "OFF" and price > core_fair_price * 0.90:
        target_pos = min(target_pos, 0.02)

    delta = target_pos - current_pos
    action = "HOLD"
    action_reason = "Within rebalance threshold."

    if abs(delta) < min_trade_delta:
        delta = 0.0
    elif delta > 0:
        delta = min(delta, add_step)
        action = "ADD" if current_pos > 0 else "BUY"
        action_reason = "Increase position based on valuation/regime/trend."
    else:
        delta = max(delta, -reduce_step)
        action = "REDUCE"
        action_reason = "Reduce position due to risk/regime signals."

    target_pos = float(np.clip(current_pos + delta, 0, 1))
    return {
        "target_pos": target_pos,
        "delta_pos": delta,
        "action": action,
        "action_reason": action_reason,
    }
