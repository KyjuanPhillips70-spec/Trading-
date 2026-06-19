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
    raise NotImplementedError


def detect_sweeps(
    pools: list[LiquidityPool],
    df: pd.DataFrame,
    sweep_window: int = 3,
) -> list[LiquidityPool]:
    """Return *pools* with swept=True / sweep_index set where a sweep occurred."""
    raise NotImplementedError


def latest_sweep(
    pools: list[LiquidityPool],
    side: PoolSide,
    after_index: int = 0,
) -> Optional[LiquidityPool]:
    """Return the most recent swept pool of the given side, or None."""
    raise NotImplementedError
