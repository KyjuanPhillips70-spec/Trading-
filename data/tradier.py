"""Tradier REST API client — price history, timesales, quotes, options.

Auth header on every request: Authorization: Bearer {TRADIER_TOKEN}.
All calls are wrapped with tenacity retry (exponential backoff, max 4 attempts)
and respect a self-imposed rate limit of ≤ 120 requests/minute.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


DEFAULT_BASE_URL = "https://sandbox.tradier.com/v1"
_OHLCV_COLS = ["open", "high", "low", "close", "volume"]
_RATE_LIMIT = 120          # requests per rolling 60s window
_RATE_WINDOW = 60.0

_request_times: "deque[float]" = deque()
_rate_lock = threading.Lock()
_session_obj: Optional[requests.Session] = None
_session_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _base_url() -> str:
    return os.environ.get("TRADIER_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _token() -> str:
    return os.environ.get("TRADIER_TOKEN", "")


def _fmt_date(d: Any) -> str:
    """Format a date/datetime/string as YYYY-MM-DD."""
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _fmt_datetime(d: Any) -> str:
    """Format for timesales: YYYY-MM-DD HH:MM when a time is present."""
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _empty_ohlcv() -> pd.DataFrame:
    df = pd.DataFrame(columns=_OHLCV_COLS)
    df.index = pd.DatetimeIndex([], name="datetime")
    return df


# ---------------------------------------------------------------------------
# Rate limiting + session + retrying request
# ---------------------------------------------------------------------------

def _throttle() -> None:
    """Block until issuing another request stays within ≤120 req/min."""
    with _rate_lock:
        now = time.monotonic()
        while _request_times and now - _request_times[0] > _RATE_WINDOW:
            _request_times.popleft()
        if len(_request_times) >= _RATE_LIMIT:
            sleep_for = _RATE_WINDOW - (now - _request_times[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
            while _request_times and now - _request_times[0] > _RATE_WINDOW:
                _request_times.popleft()
        _request_times.append(time.monotonic())


def _session() -> requests.Session:
    """Build (and memoise) an authenticated requests.Session for Tradier."""
    global _session_obj, _session_token
    token = _token()
    if _session_obj is None or _session_token != token:
        s = requests.Session()
        s.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
        )
        _session_obj = s
        _session_token = token
    return _session_obj


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type(requests.RequestException),
    reraise=True,
)
def _request(path: str, params: Optional[dict] = None) -> dict:
    """GET {base_url}{path} with auth, rate limiting, and retry; return JSON."""
    _throttle()
    url = f"{_base_url()}{path}"
    resp = _session().get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------

def resample_ohlcv(
    df: pd.DataFrame,
    tf: str,
    *,
    per_session: bool = True,
    origin: str = "start",
) -> pd.DataFrame:
    """Resample an OHLCV DataFrame to timeframe *tf* (e.g. '1H', '4H', '15min').

    Args:
        df:          Fine-grained OHLCV DataFrame with a DatetimeIndex.
        tf:          Target pandas offset alias (case-insensitive).
        per_session: When True (intraday equities), resample within each calendar
                     day so bars anchor to the session open and never span the
                     overnight gap. When False (≈24h instruments like DXY),
                     resample the whole series with *origin*.
        origin:      Pandas resample origin used when per_session is False.

    Always drops the final (potentially still-forming) bar.
    """
    if df.empty:
        return df.copy()

    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    tf_norm = tf.lower()

    if per_session:
        parts = [
            day.resample(tf_norm, origin="start").agg(agg).dropna(subset=["open"])
            for _, day in df.groupby(df.index.normalize())
        ]
        out = pd.concat(parts).sort_index() if parts else df.iloc[0:0]
    else:
        out = df.resample(tf_norm, origin=origin).agg(agg).dropna(subset=["open"])

    if len(out) > 0:
        out = out.iloc[:-1]  # closed candles only
    return out


# Spec-named alias (§5.1). Equities default: per-session anchoring.
def _resample_to_tf(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample a minute-bar DataFrame to *tf* (e.g. '1H', '4H').

    Drops the last (potentially incomplete) bar.
    """
    return resample_ohlcv(df, tf, per_session=True)


# ---------------------------------------------------------------------------
# Public API — price
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
    params: dict[str, Any] = {"symbol": symbol, "interval": interval}
    if start is not None:
        params["start"] = _fmt_date(start)
    if end is not None:
        params["end"] = _fmt_date(end)

    data = _request("/markets/history", params)
    history = data.get("history")
    if not history:
        return _empty_ohlcv()
    days = history.get("day")
    if days is None:
        return _empty_ohlcv()
    if isinstance(days, dict):
        days = [days]

    df = pd.DataFrame(days)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df.index.name = "date"
    return df[_OHLCV_COLS].astype(float)


