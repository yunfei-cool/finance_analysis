import logging
from typing import Dict, Optional, Tuple

import pandas as pd

from indicators import max_drawdown, moving_average, realized_vol, safe_clip

logger = logging.getLogger(__name__)


class RegimeState:
    def __init__(self, regime: str = "NEUTRAL", streak: int = 0) -> None:
        self.regime = regime
        self.streak = streak


def evaluate_regime(
    closes: pd.Series,
    config: Dict[str, float],
    state: RegimeState,
) -> Tuple[str, float, Dict[str, float], RegimeState]:
    """Compute HSTECH regime with debounce logic."""
    ma50 = moving_average(closes, int(config["ma_short"]))
    ma200 = moving_average(closes, int(config["ma_long"]))
    rv20 = realized_vol(closes, 20)
    rv120 = realized_vol(closes, 120)
    vol_ratio = rv20 / rv120 if rv120 and rv120 > 0 else 0.0
    dd120 = max_drawdown(closes, 120)

    buffer = float(config["ma_buffer"])
    latest = float(closes.iloc[-1])

    if latest > ma200 * (1 + buffer) and ma50 > ma200:
        desired = "ON"
    elif latest < ma200 * (1 - buffer) and ma50 < ma200:
        desired = "OFF"
    else:
        desired = "NEUTRAL"

    if desired == state.regime:
        state.streak = min(state.streak + 1, int(config["confirm_days"]))
    else:
        state.streak = 1

    regime = state.regime
    if state.streak >= int(config["confirm_days"]):
        regime = desired
        state.regime = desired

    h_regime = {"ON": 1.0, "NEUTRAL": 0.55, "OFF": 0.15}[regime]

    if vol_ratio > config["vol_ratio_high"]:
        h_regime = max(0.08, h_regime - 0.2)
    elif vol_ratio < config["vol_ratio_low"]:
        h_regime = min(1.0, h_regime + 0.1)

    if dd120 < config["dd_extreme"]:
        h_regime = min(h_regime, 0.15)
        regime = "OFF"

    if dd120 < config["dd_extreme"] or vol_ratio > config["vol_ratio_extreme"]:
        h_regime = min(h_regime, 0.08)

    if dd120 < config["dd_very_extreme"]:
        h_regime = min(h_regime, 0.03)

    return regime, h_regime, {"ma50": ma50, "ma200": ma200, "rv20": rv20, "rv120": rv120, "vol_ratio": vol_ratio, "dd120": dd120}, state
