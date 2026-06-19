"""Risk / reward calculation and option P/L estimation.

Stop (underlying):  just beyond sweep extreme / far edge of OB,
                    plus buffer = STOP_BUFFER_ATR * ATR.
Target (underlying): next liquidity pool in the bias direction OR
                     exactly 1:1 distance from entry — whichever satisfies R:R ≥ 1:1.
Option P/L at target and stop estimated via delta (and gamma for larger moves).
All estimates are clearly labelled as approximate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from contracts import Contract


@dataclass
class RiskSetup:
    entry: float
    stop: float
    target: float
    risk: float           # abs(entry - stop)
    reward: float         # abs(target - entry)
    rr: float             # reward / risk
    option_debit: float   # estimated option cost at entry (mid)
    option_gain: float    # estimated P/L at target (approximate)
    option_loss: float    # estimated P/L at stop (approximate, negative)


def compute_risk(
    entry: float,
    sweep_extreme: float,
    ob_far_edge: float,
    next_liquidity_pool: Optional[float],
    direction: str,
    atr_value: float,
    contract: Optional[Contract] = None,
    stop_buffer_atr: float = 0.1,
    min_rr: float = 1.0,
) -> Optional[RiskSetup]:
    """Calculate entry, stop, target, and option P/L estimate.

    Returns None if R:R < min_rr and no fallback target achieves it.

    Args:
        entry:               Planned entry price in the underlying.
        sweep_extreme:       The wick/sweep level used as stop anchor.
        ob_far_edge:         Far edge of the Order Block (alternative stop anchor).
        next_liquidity_pool: Nearest BSL/SSL pool in the bias direction (target candidate).
        direction:           "long" or "short".
        atr_value:           Current ATR of the underlying on the entry timeframe.
        contract:            Optional selected option contract (for P/L translation).
        stop_buffer_atr:     ATR multiplier for stop padding.
        min_rr:              Minimum acceptable risk/reward ratio.
    """
    raise NotImplementedError


def estimate_option_pl(
    contract: Contract,
    underlying_move: float,
) -> float:
    """Approximate option P/L for a given underlying price move.

    Uses delta for a linear estimate and gamma for a second-order correction.
    Result is labelled approximate — Greeks change as price moves.
    """
    raise NotImplementedError
