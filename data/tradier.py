"""Tradier REST API client — price history, timesales, quotes, options.

Auth header on every request: Authorization: Bearer {TRADIER_TOKEN}.
All calls are wrapped with tenacity retry (exponential backoff, max 4 attempts)
and respect a self-imposed rate limit of ≤ 120 requests/minute.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_history(
    symbol: str,
    interval: str = "daily",
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> pd.DataFrame:
    """Fetch daily (or other interval) OHLCV history from Tradier.

    GET /markets/history

    Returns a DataFrame indexed by date with columns:
        open, high, low, close, volume
    """
    raise NotImplementedError


def get_timesales(
    symbol: str,
    interval: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
    session_filter: str = "open",
) -> pd.DataFrame:
    """Fetch intraday timesales and resample to the requested bar size.

    GET /markets/timesales
    interval ∈ {"1min", "5min", "15min"}

    Build 1H and 4H bars by resampling 15-min/5-min data in pandas.
    Always drops the still-forming (incomplete) last bar.

    Returns a DataFrame indexed by datetime with columns:
        open, high, low, close, volume
    """
    raise NotImplementedError


def get_quotes(symbols: list[str]) -> pd.DataFrame:
    """Fetch real-time (sandbox: ~15 min delayed) quotes for up to 100 symbols.

    GET /markets/quotes?symbols=a,b,c

    Returns a DataFrame indexed by symbol.
    """
    raise NotImplementedError


def get_option_expirations(symbol: str) -> list[str]:
    """Return available option expiration dates for *symbol* as YYYY-MM-DD strings.

    GET /markets/options/expirations?symbol=...&includeAllRoots=true&strikes=true
    """
    raise NotImplementedError


def get_option_chain(symbol: str, expiration: str) -> pd.DataFrame:
    """Fetch the full option chain with Greeks for *symbol* on *expiration*.

    GET /markets/options/chains?symbol=...&expiration=YYYY-MM-DD&greeks=true

    Returns a DataFrame with per-strike rows including columns:
        strike, option_type, bid, ask, last, volume, open_interest,
        delta, gamma, theta, vega, bid_iv, mid_iv, ask_iv
    """
    raise NotImplementedError


def get_option_roots(symbol: str) -> list[str]:
    """Return the option root symbols for *symbol* (e.g. SPXW, XSPW for weeklies).

    GET /markets/options/lookup?underlying=...
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Internal helpers (private)
# ---------------------------------------------------------------------------

def _session() -> "requests.Session":  # type: ignore[name-defined]  # noqa: F821
    """Build an authenticated requests.Session for Tradier."""
    raise NotImplementedError


def _resample_to_tf(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample a minute-bar DataFrame to *tf* (e.g. '1H', '4H').

    Drops the last (potentially incomplete) bar.
    """
    raise NotImplementedError
