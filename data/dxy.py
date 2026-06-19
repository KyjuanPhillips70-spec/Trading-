"""DXY (US Dollar Index) data feed.

Primary source: yfinance ticker "DX-Y.NYB".
Fallback: UUP via Tradier daily history (flagged as source="UUP_proxy").

4H DXY: pull 1H from yfinance and resample; if unavailable use daily only.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd


DXYSource = Literal["DX-Y.NYB", "UUP_proxy", "DX=F"]


def get_dxy(
    period: str = "3mo",
    interval: str = "1d",
) -> tuple[pd.DataFrame, DXYSource]:
    """Return DXY OHLCV and the data source used.

    Tries yfinance DX-Y.NYB first; falls back to UUP via Tradier.

    Returns:
        df:     DataFrame with columns open, high, low, close, volume.
        source: One of "DX-Y.NYB", "UUP_proxy", or "DX=F".
    """
    raise NotImplementedError


def get_dxy_4h() -> tuple[pd.DataFrame, DXYSource]:
    """Return 4H DXY bars.

    Pulls 1H intraday from yfinance and resamples to 4H.
    Falls back to daily structure with a note if intraday is unavailable.
    """
    raise NotImplementedError
