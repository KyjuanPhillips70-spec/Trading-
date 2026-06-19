"""Core ICT building-block indicators.

These are the foundation everything else depends on — tested first.
"""

from __future__ import annotations

import pandas as pd


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Standard Average True Range.

    Args:
        df:     OHLCV DataFrame with columns high, low, close.
        length: Rolling window length.

    Returns:
        Series of ATR values aligned to df's index.
    """
    raise NotImplementedError


def swing_points(df: pd.DataFrame, k: int = 2) -> tuple[pd.Series, pd.Series]:
    """Detect fractal swing highs and swing lows.

    A bar at index i is a **swing high** if df['high'][i] is strictly greater
    than the high of the k bars immediately before AND the k bars immediately
    after it.  Swing low is the mirror using df['low'].

    Args:
        df: OHLCV DataFrame.
        k:  Number of bars on each side.  Use k=2 for LTF, k=3 for HTF.

    Returns:
        (swing_high, swing_low): Boolean Series, True where the condition holds.
    """
    raise NotImplementedError


def displacement(
    df: pd.DataFrame,
    atr_length: int = 10,
    mult: float = 1.5,
) -> pd.Series:
    """Boolean Series: True where a candle qualifies as displacement.

    A candle is displacement if:
      abs(close - open) >= mult * atr(df, atr_length).shift(1)
    OR the candle is the middle candle of a valid FVG (see pdarrays.py).

    Displacement distinguishes a real structural break from a stop-run wick.
    """
    raise NotImplementedError


def dealing_range(
    df: pd.DataFrame,
    lookback: int,
) -> dict[str, float]:
    """Return the most recent confirmed dealing range and helper levels.

    Scans *lookback* bars for the most recent confirmed swing low and swing high.

    Returns a dict with keys:
        range_low, range_high, equilibrium, premium_threshold, discount_threshold
    where premium = above equilibrium, discount = below equilibrium.
    """
    raise NotImplementedError


def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential moving average of *series* with span *length*."""
    raise NotImplementedError
