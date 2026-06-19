"""Telegram alert sender and message formatter.

Formats the §15 alert template and sends via Telegram Bot API sendMessage.
Secrets read from environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

_TEST_ALERT_TEXT = """\
🔔 TEST ALERT — ICT Swing-Options Alert System

This is a delivery check, not a real setup.

If you can read this your Telegram integration is working correctly.

Alert only — not financial advice. Verify before trading."""


@dataclass
class Contract:
    """Option contract selected by contracts.py."""
    symbol: str
    option_type: str
    strike: float
    expiry: str
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

    @property
    def est_profit(self) -> float:
        return round(self.mid * abs(self.delta) * 100, 2)

    @property
    def est_loss(self) -> float:
        return round(self.mid * 100, 2)


@dataclass
class Setup:
    """Fully resolved trade setup — output of scanner.scan_ticker."""
    ticker: str
    direction: str                  # "LONG" or "SHORT"
    confidence: int                 # 0–100
    daily_bias: str
    four_h_bias: str
    one_h_bias: str
    ema_stack_ok: bool
    dxy_agrees: bool
    smt_signal: Optional[str]
    sweep_side: str                 # "SSL" or "BSL"
    sweep_level: float
    structure_event: str            # "BOS" or "MSS"
    entry_type: str                 # "OTE" | "OB" | "FVG"
    entry: float
    stop: float
    target: float
    rr: float
    contract: Contract
    news_clear: bool
    next_news_event: Optional[object]


def _escape(text: str) -> str:
    """Escape MarkdownV2 reserved characters outside of code spans."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def format_alert(setup: Setup) -> str:
    """Return the MarkdownV2-formatted Telegram alert string for *setup*.

    Follows the §15 template exactly, including settlement note and disclaimer.
    """
    c = setup.contract

    risk = abs(setup.entry - setup.stop)
    dxy_str = "agrees ✅" if setup.dxy_agrees else "contradicts ⚠️"
    smt_str = setup.smt_signal if setup.smt_signal else "none"
    news_str = (
        "clear ✅"
        if setup.news_clear
        else f"next: {setup.next_news_event}"
    )

    est_profit = c.mid * abs(c.delta) * 100
    est_loss = c.mid * 100

    def e(v: str) -> str:
        return _escape(str(v))

    lines = [
        f"🔔 *ICT SWING SETUP — {e(setup.ticker)} {e(setup.direction)}*  "
        f"\\(confidence {setup.confidence}/100\\)",
        "",
        f"*Bias:* Daily {e(setup.daily_bias)} \\(EMA stack {'✅' if setup.ema_stack_ok else '❌'}\\); "
        f"4H {e(setup.four_h_bias)}; 1H {e(setup.one_h_bias)}",
        f"*DXY:* {e(dxy_str)}  |  *SMT:* {e(smt_str)}",
        f"*Trigger:* swept {e(setup.sweep_side)} @ {e(f'{setup.sweep_level:.2f}')} "
        f"→ {e(setup.structure_event)} → entry in {e(setup.entry_type)}",
        "",
        f"*Entry:*  {e(f'{setup.entry:.2f}')}",
        f"*Stop:*   {e(f'{setup.stop:.2f}')}   \\({e(f'{risk:.2f}')} away\\)",
        f"*Target:* {e(f'{setup.target:.2f}')}   \\(R:R {e(f'{setup.rr:.1f}')} : 1\\)",
        "",
        f"*Contract:* `{e(c.symbol)}`",
        f"  {e(c.option_type.upper())} {e(str(c.strike))} exp {e(c.expiry)} \\({c.dte} DTE\\)",
        f"  Δ {e(f'{c.delta:.2f}')}  "
        f"Θ {e(f'{c.theta:.4f}')}/day  "
        f"Γ {e(f'{c.gamma:.4f}')}  "
        f"V {e(f'{c.vega:.4f}')}  "
        f"IV {e(f'{c.iv:.1%}')}",
        f"  Est\\. debit ~{e(f'{c.mid:.2f}')}  "
        f"| est\\. P/L at target ~\\+{e(f'{est_profit:.0f}')}  "
        f"at stop ~\\-{e(f'{est_loss:.0f}')}",
        f"  _{e(c.settlement_note)}_",
        "",
        f"*News:* {e(news_str)}",
        "⚠️ _Alert only — not financial advice\\. Verify before trading\\._",
    ]

    return "\n".join(lines)


def send_alert(setup: Setup, dry_run: bool = False) -> None:
    """Format and send the alert to Telegram.

    Args:
        setup:   Resolved trade setup.
        dry_run: If True, print to stdout instead of sending.
    """
    text = format_alert(setup)
    if dry_run:
        print(text)
        return
    _post(text)


def send_test_alert() -> None:
    """Send a simple delivery-check message to Telegram.

    Verifies TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are valid without
    requiring a real trade setup.
    """
    _post(_TEST_ALERT_TEXT, markdown=False)
    print("Test alert sent successfully.")


def _post(text: str, markdown: bool = True) -> None:
    """POST a message to the configured Telegram chat.

    When *markdown* is True the message is parsed as MarkdownV2; otherwise it
    is sent as plain text (used for the delivery-check alert).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in the environment."
        )
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if markdown:
        payload["parse_mode"] = "MarkdownV2"
    resp = requests.post(url, json=payload, timeout=15)
    if not resp.ok:
        raise RuntimeError(
            f"Telegram sendMessage failed {resp.status_code}: {resp.text}"
        )
    log.info("Telegram message sent (chat_id=%s)", chat_id)
