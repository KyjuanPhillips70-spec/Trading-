"""Smoke-test the data layer (Stage 1).

Pulls one ticker's daily and 15-min bars and prints their shapes so you can
confirm the Tradier connection and resampling are working. Also resamples
15-min → 1H/4H and pulls DXY to verify the full data layer end-to-end.

Usage:
    python scripts/smoke_data.py [TICKER]

Default ticker: QQQ

Requires TRADIER_TOKEN (and optionally TRADIER_BASE_URL) in the environment.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

# Allow running as `python scripts/smoke_data.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.dxy import get_dxy  # noqa: E402
from data.tradier import get_history, get_timesales, resample_ohlcv  # noqa: E402


def _describe(name: str, df) -> None:
    if df is None or df.empty:
        print(f"  {name:<18} EMPTY")
        return
    print(
        f"  {name:<18} shape={df.shape}  "
        f"range={df.index.min()} .. {df.index.max()}"
    )


def main(ticker: str = "QQQ") -> None:
    if not os.environ.get("TRADIER_TOKEN"):
        print("WARNING: TRADIER_TOKEN is not set — live calls will return 401.")

    print(f"=== Data-layer smoke test: {ticker} ===\n")
    end = date.today()

    # Daily history (~120 calendar days back).
    daily = get_history(ticker, interval="daily", start=end - timedelta(days=120), end=end)
    print("Daily history:")
    _describe("daily", daily)
    if not daily.empty:
        print(daily.tail(3).to_string())
    print()

    # 15-minute intraday (~5 trading days back).
    m15 = get_timesales(ticker, interval="15min", start=end - timedelta(days=5), end=end)
    print("15-min timesales:")
    _describe("15min", m15)
    if not m15.empty:
        print(m15.tail(3).to_string())
    print()

    # Resample 15m → 1H / 4H (closed candles only).
    print("Resampled (from 15-min):")
    _describe("1H", resample_ohlcv(m15, "1H"))
    _describe("4H", resample_ohlcv(m15, "4H"))
    print()

    # DXY with fallback.
    dxy, source = get_dxy()
    print(f"DXY (source={source}):")
    _describe("dxy", dxy)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "QQQ")
