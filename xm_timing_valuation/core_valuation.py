import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_core_valuation(
    target: Dict[str, Optional[float]],
    peer_snapshots: pd.DataFrame,
) -> Tuple[float, float, str]:
    """Compute core fair market cap and cheapness.

    Returns (core_fair_mcap, core_cheapness, confidence).
    """
    market_cap = target.get("market_cap") or 0.0
    pe_ttm = target.get("pe_ttm")
    if pe_ttm and pe_ttm > 0:
        net_profit_ttm = market_cap / pe_ttm if pe_ttm else None
    else:
        net_profit_ttm = None

    peer_pe = peer_snapshots.get("pe_ttm") if "pe_ttm" in peer_snapshots.columns else None
    if peer_pe is not None:
        peer_pe = peer_pe[(peer_pe > 0) & (peer_pe < 200)]
    peer_pe_med = float(peer_pe.median()) if peer_pe is not None and not peer_pe.empty else None

    if net_profit_ttm is None or peer_pe_med is None:
        logger.warning("Fallback: core fair MCAP uses market cap directly.")
        core_fair_mcap = market_cap
        confidence = "low"
    else:
        core_fair_mcap = net_profit_ttm * peer_pe_med
        confidence = "medium"

    core_cheapness = core_fair_mcap / market_cap - 1 if market_cap else 0.0
    return float(core_fair_mcap), float(core_cheapness), confidence
