"""Core ICT building-block indicators.

These are the foundation everything else depends on — tested first.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Standard Average True Range (Wilder's smoothing = RMA).

    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR        = RMA(TR, length)  — Wilder's EWM with alpha = 1/length

    Args:
        df:     OHLCV DataFrame with columns high, low, close.
        length: Smoothing window (Wilder).

    Returns:
        Series of ATR values, same index as df.
    """
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Wilder smoothing: seed with first SMA, then alpha = 1/length.
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def swing_points(df: pd.DataFrame, k: int = 2) -> tuple[pd.Series, pd.Series]:
    """Detect fractal swing highs and swing lows.

    A bar at index i is a **swing high** if df['high'][i] is strictly greater
    than the high of the k bars immediately before AND the k bars immediately
    after it.  Swing low is the mirror using df['low'].

    Args:
        df: OHLCV DataFrame.
        k:  Bars on each side.  Use k=2 for LTF (1H/15m), k=3 for HTF (4H/Daily).

    Returns:
        (swing_high, swing_low): Boolean Series, True where the condition holds.
        The first and last k bars are always False (insufficient neighbours).
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)

    for i in range(k, n - k):
        left_h = highs[i - k : i]
        right_h = highs[i + 1 : i + k + 1]
        if highs[i] > left_h.max() and highs[i] > right_h.max():
            sh[i] = True

        left_l = lows[i - k : i]
        right_l = lows[i + 1 : i + k + 1]
        if lows[i] < left_l.min() and lows[i] < right_l.min():
            sl[i] = True

    return (
        pd.Series(sh, index=df.index, name="swing_high"),
        pd.Series(sl, index=df.index, name="swing_low"),
    )


def displacement(
    df: pd.DataFrame,
    atr_length: int = 10,
    mult: float = 1.5,
) -> pd.Series:
    """Boolean Series: True where a candle qualifies as displacement.

    Condition: abs(close - open) >= mult * ATR(atr_length).shift(1).

    The FVG middle-candle check (§6) is applied by pdarrays.py at build time
    so it can OR into this series without a circular dependency.

    Displacement distinguishes a real structural break from a stop-run wick.
    """
    body = (df["close"] - df["open"]).abs()
    threshold = mult * atr(df, atr_length).shift(1)
    result = body >= threshold
    result.name = "displacement"
    return result


def dealing_range(
    df: pd.DataFrame,
    lookback: int,
) -> dict[str, float]:
    """Return the most recent confirmed dealing range and helper levels.

    Scans the last *lookback* bars (using k=2 swing detection) for the most
    recent confirmed swing low and swing high.

    Returns a dict with keys:
        range_low           — confirmed swing low
        range_high          — confirmed swing high
        equilibrium         — (range_high + range_low) / 2
        premium_threshold   — equilibrium  (anything above = premium)
        discount_threshold  — equilibrium  (anything below = discount)

    Raises ValueError if fewer than 2*k+1 bars are available or no swing
    points are found within the lookback window.
    """
    window = df.iloc[-lookback:] if len(df) > lookback else df
    sh, sl = swing_points(window, k=2)

    high_vals = window.loc[sh, "high"]
    low_vals = window.loc[sl, "low"]

    if high_vals.empty or low_vals.empty:
        raise ValueError(
            f"No confirmed swing points found in the last {lookback} bars. "
            "Increase lookback or supply more data."
        )

    range_high = float(high_vals.iloc[-1])
    range_low = float(low_vals.iloc[-1])

    if range_low > range_high:
        range_low, range_high = range_high, range_low

    eq = (range_high + range_low) / 2.0

    return {
        "range_low": range_low,
        "range_high": range_high,
        "equilibrium": eq,
        "premium_threshold": eq,
        "discount_threshold": eq,
    }


def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential moving average of *series* with span *length*.

    Uses pandas ewm with span=length (alpha = 2/(length+1)), adjust=False
    to match most charting platforms (TradingView / ICT default).
    """
    return series.ewm(span=length, adjust=False).mean()