def get_timesales(
    symbol: str,
    interval: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
    session_filter: str = "open",
) -> pd.DataFrame:
    """Fetch intraday timesales bars from Tradier.

    GET /markets/timesales
    interval ∈ {"1min", "5min", "15min"}

    Returns a DataFrame indexed by datetime with columns:
        open, high, low, close, volume

    Build 1H/4H bars from this via resample_ohlcv(); resampling always drops the
    still-forming last bar so callers work on closed candles only.
    """
    params: dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "session_filter": session_filter,
    }
    if start is not None:
        params["start"] = _fmt_datetime(start)
    if end is not None:
        params["end"] = _fmt_datetime(end)

    data = _request("/markets/timesales", params)
    series = data.get("series")
    if not series:
        return _empty_ohlcv()
    rows = series.get("data")
    if rows is None:
        return _empty_ohlcv()
    if isinstance(rows, dict):
        rows = [rows]

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time").sort_index()
    df.index.name = "datetime"
    return df[_OHLCV_COLS].astype(float)


def get_quotes(symbols: list[str]) -> pd.DataFrame:
    """Fetch quotes (sandbox: ~15 min delayed) for symbols, indexed by symbol.

    GET /markets/quotes?symbols=a,b,c

    Batches in groups of ≤100 symbols per the Tradier limit.
    """
    if not symbols:
        return pd.DataFrame()

    frames = []
    for i in range(0, len(symbols), 100):
        chunk = symbols[i : i + 100]
        data = _request("/markets/quotes", {"symbols": ",".join(chunk)})
        quotes = data.get("quotes")
        if not quotes:
            continue
        q = quotes.get("quote")
        if q is None:
            continue
        if isinstance(q, dict):
            q = [q]
        frames.append(pd.DataFrame(q))

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if "symbol" in df.columns:
        df = df.set_index("symbol")
    return df


# ---------------------------------------------------------------------------
# Public API — options
# ---------------------------------------------------------------------------

def get_option_expirations(symbol: str) -> list[str]:
    """Return available option expiration dates as YYYY-MM-DD strings.

    GET /markets/options/expirations?symbol=...&includeAllRoots=true&strikes=true
    """
    params = {"symbol": symbol, "includeAllRoots": "true", "strikes": "true"}
    data = _request("/markets/options/expirations", params)
    exp = data.get("expirations")
    if not exp:
        return []
    # strikes=true → {"expiration": [{"date": ..., "strikes": {...}}, ...]}
    if "expiration" in exp:
        items = exp["expiration"]
        if isinstance(items, dict):
            items = [items]
        return [it["date"] for it in items if "date" in it]
    # strikes=false → {"date": [...]}
    if "date" in exp:
        dates = exp["date"]
        if isinstance(dates, str):
            dates = [dates]
        return list(dates)
    return []


def get_option_chain(symbol: str, expiration: str) -> pd.DataFrame:
    """Fetch the full option chain with Greeks for *symbol* on *expiration*.

    GET /markets/options/chains?symbol=...&expiration=YYYY-MM-DD&greeks=true

    Returns a DataFrame with per-strike rows including columns:
        symbol, strike, option_type, bid, ask, last, volume, open_interest,
        delta, gamma, theta, vega, bid_iv, mid_iv, ask_iv
    """
    params = {"symbol": symbol, "expiration": expiration, "greeks": "true"}
    data = _request("/markets/options/chains", params)
    options = data.get("options")
    if not options:
        return pd.DataFrame()
    opts = options.get("option")
    if opts is None:
        return pd.DataFrame()
    if isinstance(opts, dict):
        opts = [opts]

    df = pd.json_normalize(opts)
    rename = {
        "greeks.delta": "delta",
        "greeks.gamma": "gamma",
        "greeks.theta": "theta",
        "greeks.vega": "vega",
        "greeks.bid_iv": "bid_iv",
        "greeks.mid_iv": "mid_iv",
        "greeks.ask_iv": "ask_iv",
    }
    return df.rename(columns=rename)


def get_option_roots(symbol: str) -> list[str]:
    """Return option root symbols for *symbol* (e.g. SPXW for weeklies).

    GET /markets/options/lookup?underlying=...
    """
    data = _request("/markets/options/lookup", {"underlying": symbol})
    symbols = data.get("symbols")
    if not symbols:
        return []
    if isinstance(symbols, dict):
        symbols = [symbols]
    return [s["rootSymbol"] for s in symbols if "rootSymbol" in s]
