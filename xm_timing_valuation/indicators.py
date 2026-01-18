import math
from typing import Optional

import numpy as np
import pandas as pd


def compute_returns(prices: pd.Series) -> pd.Series:
    return prices.pct_change().dropna()


def realized_vol(prices: pd.Series, window: int) -> float:
    returns = compute_returns(prices)
    if returns.empty:
        return float("nan")
    rv = returns.rolling(window).std().iloc[-1]
    return float(rv) if rv is not None else float("nan")


def moving_average(prices: pd.Series, window: int) -> float:
    if prices.empty:
        return float("nan")
    return float(prices.rolling(window).mean().iloc[-1])


def max_drawdown(prices: pd.Series, window: int) -> float:
    if len(prices) < window:
        window = len(prices)
    recent = prices.iloc[-window:]
    roll_max = recent.cummax()
    dd = recent / roll_max - 1.0
    return float(dd.min())


def ewma(series: pd.Series, half_life: float) -> float:
    if series.empty:
        return float("nan")
    alpha = 1 - math.exp(math.log(0.5) / half_life)
    return float(series.ewm(alpha=alpha, adjust=False).mean().iloc[-1])


def sma(series: pd.Series, window: int) -> float:
    if series.empty:
        return float("nan")
    return float(series.rolling(window).mean().iloc[-1])


def safe_clip(value: float, low: float, high: float) -> float:
    return float(np.clip(value, low, high))


def compute_beta(returns: pd.Series, benchmark_returns: pd.Series) -> Optional[float]:
    aligned = pd.concat([returns, benchmark_returns], axis=1).dropna()
    if aligned.empty or len(aligned) < 5:
        return None
    cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])[0, 1]
    var = np.var(aligned.iloc[:, 1])
    if var == 0:
        return None
    return float(cov / var)
