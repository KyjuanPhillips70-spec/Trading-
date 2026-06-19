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

    Args:
        daily:          Daily OHLCV DataFrame.
        four_h:         4H OHLCV DataFrame.
        one_h:          1H OHLCV DataFrame.
        ticker:         The ticker symbol (used to apply stricter rules for indices).
        index_tickers:  List of tickers that require 4H+1H bias confirmation.
        ema_fast/slow:  EMA periods for daily bias stack.
        swing_k_htf:    Swing-point strength for HTF.
        swing_k_ltf:    Swing-point strength for LTF.

    Returns:
        BiasResult with bias in {"long", "short", "none"} and supporting detail.
    """
    raise NotImplementedError
