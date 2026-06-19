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
from datetime import date, datetime
from typing import Literal, Optional

import pandas as pd

from data import tradier


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
    oi: int
    volume: int
    settlement_note: str
    iv_warning: bool = False


def settlement_note(ticker: str) -> str:
    """Return the settlement/tax note for *ticker* (defaults to equity-style)."""
    return SETTLEMENT_NOTES.get(
        ticker.upper(),
        "American-style, physically settled (shares), standard equity tax, early-assignment/pin risk.",
    )


def _dte(expiry: str, today: date) -> int:
    """Calendar days from *today* to the *expiry* (YYYY-MM-DD) string."""
    exp = datetime.strptime(expiry, "%Y-%m-%d").date()
    return (exp - today).days


def choose_expiration(
    expirations: list[str],
    today: date,
    dte_min: int = 7,
    dte_max: int = 14,
) -> Optional[tuple[str, int]]:
    """Pick the best expiration string and its DTE.

    Prefer the nearest expiry with DTE in [dte_min, dte_max]. If none fall in
    range, fall back to the smallest DTE ≥ dte_min. Returns None if every
    expiration is below dte_min.
    """
    dated = sorted(
        ((exp, _dte(exp, today)) for exp in expirations),
        key=lambda t: t[1],
    )
    in_range = [t for t in dated if dte_min <= t[1] <= dte_max]
    if in_range:
        return in_range[0]
    above_min = [t for t in dated if t[1] >= dte_min]
    if above_min:
        return above_min[0]
    return None


def _mid(bid: float, ask: float) -> float:
    if bid <= 0 and ask <= 0:
        return 0.0
    if bid <= 0:
        return round(ask, 4)
    if ask <= 0:
        return round(bid, 4)
    return round((bid + ask) / 2.0, 4)


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
    delta_reject: float = 0.30,
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
    today = today or date.today()
    opt_type: OptionType = "call" if direction == "long" else "put"

    expirations = tradier.get_option_expirations(ticker)
    if not expirations:
        return None

    chosen = choose_expiration(expirations, today, dte_min=dte_min, dte_max=dte_max)
    if chosen is None:
        return None
    expiry_str, dte = chosen

    chain = tradier.get_option_chain(ticker, expiry_str)
    if chain.empty or "option_type" not in chain.columns:
        return None

    side = chain[chain["option_type"] == opt_type].copy()
    if side.empty or "delta" not in side.columns:
        return None

    side["delta"] = pd.to_numeric(side["delta"], errors="coerce")
    side = side.dropna(subset=["delta"])
    side["abs_delta"] = side["delta"].abs()

    # Reject lottery tickets outright.
    side = side[side["abs_delta"] >= delta_reject]
    if side.empty:
        return None

    # Preferred band; if nothing in band, fall back to closest to band centre.
    band = side[(side["abs_delta"] >= delta_min) & (side["abs_delta"] <= delta_max)]
    band_centre = (delta_min + delta_max) / 2.0
    candidates = band if not band.empty else side
    candidates = candidates.copy()

    for col in ("bid", "ask", "open_interest", "volume", "mid_iv"):
        if col in candidates.columns:
            candidates[col] = pd.to_numeric(candidates[col], errors="coerce")

    candidates["spread"] = (candidates["ask"] - candidates["bid"]).abs()
    candidates["delta_dist"] = (candidates["abs_delta"] - band_centre).abs()

    liquidity = candidates.get("open_interest")
    if liquidity is None:
        candidates["_liq"] = 0.0
    else:
        candidates["_liq"] = candidates["open_interest"].fillna(0)

    # Tightest spread, closest to band centre, deepest liquidity.
    candidates = candidates.sort_values(
        by=["spread", "delta_dist", "_liq"],
        ascending=[True, True, False],
    )
    row = candidates.iloc[0]

    bid = float(row.get("bid") or 0.0)
    ask = float(row.get("ask") or 0.0)
    iv = float(row.get("mid_iv") or 0.0)

    # IV warning: elevated relative to the rest of this side of the chain.
    iv_warning = False
    if "mid_iv" in side.columns:
        chain_iv = pd.to_numeric(side["mid_iv"], errors="coerce").dropna()
        if len(chain_iv) >= 3 and iv > 0:
            median_iv = float(chain_iv.median())
            if median_iv > 0 and iv > 1.5 * median_iv:
                iv_warning = True

    return Contract(
        symbol=str(row.get("symbol", "")),
        option_type=opt_type,
        strike=float(row.get("strike") or 0.0),
        expiry=datetime.strptime(expiry_str, "%Y-%m-%d").date(),
        dte=dte,
        bid=bid,
        ask=ask,
        mid=_mid(bid, ask),
        delta=float(row.get("delta") or 0.0),
        theta=float(row.get("theta") or 0.0),
        gamma=float(row.get("gamma") or 0.0),
        vega=float(row.get("vega") or 0.0),
        iv=iv,
        oi=int(row.get("open_interest") or 0),
        volume=int(row.get("volume") or 0),
        settlement_note=settlement_note(ticker),
        iv_warning=iv_warning,
    )
