from typing import Dict

import numpy as np
import pandas as pd

from indicators import max_drawdown, realized_vol, safe_clip


def compute_risk_score(closes: pd.Series) -> Dict[str, float]:
    rv20 = realized_vol(closes, 20)
    rv60 = realized_vol(closes, 60)
    rv120 = realized_vol(closes, 120)
    dd120 = max_drawdown(closes, 120)

    vol_component = safe_clip((rv20 / rv120) if rv120 else 0.0, 0, 1) * 40
    dd_component = safe_clip(abs(dd120) / 0.25, 0, 1) * 40
    gap_component = 0.0

    risk_score = float(np.clip(vol_component + dd_component + gap_component, 0, 100))

    return {
        "risk_score": risk_score,
        "rv20": rv20,
        "rv60": rv60,
        "rv120": rv120,
        "dd120": dd120,
    }
