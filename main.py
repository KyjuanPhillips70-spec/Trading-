"""Entry point — loop all tickers, run scanner, send alerts.

Usage:
    python main.py                  # full scan
    python main.py --test-alert     # send a Telegram delivery-check message

Required environment variables (see §4):
    TRADIER_TOKEN
    TRADIER_BASE_URL   (default: https://sandbox.tradier.com/v1)
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

All secrets come from environment / GitHub Actions secrets.
No orders are ever placed; every result is an alert only.
"""

from __future__ import annotations

import logging
import sys

import config
from scanner import scan_ticker
from alert import send_alert, send_test_alert


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


def run() -> None:
    """Scan all configured tickers and send alerts for valid setups."""
    tickers = config.TICKERS_INDEX + config.TICKERS_SINGLE
    log.info("Starting scan: %s", tickers)

    setups = []
    for ticker in tickers:
        try:
            setup = scan_ticker(ticker)
            if setup is not None:
                setups.append(setup)
                log.info("Setup found: %s %s (confidence %d)", ticker, setup.direction, setup.confidence)
            else:
                log.debug("No setup: %s", ticker)
        except Exception as exc:
            log.error("Error scanning %s: %s", ticker, exc, exc_info=True)

    log.info("%d setup(s) found", len(setups))
    for setup in setups:
        send_alert(setup)


if __name__ == "__main__":
    if "--test-alert" in sys.argv:
        send_test_alert()
    else:
        run()
