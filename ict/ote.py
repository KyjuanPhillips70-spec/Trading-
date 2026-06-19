"""Optimal Trade Entry (OTE) — Fibonacci retracement zone 62–79%.

Anchor on the impulse/displacement leg using body-to-body anchors for stability.
Bullish: swing_low → swing_high.  Bearish: swing_high → swing_low.

OTE zone: 62%–79% retracement.  Sweet spot: 0.705.  EQ: 0.5.
Invalidation: candle BODY closes beyond the 1.0 level (the swing origin).
Profit projections: -0.27, -0.62, -1.0, -2.0, -2.5, -4.0 from the leg.

A retracement qualifies only when price is in 62–79% AND there is confluence
(an FVG, OB, or equal-liquidity level) inside that zone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd


Direction = Literal["bullish", "bearish"]


@dataclass
class OTEResult:
    in_ote: bool
    level: float                    # current retracement level (0–1)
    entry_zone: tuple[float, float] # (low_price, high_price) of 62–79% zone
    stop_ref: float                 # 1.0 level (the sweep extreme / swing origin)
    projections: dict[str, float]   # keyed by "-0.27", "-0.62", etc.
    has_confluence: bool = False
    invalidated: bool = False


def compute_ote(
    swing_origin: float,
    swing_end: float,
    current_price: float,
    direction: Direction,
    confluence_levels: Optional[list[float]] = None,
    ote_low: float = 0.62,
    ote_high: float = 0.79,
    ote_sweet: float = 0.705,
) -> OTEResult:
    """Calculate the OTE result for a retracement.

    Args:
        swing_origin:      The 1.0 Fibonacci anchor (sweep extreme).
        swing_end:         The 0.0 Fibonacci anchor (displacement end).
        current_price:     The price to check against the OTE zone.
        direction:         "bullish" or "bearish".
        confluence_levels: Optional list of nearby PD-array price levels.
        ote_low / ote_high / ote_sweet: OTE zone parameters from config.

    Returns:
        OTEResult with in_ote, projections, and confluence flag.
    """
    raise NotImplementedError


def projection_levels(
    swing_origin: float,
    swing_end: float,
    direction: Direction,
    ratios: tuple[float, ...] = (-0.27, -0.62, -1.0, -2.0, -2.5, -4.0),
) -> dict[str, float]:
    """Return price levels for each extension ratio.

    Keys are the string representations of the ratios (e.g. "-0.27").
    """
    raise NotImplementedError
