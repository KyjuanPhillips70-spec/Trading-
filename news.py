"""ForexFactory news feed — parse and blackout filter.

Downloads https://nfs.faireconomy.media/ff_calendar_thisweek.xml (fallback .json).
Cached once per week (TTL 6 days) via data/cache.py to avoid throttling.

Blackout rule:
  Suppress new-entry alerts within NEWS_BEFORE_H hours before through
  NEWS_AFTER_H hours after any High-impact USD event.
  When inside the window, scan_ticker returns news_block=True.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

FF_XML_URL  = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
FF_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_KEY   = "ff_calendar_thisweek"
CACHE_TTL   = 6 * 24 * 3600   # 6 days in seconds


@dataclass
class NewsEvent:
    title: str
    country: str
    impact: str
    dt: datetime


def fetch_calendar(force: bool = False) -> list[NewsEvent]:
    """Return this week's ForexFactory events, reading from cache when fresh.

    Tries XML first; falls back to JSON.
    Filters to country == "USD" and impact == "High" before returning.
    """
    raise NotImplementedError


def is_news_blackout(
    now: Optional[datetime] = None,
    before_h: int = 24,
    after_h: int = 2,
) -> tuple[bool, Optional[NewsEvent]]:
    """Return (blocked, event) where blocked is True if *now* falls in a blackout window.

    Args:
        now:      Current UTC datetime (defaults to datetime.utcnow()).
        before_h: Hours before the event to block.
        after_h:  Hours after the event to unblock.

    Returns:
        (True, triggering_event) if blocked, else (False, None).
    """
    raise NotImplementedError


def next_high_impact_event(now: Optional[datetime] = None) -> Optional[NewsEvent]:
    """Return the next upcoming High-impact USD event after *now*."""
    raise NotImplementedError
