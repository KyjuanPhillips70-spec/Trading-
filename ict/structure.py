"""Market structure: BOS (Break of Structure) and MSS/CHoCH (Market Structure Shift).

Maintains the running sequence of confirmed swing highs and lows to classify
trend direction and detect structural breaks.

Rules:
  BOS (continuation)  — body close above most recent confirmed swing high (bull)
                         or below most recent swing low (bear).
  MSS (reversal)      — body close with displacement through the opposing swing
                         level, signalling a trend change.

Body closes only — wick-through events never count as BOS or MSS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


StructureEventType = Literal["BOS", "MSS"]
Direction = Literal["bullish", "bearish"]


@dataclass
class StructureEvent:
    type: StructureEventType
    direction: Direction
    break_level: float
    index: int            # integer position in the source DataFrame
    displacement: bool


def detect_structure(df: pd.DataFrame, k: int = 2) -> list[StructureEvent]:
    """Scan *df* for BOS and MSS events.

    Args:
        df: OHLCV DataFrame (closed candles only).
        k:  Swing-point strength passed to primitives.swing_points.

    Returns:
        Chronological list of StructureEvent objects.
    """
    raise NotImplementedError


def current_trend(events: list[StructureEvent]) -> Literal["up", "down", "ranging"]:
    """Derive the current trend from the most recent structure events."""
    raise NotImplementedError
