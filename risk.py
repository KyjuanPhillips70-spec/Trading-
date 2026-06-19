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
    is_long = direction == "long"
    buffer = stop_buffer_atr * atr_value

    # --- Stop: just beyond the farther of sweep extreme / OB far edge. ---
    if is_long:
        stop_anchor = min(sweep_extreme, ob_far_edge)
        stop = stop_anchor - buffer
    else:
        stop_anchor = max(sweep_extreme, ob_far_edge)
        stop = stop_anchor + buffer

    risk = abs(entry - stop)
    if risk <= 0:
        return None

    # --- Target: next liquidity pool if it yields ≥ min_rr, else exactly 1:1. ---
    one_to_one = entry + risk if is_long else entry - risk

    target: Optional[float] = None
    if next_liquidity_pool is not None:
        pool_in_direction = (
            next_liquidity_pool > entry if is_long else next_liquidity_pool < entry
        )
        if pool_in_direction:
            pool_reward = abs(next_liquidity_pool - entry)
            if pool_reward / risk >= min_rr:
                target = next_liquidity_pool

    if target is None:
        target = one_to_one  # fall back to exactly 1:1

    reward = abs(target - entry)
    rr = reward / risk
    if rr < min_rr:
        return None

    # --- Option P/L translation (approximate). ---
    if contract is not None:
        option_debit = contract.mid
        option_gain = estimate_option_pl(contract, reward if is_long else -reward)
        option_loss = estimate_option_pl(contract, -risk if is_long else risk)
    else:
        option_debit = option_gain = option_loss = 0.0

    return RiskSetup(
        entry=round(entry, 4),
        stop=round(stop, 4),
        target=round(target, 4),
        risk=round(risk, 4),
        reward=round(reward, 4),
        rr=round(rr, 4),
        option_debit=round(option_debit, 4),
        option_gain=round(option_gain, 4),
        option_loss=round(option_loss, 4),
    )


def estimate_option_pl(
    contract: Contract,
    underlying_move: float,
) -> float:
    """Approximate option P/L (per contract, in dollars) for an underlying move.

    Uses delta for the linear estimate and gamma for the second-order term:
        Δprice ≈ delta * move + 0.5 * gamma * move²
    then scales by the 100-share contract multiplier. The premium can never go
    below zero for a long option, so the loss is floored at the full debit.

    Result is approximate — Greeks change as price and time move.
    """
    delta = contract.delta
    gamma = contract.gamma
    price_change = delta * underlying_move + 0.5 * gamma * (underlying_move ** 2)
    pl = price_change * 100.0
    # A long option can lose at most the premium paid.
    max_loss = -contract.mid * 100.0
    if pl < max_loss:
        pl = max_loss
    return round(pl, 4)
