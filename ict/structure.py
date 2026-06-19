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

from ict.primitives import displacement, swing_points


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

    Algorithm:
      1. Find all swing highs / lows (using primitives.swing_points).
      2. Walk bars left-to-right, maintaining the running most-recent confirmed
         swing high and swing low.
      3. At each bar check whether the *body* (open/close, not wick) closes
         beyond the active swing level.
         - If trend == "up" and body close > last swing high  → bullish BOS.
         - If trend == "down" and body close < last swing low → bearish BOS.
         - If trend == "up" and body close < last swing low WITH displacement
           → bearish MSS (reversal).
         - If trend == "down" and body close > last swing high WITH displacement
           → bullish MSS (reversal).
      4. After a BOS the broken level becomes the new reference; after an MSS
         the trend flips.

    Args:
        df: OHLCV DataFrame (closed candles only).
        k:  Swing-point strength passed to primitives.swing_points.

    Returns:
        Chronological list of StructureEvent objects.
    """
    if len(df) < 2 * k + 1:
        return []

    sh_series, sl_series = swing_points(df, k=k)
    disp_series = displacement(df)

    closes = df["close"].values
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    events: list[StructureEvent] = []

    last_sh_level: float | None = None
    last_sl_level: float | None = None
    last_sh_index: int = -1
    last_sl_index: int = -1
    trend: Literal["up", "down", "ranging"] = "ranging"

    for i in range(n):
        # Update known swing references before checking breaks.
        if sh_series.iloc[i]:
            last_sh_level = float(highs[i])
            last_sh_index = i
        if sl_series.iloc[i]:
            last_sl_level = float(lows[i])
            last_sl_index = i

        # Seed trend once we have both references.
        # Rule: the swing type confirmed LAST determines the current bias.
        #   last confirmed = swing HIGH → we just made a high → uptrend context.
        #   last confirmed = swing LOW  → we just made a low  → downtrend context.
        if trend == "ranging" and last_sh_level is not None and last_sl_level is not None:
            trend = "up" if last_sh_index > last_sl_index else "down"

        if trend == "ranging":
            continue

        body_high = max(opens[i], closes[i])
        body_low = min(opens[i], closes[i])
        is_disp = bool(disp_series.iloc[i])

        if trend == "up" and last_sh_level is not None:
            if closes[i] > last_sh_level:                   # body-close only
                events.append(
                    StructureEvent(
                        type="BOS",
                        direction="bullish",
                        break_level=last_sh_level,
                        index=i,
                        displacement=is_disp,
                    )
                )
                last_sh_level = body_high                   # use body, not wick

            elif last_sl_level is not None and closes[i] < last_sl_level and is_disp:
                events.append(
                    StructureEvent(
                        type="MSS",
                        direction="bearish",
                        break_level=last_sl_level,
                        index=i,
                        displacement=True,
                    )
                )
                trend = "down"
                last_sl_level = body_low                    # use body, not wick

        elif trend == "down" and last_sl_level is not None:
            if closes[i] < last_sl_level:                   # body-close only
                events.append(
                    StructureEvent(
                        type="BOS",
                        direction="bearish",
                        break_level=last_sl_level,
                        index=i,
                        displacement=is_disp,
                    )
                )
                last_sl_level = body_low                    # use body, not wick

            elif last_sh_level is not None and closes[i] > last_sh_level and is_disp:
                events.append(
                    StructureEvent(
                        type="MSS",
                        direction="bullish",
                        break_level=last_sh_level,
                        index=i,
                        displacement=True,
                    )
                )
                trend = "up"
                last_sh_level = body_high                   # use body, not wick

    return events


def current_trend(events: list[StructureEvent]) -> Literal["up", "down", "ranging"]:
    """Derive the current trend from the most recent structure events.

    The last MSS defines the current trend; if no MSS, the last BOS does.
    Returns "ranging" when no events are present.
    """
    if not events:
        return "ranging"
    # Most-recent event drives the answer.
    last = events[-1]
    return "up" if last.direction == "bullish" else "down"
