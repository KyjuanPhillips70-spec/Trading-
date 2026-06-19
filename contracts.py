"""Option contract selection — DTE, delta, Greeks, settlement labels.

Hard Requirements:
  §5 — contract must have ≥ 7 calendar days to expiration (target 7–14 DTE).
  §5 — |delta| ≈ 0.45–0.65 (ATM to slightly ITM).
  Reject |delta| < 0.30 for any 1:1 R:R trade.

Settlement labels (must appear in every alert):
  SPX, XSP      → cash-settled, European-style, Section 1256 (60/40 tax),
                   no early assignment.  XSP ≈ 1/10 SPX notional.
                   Use weekly roots SPXW / XSPW for PM-settled weeklies.
  QQQ, NVDA, PLTR, AMD, TSLA
                → American-style, physically settled (shares), standard
                   equity tax, early-assignment / pin risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional


OptionType = Literal["call", "put"]


SETTLEMENT_NOTES: dict[str, str] = {
    "SPX":  "Cash-settled, European-style, Section 1256 (60/40 tax), no early assignment. Use SPXW roots for PM-settled weeklies.",
    "XSP":  "Cash-settled, European-style, Section 1256 (60/40 tax), no early assignment. ≈1/10 SPX notional; watch wider spreads. Use XSPW roots.",
    "QQQ":  "American-style, physically settled (shares), standard equity tax, early-assignment/pin risk.",
    "NVDA": "American-style, physically settled (shares), standard equity tax, early-assignment/pin risk.",
    "PLTR": "American-style, physically settled (shares), standard equity tax, early-assignment/pin risk.",
    "AMD":  "American-style, physically settled (shares), standard equity tax, early-assignment/pin risk.",
    "TSLA": "American-style, physically settled (shares), standard equity tax, early-assignment/pin risk.",
}


@dataclass
class Contract:
    symbol: str           # OCC option symbol
    option_type: OptionType
    strike: float
    expiry: date
    dte: int
    bid: float
    ask: float
    mid: float
    delta: float
    theta: float
    gamma: float
    vega: float
    iv: float
    open_interest: int
    volume: int
    settlement_note: str
    iv_warning: bool = False


def select_contract(
    ticker: str,
    direction: Literal["long", "short"],
    entry_price: float,
    stop_price: float,
    target_price: float,
    today: Optional[date] = None,
    dte_min: int = 7,
    dte_max: int = 14,
    delta_min: float = 0.45,
    delta_max: float = 0.65,
) -> Optional[Contract]:
    """Choose the best-fit option contract for the given setup.

    Steps (§10.3):
      1. Pull expirations; select nearest expiry with DTE in [dte_min, dte_max].
         If none, pick smallest DTE ≥ dte_min and note it.
      2. Pull option chain with Greeks.
      3. Filter to call (long) or put (short); target |delta| in [delta_min, delta_max].
      4. Among candidates prefer tightest bid/ask spread and highest OI/volume.
      5. Flag elevated IV.

    Returns None if no suitable contract is found.
    """
    raise NotImplementedError
