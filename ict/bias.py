"""HTF directional bias using top-down multi-timeframe analysis.

Top-down order: Daily → 4H → 1H / 15m.

Daily bias is CLEAR only when market structure AND EMA stack agree:
  Bullish: HH/HL structure AND EMA10 > EMA20 (both rising, gap widening).
  Bearish: LH/LL structure AND EMA10 < EMA20 (both falling).
  If they disagree → bias = "none" → ticker is skipped.

Index/ETF (SPX, XSP, QQQ): require clear bias on BOTH 4H and 1H.
Single-name (NVDA, PLTR, AMD, TSLA): require Daily + 4H agreement, 1H trigger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd

from ict.primitives import ema, swing_points
from ict.structure import current_trend, detect_structure


BiasValue = Literal["long", "short", "none"]


@dataclass
class BiasResult:
    bias: BiasValue
    htf_zone: Optional[dict]      # nearest in-bias PD array on 4H
    reasons: list[str] = field(default_factory=list)
    daily_bias: BiasValue = "none"
    four_h_bias: BiasValue = "none"
    one_h_bias: BiasValue = "none"
    ema_stack_ok: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ema_stack_bias(df: pd.DataFrame, fast: int, slow: int) -> tuple[BiasValue, bool]:
    """Return (bias, stack_ok) from EMA fast/slow on *df*.

    Bullish stack: fast > slow, both rising (last bar > previous bar), gap widening.
    Bearish stack: fast < slow, both falling, gap widening negatively.
    Otherwise: "none", False.
    """
    if len(df) < slow + 2:
        return "none", False

    fast_s = ema(df["close"], fast)
    slow_s = ema(df["close"], slow)

    f_now, f_prev = float(fast_s.iloc[-1]), float(fast_s.iloc[-2])
    s_now, s_prev = float(slow_s.iloc[-1]), float(slow_s.iloc[-2])

    gap_now  = f_now - s_now
    gap_prev = f_prev - s_prev

    bullish = (
        f_now > s_now          # fast above slow
        and f_now > f_prev     # fast rising
        and s_now > s_prev     # slow rising
        and gap_now > gap_prev # gap widening
    )
    bearish = (
        f_now < s_now
        and f_now < f_prev
        and s_now < s_prev
        and gap_now < gap_prev
    )

    if bullish:
        return "long", True
    if bearish:
        return "short", True
    return "none", False


def _structure_bias(df: pd.DataFrame, k: int) -> BiasValue:
    """Derive bias from market structure on *df*."""
    if len(df) < 2 * k + 2:
        return "none"
    events = detect_structure(df, k=k)
    trend = current_trend(events)
    if trend == "up":
        return "long"
    if trend == "down":
        return "short"
    return "none"


def _timeframe_bias(df: pd.DataFrame, k: int) -> BiasValue:
    """Simple per-timeframe bias: structure BOS/MSS direction."""
    return _structure_bias(df, k)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_bias(
    daily: pd.DataFrame,
    four_h: pd.DataFrame,
    one_h: pd.DataFrame,
    ticker: str,
    index_tickers: list[str],
    ema_fast: int = 10,
    ema_slow: int = 20,
    swing_k_htf: int = 3,
    swing_k_ltf: int = 2,
) -> BiasResult:
    """Compute the top-down HTF directional bias for *ticker*.

    Step 1 — Daily: combine structure (HH/HL vs LH/LL) with EMA stack.
      Both must agree; otherwise daily_bias = "none" → return no-trade.

    Step 2 — 4H: confirm bias direction.

    Step 3 — 1H: confirm bias direction.
      For indices (SPX, XSP, QQQ): BOTH 4H and 1H must be clear (§10.1 hard req).
      For single names: Daily + 4H agreement required; 1H is the entry trigger.

    Returns:
        BiasResult with overall bias and per-timeframe breakdown.
    """
    reasons: list[str] = []

    # --- Daily ---
    struct_daily = _structure_bias(daily, k=swing_k_htf)
    ema_daily, stack_ok = _ema_stack_bias(daily, ema_fast, ema_slow)

    if struct_daily == "none" or ema_daily == "none":
        reasons.append(f"Daily structure={struct_daily}, EMA bias={ema_daily} — no clear agreement")
        return BiasResult(bias="none", htf_zone=None, reasons=reasons,
                          daily_bias="none", ema_stack_ok=stack_ok)

    if struct_daily != ema_daily:
        reasons.append(
            f"Daily structure ({struct_daily}) contradicts EMA stack ({ema_daily}) — skipping"
        )
        return BiasResult(bias="none", htf_zone=None, reasons=reasons,
                          daily_bias="none", ema_stack_ok=stack_ok)

    daily_bias: BiasValue = struct_daily
    reasons.append(f"Daily: {daily_bias} (structure + EMA stack agree, stack_ok={stack_ok})")

    # --- 4H ---
    four_h_bias = _timeframe_bias(four_h, k=swing_k_htf)
    reasons.append(f"4H: {four_h_bias}")

    if four_h_bias == "none" or four_h_bias != daily_bias:
        reasons.append("4H bias missing or contradicts daily — no trade")
        return BiasResult(bias="none", htf_zone=None, reasons=reasons,
                          daily_bias=daily_bias, four_h_bias=four_h_bias,
                          ema_stack_ok=stack_ok)

    # --- 1H ---
    one_h_bias = _timeframe_bias(one_h, k=swing_k_ltf)
    reasons.append(f"1H: {one_h_bias}")

    is_index = ticker.upper() in [t.upper() for t in index_tickers]

    if is_index:
        # Hard Requirement #1: indices need BOTH 4H and 1H clear.
        if one_h_bias == "none" or one_h_bias != daily_bias:
            reasons.append(f"{ticker} is an index — requires clear 1H bias too; got {one_h_bias}")
            return BiasResult(bias="none", htf_zone=None, reasons=reasons,
                              daily_bias=daily_bias, four_h_bias=four_h_bias,
                              one_h_bias=one_h_bias, ema_stack_ok=stack_ok)

    # 1H is the entry trigger for single names (doesn't block if unclear).
    overall: BiasValue = daily_bias
    reasons.append(f"Overall bias: {overall}")

    return BiasResult(
        bias=overall,
        htf_zone=None,   # populated by scanner.py using pdarrays on 4H
        reasons=reasons,
        daily_bias=daily_bias,
        four_h_bias=four_h_bias,
        one_h_bias=one_h_bias,
        ema_stack_ok=stack_ok,
    )
