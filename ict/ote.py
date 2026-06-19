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

_DEFAULT_RATIOS: tuple[float, ...] = (-0.27, -0.62, -1.0, -2.0, -2.5, -4.0)


@dataclass
class OTEResult:
    in_ote: bool
    level: float                    # current retracement level (0–1)
    entry_zone: tuple[float, float] # (low_price, high_price) of 62–79% zone
    stop_ref: float                 # 1.0 level (the sweep extreme / swing origin)
    projections: dict[str, float]   # keyed by "-0.27", "-0.62", etc.
    has_confluence: bool = False
    invalidated: bool = False


def _fib_price(origin: float, end: float, ratio: float, direction: Direction) -> float:
    """Convert a Fibonacci ratio to an absolute price level.

    For a bullish leg (origin = low, end = high):
      price = end - ratio * (end - origin)
      ratio=0.62 → 62% pull-back from high toward low.

    For a bearish leg (origin = high, end = low):
      price = end + ratio * (origin - end)
      ratio=0.62 → 62% pull-back from low toward high.

    Projection ratios are negative (beyond swing_end), so the formula
    naturally extends past the 0.0 level.
    """
    leg = abs(end - origin)
    if direction == "bullish":
        return end - ratio * leg
    else:
        return end + ratio * leg


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

    Fibonacci anchoring:
      Bullish: origin = swing LOW (1.0), end = swing HIGH (0.0).
        Retracement price  = end - ratio * (end - origin)
        ratio = (end - current) / (end - origin)
      Bearish: origin = swing HIGH (1.0), end = swing LOW (0.0).
        ratio = (current - end) / (origin - end)

    Args:
        swing_origin:      The 1.0 Fibonacci anchor (sweep extreme / invalidation).
        swing_end:         The 0.0 Fibonacci anchor (displacement end / entry side).
        current_price:     The price to check against the OTE zone.
        direction:         "bullish" or "bearish".
        confluence_levels: Optional list of nearby PD-array price levels.
        ote_low / ote_high / ote_sweet: OTE zone parameters.

    Returns:
        OTEResult with in_ote, projections, and confluence flag.
    """
    leg = abs(swing_end - swing_origin)
    if leg == 0:
        return OTEResult(
            in_ote=False, level=0.0,
            entry_zone=(swing_end, swing_end),
            stop_ref=swing_origin,
            projections=projection_levels(swing_origin, swing_end, direction),
        )

    if direction == "bullish":
        # origin = low, end = high; retracement moves price back toward origin.
        ratio = (swing_end - current_price) / leg
        zone_low  = _fib_price(swing_origin, swing_end, ote_high, direction)  # 79% pull-back (lower price)
        zone_high = _fib_price(swing_origin, swing_end, ote_low,  direction)  # 62% pull-back (higher price)
    else:
        # origin = high, end = low; retracement moves price back toward origin.
        ratio = (current_price - swing_end) / leg
        zone_low  = _fib_price(swing_origin, swing_end, ote_low,  direction)  # 62% pull-back (lower price)
        zone_high = _fib_price(swing_origin, swing_end, ote_high, direction)  # 79% pull-back (higher price)

    ratio = max(0.0, ratio)  # clamp negative (price beyond swing_end)

    in_ote = ote_low <= ratio <= ote_high

    # Invalidation: body close beyond the 1.0 level.
    # We check whether current_price has already violated origin.
    if direction == "bullish":
        invalidated = current_price < swing_origin
    else:
        invalidated = current_price > swing_origin

    # Confluence: any supplied level falls inside the OTE zone.
    has_confluence = False
    if confluence_levels:
        for lvl in confluence_levels:
            if zone_low <= lvl <= zone_high:
                has_confluence = True
                break

    projs = projection_levels(swing_origin, swing_end, direction)

    return OTEResult(
        in_ote=in_ote and not invalidated,
        level=round(ratio, 6),
        entry_zone=(zone_low, zone_high),
        stop_ref=swing_origin,
        projections=projs,
        has_confluence=has_confluence,
        invalidated=invalidated,
    )


def projection_levels(
    swing_origin: float,
    swing_end: float,
    direction: Direction,
    ratios: tuple[float, ...] = _DEFAULT_RATIOS,
) -> dict[str, float]:
    """Return price levels for each extension ratio.

    Negative ratios project *beyond* swing_end (the 0.0 level) in the
    direction of the trade — these are the standard ICT profit targets.

    Keys are the string representations of the ratios (e.g. "-0.27").
    """
    return {
        str(r): round(_fib_price(swing_origin, swing_end, r, direction), 6)
        for r in ratios
    }
