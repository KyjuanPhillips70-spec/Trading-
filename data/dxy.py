"""DXY (US Dollar Index) data feed.

Primary source: yfinance ticker "DX-Y.NYB".
Fallback: UUP via Tradier daily history (flagged as source="UUP_proxy").

4H DXY: pull 1H from yfinance and resample; if unavailable use daily only.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd


DXYSource = Literal["DX-Y.NYB", "UUP_proxy", "DX=F"]

_OHLCV_COLS = ["open", "high", "low", "close", "volume"]


def _empty_ohlcv() -> pd.DataFrame:
    df = pd.DataFrame(columns=_OHLCV_COLS)
    df.index = pd.DatetimeIndex([], name="date")
    return df


def _standardize(hist: pd.DataFrame) -> pd.DataFrame:
    """Lower-case yfinance OHLCV columns and drop timezone info."""
    df = hist.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    cols = [c for c in _OHLCV_COLS if c in df.columns]
    df = df[cols].copy()
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index.name = "date"
    return df


def _yf_history(period: str, interval: str) -> pd.DataFrame:
    """Pull DX-Y.NYB history from yfinance; return empty frame on any failure."""
    try:
        import yfinance as yf

        hist = yf.Ticker("DX-Y.NYB").history(period=period, interval=interval)
        if hist is not None and not hist.empty:
            return _standardize(hist)
    except Exception:
        pass
    return _empty_ohlcv()


def get_dxy(
    period: str = "3mo",
    interval: str = "1d",
) -> tuple[pd.DataFrame, DXYSource]:
    """Return DXY OHLCV and the data source used.

    Tries yfinance DX-Y.NYB first; falls back to UUP via Tradier daily history.

    Returns:
        df:     DataFrame with columns open, high, low, close, volume.
        source: "DX-Y.NYB" on success, else "UUP_proxy".
    """
    df = _yf_history(period, interval)
    if not df.empty:
        return df, "DX-Y.NYB"

    # Fallback: UUP via Tradier daily history.
    try:
        from data.tradier import get_history

        uup = get_history("UUP", interval="daily")
        if uup is not None and not uup.empty:
            return uup, "UUP_proxy"
    except Exception:
        pass

    return _empty_ohlcv(), "UUP_proxy"


def get_dxy_4h() -> tuple[pd.DataFrame, DXYSource]:
    """Return 4H DXY bars.

    Pulls 1H intraday from yfinance and resamples to 4H. Falls back to daily
    structure (with the daily source flag) if intraday is unavailable.
    """
    hourly = _yf_history(period="1mo", interval="1h")
    if not hourly.empty:
        from data.tradier import resample_ohlcv

        # DXY trades ≈24h; anchor 4H bins to midnight rather than per-session.
        four_h = resample_ohlcv(hourly, "4H", per_session=False, origin="start_day")
        if not four_h.empty:
            return four_h, "DX-Y.NYB"

    # Intraday unavailable → daily structure only.
    return get_dxy(period="3mo", interval="1d")
