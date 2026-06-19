"""Telegram alert sender and message formatter.

Formats the §15 alert template and sends via Telegram Bot API sendMessage.
Secrets read from environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

TELEGRAM_API = "https://api.telegram.org"


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
    contract: object                # contracts.Contract
    news_clear: bool
    next_news_event: Optional[object]


def format_alert(setup: Setup) -> str:
    """Return the Markdown-formatted Telegram alert string for *setup*.

    Follows the §15 template exactly, including settlement note and disclaimer.
    """
    raise NotImplementedError


def send_alert(setup: Setup, dry_run: bool = False) -> None:
    """Format and send the alert to Telegram.

    Args:
        setup:   Resolved trade setup.
        dry_run: If True, print to stdout instead of sending to Telegram.
    """
    raise NotImplementedError


def _post(text: str) -> None:
    """POST a Markdown message to the configured Telegram chat."""
    raise NotImplementedError
