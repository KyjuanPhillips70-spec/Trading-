"""Liquidity pools, equal highs/lows, and sweep / stop-hunt detection.

Definitions:
  BSL (Buy-Side Liquidity):   resting stops above old/equal highs, PDH, PWH.
  SSL (Sell-Side Liquidity):  resting stops below old/equal lows, PDL, PWL.

Sweep rule:
  A BSL sweep: high > pool_level AND close < pool_level within sweep_window.
  A SSL sweep: low  < pool_level AND close > pool_level within sweep_window.
  The reversal CLOSE — not the wick — defines the sweep.

Directional context:
  Bullish HTF bias → look for SSL sweeps before continuation up.
  Bearish HTF bias → look for BSL sweeps before continuation down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd

from ict.primitives import atr, swing_points


PoolSide = Literal["BSL", "SSL"]
PoolSource = Literal["equal_highs", "equal_lows", "PDH", "PDL", "PWH", "PWL", "swing_high", "swing_low"]


@dataclass
class LiquidityPool:
    pool_level: float
    side: PoolSide
    source: PoolSource
    formed_index: int
    swept: bool = False
    sweep_index: Optional[int] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _prior_day_levels(df: pd.DataFrame) -> list[LiquidityPool]:
    """Return PDH and PDL pools derived from daily grouping of *df*."""
    pools: list[LiquidityPool] = []
    if not isinstance(df.index, pd.DatetimeIndex):
        return pools

    days = list(df.groupby(df.index.normalize()))
    for i in range(1, len(days)):
        prev_date, prev_day = days[i - 1]
        curr_date, curr_day = days[i]
        if prev_day.empty or curr_day.empty:
            continue
        pdh = float(prev_day["high"].max())
        pdl = float(prev_day["low"].min())
        # formed_index = first bar of the current day
        formed = df.index.get_loc(curr_day.index[0])
        if isinstance(formed, int):
            formed_i = formed
        elif isinstance(formed, slice):
            formed_i = int(formed.start)
        else:
            import numpy as np
            formed_i = int(np.argmax(formed))
        pools.append(LiquidityPool(pool_level=pdh, side="BSL", source="PDH", formed_index=formed_i))
        pools.append(LiquidityPool(pool_level=pdl, side="SSL", source="PDL", formed_index=formed_i))
    return pools


def _prior_week_levels(df: pd.DataFrame) -> list[LiquidityPool]:
    """Return PWH and PWL pools."""
    pools: list[LiquidityPool] = []
    if not isinstance(df.index, pd.DatetimeIndex):
        return pools

    weeks = list(df.groupby(df.index.to_period("W")))
    for i in range(1, len(weeks)):
        _, prev_week = weeks[i - 1]
        _, curr_week = weeks[i]
        if prev_week.empty or curr_week.empty:
            continue
        pwh = float(prev_week["high"].max())
        pwl = float(prev_week["low"].min())
        formed = df.index.get_loc(curr_week.index[0])
        formed_i = formed if isinstance(formed, int) else int(formed.start)
        pools.append(LiquidityPool(pool_level=pwh, side="BSL", source="PWH", formed_index=formed_i))
        pools.append(LiquidityPool(pool_level=pwl, side="SSL", source="PWL", formed_index=formed_i))
    return pools


def _equal_levels(
    df: pd.DataFrame,
    sh_series: pd.Series,
    sl_series: pd.Series,
    tol: float,
) -> list[LiquidityPool]:
    """Detect equal highs and equal lows within *tol* price distance."""
    pools: list[LiquidityPool] = []

    sh_idx = [i for i in range(len(df)) if sh_series.iloc[i]]
    sl_idx = [i for i in range(len(df)) if sl_series.iloc[i]]

    highs = df["high"].values
    lows = df["low"].values

    # Equal highs: pairs of swing highs within tol of each other.
    for j in range(len(sh_idx)):
        for k_idx in range(j + 1, len(sh_idx)):
            i, m = sh_idx[j], sh_idx[k_idx]
            if abs(highs[i] - highs[m]) <= tol:
                pools.append(
                    LiquidityPool(
                        pool_level=(highs[i] + highs[m]) / 2,
                        side="BSL",
                        source="equal_highs",
                        formed_index=m,
                    )
                )

    # Equal lows.
    for j in range(len(sl_idx)):
        for k_idx in range(j + 1, len(sl_idx)):
            i, m = sl_idx[j], sl_idx[k_idx]
            if abs(lows[i] - lows[m]) <= tol:
                pools.append(
                    LiquidityPool(
                        pool_level=(lows[i] + lows[m]) / 2,
                        side="SSL",
                        source="equal_lows",
                        formed_index=m,
                    )
                )

    return pools


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_liquidity_pools(
    df: pd.DataFrame,
    k: int = 2,
    equal_tol_atr: float = 0.1,
    atr_length: int = 14,
) -> list[LiquidityPool]:
    """Identify all BSL and SSL pools in *df*.

    Includes:
      - Swing highs/lows (fractals with strength k).
      - Equal highs / equal lows (within equal_tol_atr * ATR tolerance).
      - Prior-day high/low and prior-week high/low.
    """
    pools: list[LiquidityPool] = []

    if df.empty:
        return pools

    sh_series, sl_series = swing_points(df, k=k)
    atr_series = atr(df, length=atr_length)
    tol = float(atr_series.iloc[-1]) * equal_tol_atr if not atr_series.dropna().empty else 0.0

    highs = df["high"].values
    lows = df["low"].values

    # Swing high/low pools.
    for i in range(len(df)):
        if sh_series.iloc[i]:
            pools.append(
                LiquidityPool(
                    pool_level=float(highs[i]),
                    side="BSL",
                    source="swing_high",
                    formed_index=i,
                )
            )
        if sl_series.iloc[i]:
            pools.append(
                LiquidityPool(
                    pool_level=float(lows[i]),
                    side="SSL",
                    source="swing_low",
                    formed_index=i,
                )
            )

    # Equal highs/lows.
    pools.extend(_equal_levels(df, sh_series, sl_series, tol))

    # Prior-day and prior-week levels (only meaningful for intraday data).
    pools.extend(_prior_day_levels(df))
    pools.extend(_prior_week_levels(df))

    return pools


def detect_sweeps(
    pools: list[LiquidityPool],
    df: pd.DataFrame,
    sweep_window: int = 3,
) -> list[LiquidityPool]:
    """Return *pools* with swept=True / sweep_index set where a sweep occurred.

    BSL sweep: within *sweep_window* bars of the pool, price wicks ABOVE the
               pool level (high > pool_level) AND closes BACK BELOW it
               (close < pool_level).
    SSL sweep: low < pool_level AND close > pool_level within sweep_window.

    The reversal close — not the wick — defines the sweep.
    """
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)

    result: list[LiquidityPool] = []
    for pool in pools:
        p = pool.pool_level
        start = pool.formed_index + 1  # only look at bars AFTER the pool formed

        swept = False
        sweep_idx: Optional[int] = None
        bars_without_wick = 0

        for i in range(start, n):
            if pool.side == "BSL":
                if highs[i] > p and closes[i] < p:
                    swept = True
                    sweep_idx = i
                    break
                if highs[i] <= p:
                    bars_without_wick += 1
                    if bars_without_wick >= sweep_window:
                        break
                else:
                    bars_without_wick = 0  # wick above pool but no reversal close yet
            else:  # SSL
                if lows[i] < p and closes[i] > p:
                    swept = True
                    sweep_idx = i
                    break
                if lows[i] >= p:
                    bars_without_wick += 1
                    if bars_without_wick >= sweep_window:
                        break
                else:
                    bars_without_wick = 0

        result.append(
            LiquidityPool(
                pool_level=pool.pool_level,
                side=pool.side,
                source=pool.source,
                formed_index=pool.formed_index,
                swept=swept,
                sweep_index=sweep_idx,
            )
        )

    return result


def latest_sweep(
    pools: list[LiquidityPool],
    side: PoolSide,
    after_index: int = 0,
) -> Optional[LiquidityPool]:
    """Return the most recent swept pool of the given side at or after *after_index*, or None."""
    candidates = [
        p for p in pools
        if p.swept and p.side == side and p.sweep_index is not None and p.sweep_index >= after_index
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.sweep_index)  # type: ignore[arg-type]
