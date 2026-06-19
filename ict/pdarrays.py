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

    Applies the 3-candle definition with displacement filter on candle2.
    Updates state (mitigated) if price has already traded back through the gap.
    """
    raise NotImplementedError


def find_order_blocks(
    df: pd.DataFrame,
    structure_events: list,    # list[StructureEvent] — avoid circular import
    fvgs: list[FVG],
    atr_length: int = 10,
    disp_mult: float = 1.5,
) -> list[OrderBlock]:
    """Detect valid Order Blocks in *df*.

    An OB requires all four validity conditions from §7.2.
    Sets has_fvg and strength based on adjacent FVG presence.
    """
    raise NotImplementedError


def find_breaker_blocks(
    df: pd.DataFrame,
    order_blocks: list[OrderBlock],
    structure_events: list,    # list[StructureEvent]
) -> list[BreakerBlock]:
    """Identify Breaker Blocks from failed Order Blocks."""
    raise NotImplementedError


def update_fvg_states(fvgs: list[FVG], df: pd.DataFrame) -> list[FVG]:
    """Mark FVGs as mitigated or inverted based on subsequent price action."""
    raise NotImplementedError
