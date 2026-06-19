"""Entry point — loop all tickers, run scanner, send alerts.

Usage:
    python main.py                        # full scan
    python main.py --test-alert           # Telegram delivery-check message
    python main.py --force-alert TICKER   # live scan on one ticker; sends real
                                          # alert if setup found, placeholder if not

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
from datetime import date, datetime, timezone

import config
from scanner import scan_ticker, load_ticker_data, evaluate
from alert import send_alert, send_test_alert, Setup
from contracts import Contract


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


def _placeholder_setup(ticker: str, price: float) -> Setup:
    """Return a placeholder Setup for *ticker* using *price* as the current price."""
    stop = round(price * 0.985, 2)    # 1.5% below
    target = round(price * 1.015, 2)  # 1.5% above
    strike = round(price / 5) * 5     # nearest $5 strike
    contract = Contract(
        symbol=f"{ticker}{date.today().strftime('%y%m%d')}C{int(strike):08d}000",
        option_type="call",
        strike=float(strike),
        expiry=str(date.today()),
        dte=10,
        bid=round(price * 0.022, 2),
        ask=round(price * 0.024, 2),
        mid=round(price * 0.023, 2),
        delta=0.55,
        theta=-0.05,
        gamma=0.01,
        vega=0.10,
        iv=0.45,
        oi=1000,
        volume=300,
        settlement_note="equity — PLACEHOLDER alert, no real ICT setup found",
    )
    return Setup(
        ticker=ticker,
        direction="LONG",
        confidence=0,
        daily_bias="none",
        four_h_bias="none",
        one_h_bias="none",
        ema_stack_ok=False,
        dxy_agrees=False,
        smt_signal=None,
        sweep_side="SSL",
        sweep_level=round(price * 0.99, 2),
        structure_event="BOS",
        entry_type="OTE",
        entry=price,
        stop=stop,
        target=target,
        rr=1.0,
        contract=contract,
        news_clear=True,
        next_news_event=None,
    )


def force_alert(ticker: str) -> None:
    """Run a live scan on *ticker* and send the result to Telegram.

    Sends the real setup if one is found; otherwise sends a clearly labelled
    placeholder built from the real current price so you can verify formatting.
    """
    ticker = ticker.upper()
    log.info("Force-alert: loading live data for %s", ticker)
    data = None
    try:
        data = load_ticker_data(ticker)
        setup = evaluate(ticker, data,
                         now=datetime.now(tz=timezone.utc),
                         today=date.today())
    except Exception as exc:
        log.error("Live scan failed for %s: %s", ticker, exc, exc_info=True)
        setup = None

    if setup is not None:
        log.info("Real setup found for %s — sending live alert", ticker)
        send_alert(setup)
        print(f"Real setup alert sent for {ticker}.")
    else:
        # Use the real current close price for the placeholder.
        price = float(data.daily["close"].iloc[-1]) if data is not None else 100.0
        log.info("No real setup for %s (last close %.2f) — sending placeholder", ticker, price)
        send_alert(_placeholder_setup(ticker, price))
        print(f"Placeholder alert sent for {ticker} at live price {price:.2f} (no real setup found).")


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
    elif "--force-alert" in sys.argv:
        idx = sys.argv.index("--force-alert")
        if idx + 1 >= len(sys.argv):
            print("Usage: python main.py --force-alert TICKER")
            sys.exit(1)
        force_alert(sys.argv[idx + 1])
    else:
        run()
