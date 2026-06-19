"""PD arrays: Fair Value Gaps, Order Blocks, and Breaker Blocks.

§7 exact definitions
--------------------
FVG (3-candle):
  Candle numbering: candle1 = shift(2), candle2 = shift(1), candle3 = current.
  Bullish FVG (BISI): candle3.low  > candle1.high  → gap zone [candle1.high, candle3.low]
  Bearish FVG (SIBI): candle3.high < candle1.low   → gap zone [candle3.high, candle1.low]
  CE (Consequent Encroachment): midpoint of the gap.
  Validity: candle2 must be displacement-grade.

Order Block:
  Bullish OB: last bearish candle before an up-move that breaks structure.
  Bearish OB: last bullish candle before a down-move that breaks structure.
  Valid when all four criteria are met (see §7.2).

Breaker Block:
  A failed OB whose polarity has flipped (swept liquidity, BOS through OB,
  MSS on the other side).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd

from ict.primitives import atr, displacement


Direction = Literal["bullish", "bearish"]
FVGState = Literal["unmitigated", "mitigated"]
OBState  = Literal["unmitigated", "mitigated"]


@dataclass
class FVG:
    direction: Direction
    top: float
    bottom: float
    ce: float                     # Consequent Encroachment = (top+bottom)/2
    index: int                    # integer position of candle3 in source DataFrame
    state: FVGState = "unmitigated"
    inverted: bool = False        # True once price body-closes through against polarity


@dataclass
class OrderBlock:
    direction: Direction
    top: float
    bottom: float
    body_top: float
    body_bottom: float
    index: int
    has_fvg: bool = False
    strength: int = 0             # 0–3; higher = more confluent
    state: OBState = "unmitigated"


@dataclass
class BreakerBlock:
    direction: Direction          # flipped from the original OB
    top: float
    bottom: float
    origin_index: int             # index of the original OB candle


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_fvgs(
    df: pd.DataFrame,
    atr_length: int = 10,
    disp_mult: float = 1.5,
) -> list[FVG]:
    """Detect all valid Fair Value Gaps in *df*.

    3-candle rule (positions relative to each row i being candle3):
      candle1 = i-2, candle2 = i-1, candle3 = i.
      Bullish FVG: low[i] > high[i-2]   → gap [high[i-2], low[i]]
      Bearish FVG: high[i] < low[i-2]   → gap [high[i], low[i-2]]
      Validity filter: candle2 (i-1) must be displacement-grade.

    State is immediately checked: if current price has already traded back
    through the gap zone the FVG is marked mitigated on creation.
    """
    if len(df) < 3:
        return []

    disp_series = displacement(df, atr_length=atr_length, mult=disp_mult)
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)

    fvgs: list[FVG] = []

    for i in range(2, n):
        h1, l1 = highs[i - 2], lows[i - 2]   # candle1
        # candle2 displacement check
        if not bool(disp_series.iloc[i - 1]):
            continue

        h3, l3 = highs[i], lows[i]            # candle3

        if l3 > h1:
            # Bullish FVG
            top, bottom = l3, h1
            ce = (top + bottom) / 2.0
            # Already mitigated if price has since traded back into the zone.
            later_low = lows[i + 1:].min() if i + 1 < n else float("inf")
            state: FVGState = "mitigated" if later_low <= top else "unmitigated"
            fvgs.append(FVG(direction="bullish", top=top, bottom=bottom, ce=ce, index=i, state=state))

        elif h3 < l1:
            # Bearish FVG
            top, bottom = l1, h3
            ce = (top + bottom) / 2.0
            later_high = highs[i + 1:].max() if i + 1 < n else float("-inf")
            state = "mitigated" if later_high >= bottom else "unmitigated"
            fvgs.append(FVG(direction="bearish", top=top, bottom=bottom, ce=ce, index=i, state=state))

    return fvgs


def find_order_blocks(
    df: pd.DataFrame,
    structure_events: list,    # list[StructureEvent] — avoid circular import
    fvgs: list[FVG],
    atr_length: int = 10,
    disp_mult: float = 1.5,
) -> list[OrderBlock]:
    """Detect valid Order Blocks in *df*.

    For each structure event (BOS or MSS):
      Bullish impulse (bullish BOS/MSS):
        The OB candle is the LAST bearish (close < open) candle BEFORE the
        break bar (structure_event.index). Zone = [low, high] of that candle.
        Validity (all four required per §7.2):
          (a) impulse engulfs the OB candle's low (high of impulse > high of OB)
          (b) a bar closes beyond the OB body (close > body_top)
          (c) an FVG exists near the OB (within 5 bars after it)
          (d) the move produced the structure event (already satisfied by caller)
        Strength is incremented for each of (c) adjacent FVG, (d) MSS type.

      Bearish impulse: mirror logic with last bullish candle before a bearish break.
    """
    if df.empty or not structure_events:
        return []

    opens = df["open"].values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    obs: list[OrderBlock] = []
    fvg_indices = {f.index for f in fvgs}

    for event in structure_events:
        break_i = event.index
        if break_i < 1:
            continue

        if event.direction == "bullish":
            # Find last bearish candle before break_i.
            ob_i = None
            for j in range(break_i - 1, -1, -1):
                if closes[j] < opens[j]:
                    ob_i = j
                    break
            if ob_i is None:
                continue

            ob_high = highs[ob_i]
            ob_low = lows[ob_i]
            body_top = max(opens[ob_i], closes[ob_i])
            body_bottom = min(opens[ob_i], closes[ob_i])

            # (a) impulse engulfs OB low: any bar from ob_i+1 to break_i goes above ob_high
            engulfs = any(highs[j] > ob_high for j in range(ob_i + 1, break_i + 1))
            # (b) a close above OB body
            close_beyond = any(closes[j] > body_top for j in range(ob_i + 1, min(break_i + 3, n)))
            if not (engulfs and close_beyond):
                continue

            # (c) adjacent FVG within 5 bars after OB
            has_fvg = any(fi in fvg_indices for fi in range(ob_i, min(ob_i + 6, n)))

            strength = 0
            if has_fvg:
                strength += 1
            if event.type == "MSS":
                strength += 1
            if event.displacement:
                strength += 1

            later_low = lows[break_i + 1:].min() if break_i + 1 < n else float("inf")
            state: OBState = "mitigated" if later_low < ob_low else "unmitigated"

            obs.append(
                OrderBlock(
                    direction="bullish",
                    top=ob_high, bottom=ob_low,
                    body_top=body_top, body_bottom=body_bottom,
                    index=ob_i,
                    has_fvg=has_fvg,
                    strength=strength,
                    state=state,
                )
            )

        else:  # bearish
            # Find last bullish candle before break_i.
            ob_i = None
            for j in range(break_i - 1, -1, -1):
                if closes[j] > opens[j]:
                    ob_i = j
                    break
            if ob_i is None:
                continue

            ob_high = highs[ob_i]
            ob_low = lows[ob_i]
            body_top = max(opens[ob_i], closes[ob_i])
            body_bottom = min(opens[ob_i], closes[ob_i])

            engulfs = any(lows[j] < ob_low for j in range(ob_i + 1, break_i + 1))
            close_beyond = any(closes[j] < body_bottom for j in range(ob_i + 1, min(break_i + 3, n)))
            if not (engulfs and close_beyond):
                continue

            has_fvg = any(fi in fvg_indices for fi in range(ob_i, min(ob_i + 6, n)))

            strength = 0
            if has_fvg:
                strength += 1
            if event.type == "MSS":
                strength += 1
            if event.displacement:
                strength += 1

            later_high = highs[break_i + 1:].max() if break_i + 1 < n else float("-inf")
            state = "mitigated" if later_high > ob_high else "unmitigated"

            obs.append(
                OrderBlock(
                    direction="bearish",
                    top=ob_high, bottom=ob_low,
                    body_top=body_top, body_bottom=body_bottom,
                    index=ob_i,
                    has_fvg=has_fvg,
                    strength=strength,
                    state=state,
                )
            )

    return obs


def find_breaker_blocks(
    df: pd.DataFrame,
    order_blocks: list[OrderBlock],
    structure_events: list,    # list[StructureEvent]
) -> list[BreakerBlock]:
    """Identify Breaker Blocks from failed (mitigated) Order Blocks.

    A breaker is a mitigated OB whose direction has flipped:
      - A bullish OB that price traded below (mitigated) becomes a bearish breaker.
      - A bearish OB that price traded above becomes a bullish breaker.
    We confirm the flip with a subsequent opposite-direction structure event
    after the OB's index.
    """
    if not order_blocks or not structure_events:
        return []

    event_dirs = {e.index: e.direction for e in structure_events}
    breakers: list[BreakerBlock] = []

    for ob in order_blocks:
        if ob.state != "mitigated":
            continue

        # Check for a confirming opposite-direction event after the OB.
        flip_dir: Direction = "bearish" if ob.direction == "bullish" else "bullish"
        confirmed = any(
            e.direction == flip_dir and e.index > ob.index
            for e in structure_events
        )
        if not confirmed:
            continue

        breakers.append(
            BreakerBlock(
                direction=flip_dir,
                top=ob.top,
                bottom=ob.bottom,
                origin_index=ob.index,
            )
        )

    return breakers


def update_fvg_states(fvgs: list[FVG], df: pd.DataFrame) -> list[FVG]:
    """Mark FVGs as mitigated or inverted based on subsequent price action.

    Mitigation:
      Bullish FVG: price trades back down into the zone (low <= top of gap).
      Bearish FVG: price trades back up into the zone (high >= bottom of gap).

    Inversion:
      Bullish FVG: a candle *body closes* below the gap bottom → inverted (now bearish).
      Bearish FVG: a candle *body closes* above the gap top    → inverted (now bullish).
    """
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    closes = df["close"].values
    n = len(df)

    updated: list[FVG] = []
    for fvg in fvgs:
        start = fvg.index + 1
        mitigated = fvg.state == "mitigated"
        inverted = fvg.inverted

        for i in range(start, n):
            if fvg.direction == "bullish":
                if not mitigated and lows[i] <= fvg.top:
                    mitigated = True
                body_low = min(opens[i], closes[i])
                if not inverted and body_low < fvg.bottom:
                    inverted = True
            else:
                if not mitigated and highs[i] >= fvg.bottom:
                    mitigated = True
                body_high = max(opens[i], closes[i])
                if not inverted and body_high > fvg.top:
                    inverted = True

            if mitigated and inverted:
                break

        updated.append(
            FVG(
                direction=fvg.direction,
                top=fvg.top,
                bottom=fvg.bottom,
                ce=fvg.ce,
                index=fvg.index,
                state="mitigated" if mitigated else "unmitigated",
                inverted=inverted,
            )
        )

    return updated
