"""Smoke-test the data layer (Stage 1).

Pulls one ticker's daily and 15-min bars and prints their shapes so you can
confirm the Tradier connection and resampling are working.

Usage:
    python scripts/smoke_data.py [TICKER]

Default ticker: QQQ
"""

from __future__ import annotations

import sys

# Stage 1 will implement these; this script is a stub for now.
# from data.tradier import get_history, get_timesales


def main(ticker: str = "QQQ") -> None:
    raise NotImplementedError(
        "smoke_data.py requires the Stage 1 data layer — not yet implemented."
    )


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "QQQ"
    main(ticker)
