"""ForexFactory news feed — parse and blackout filter.

Downloads https://nfs.faireconomy.media/ff_calendar_thisweek.xml (fallback .json).
Cached once per week (TTL 6 days) via data/cache.py to avoid throttling.

Blackout rule:
  Suppress new-entry alerts within NEWS_BEFORE_H hours before through
  NEWS_AFTER_H hours after any High-impact USD event.
  When inside the window, scan_ticker returns news_block=True.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from data import cache

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


# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type(requests.RequestException),
    reraise=True,
)
def _download(url: str) -> str:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "ict-alert/1.0"})
    resp.raise_for_status()
    return resp.text


def _parse_dt(value: str) -> Optional[datetime]:
    """Parse a ForexFactory timestamp into a timezone-aware UTC datetime."""
    if not value:
        return None
    value = value.strip()
    # JSON feed: ISO 8601 with offset, e.g. "2024-01-05T08:30:00-05:00".
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    # XML feed: separate date "01-05-2024" and time "8:30am" — handled by caller.
    return None


def _parse_xml(text: str) -> list[dict]:
    """Parse the ForexFactory weekly XML feed into raw event dicts."""
    out: list[dict] = []
    root = ET.fromstring(text)
    for ev in root.findall("event"):
        def _text(tag: str) -> str:
            node = ev.find(tag)
            return node.text.strip() if node is not None and node.text else ""

        date_s = _text("date")   # e.g. "01-05-2024"
        time_s = _text("time")   # e.g. "8:30am" or "All Day" / "Tentative"
        dt: Optional[datetime] = None
        if date_s and time_s and time_s.lower() not in ("all day", "tentative", ""):
            for fmt in ("%m-%d-%Y %I:%M%p", "%m-%d-%Y %I%p"):
                try:
                    naive = datetime.strptime(f"{date_s} {time_s}", fmt)
                    # FF times are US Eastern; store as UTC (approx via fixed -5).
                    dt = naive.replace(tzinfo=timezone(timedelta(hours=-5))).astimezone(timezone.utc)
                    break
                except ValueError:
                    continue
        out.append({
            "title": _text("title"),
            "country": _text("country"),
            "impact": _text("impact"),
            "dt": dt.isoformat() if dt else "",
        })
    return out


def _parse_json(text: str) -> list[dict]:
    """Parse the ForexFactory weekly JSON feed into raw event dicts."""
    import json
    rows = json.loads(text)
    out: list[dict] = []
    for r in rows:
        dt = _parse_dt(r.get("date", ""))
        out.append({
            "title": r.get("title", ""),
            "country": r.get("country", ""),
            "impact": r.get("impact", ""),
            "dt": dt.isoformat() if dt else "",
        })
    return out


def _to_events(raw: list[dict]) -> list[NewsEvent]:
    """Convert cached raw dicts to high-impact USD NewsEvent objects, sorted by time."""
    events: list[NewsEvent] = []
    for r in raw:
        if r.get("country", "").upper() != "USD":
            continue
        if r.get("impact", "").lower() != "high":
            continue
        if not r.get("dt"):
            continue
        try:
            dt = datetime.fromisoformat(r["dt"])
        except ValueError:
            continue
        events.append(NewsEvent(
            title=r["title"], country=r["country"], impact=r["impact"], dt=dt,
        ))
    events.sort(key=lambda e: e.dt)
    return events


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_calendar(force: bool = False) -> list[NewsEvent]:
    """Return this week's High-impact USD events, reading from cache when fresh.

    Tries XML first; falls back to JSON. Caches the raw parsed events for 6 days
    (ForexFactory throttles downloads to ≈2 per 5 min).
    """
    raw: Optional[list[dict]] = None
    if not force:
        raw = cache.get(CACHE_KEY, CACHE_TTL)

    if raw is None:
        try:
            raw = _parse_xml(_download(FF_XML_URL))
        except Exception:
            try:
                raw = _parse_json(_download(FF_JSON_URL))
            except Exception:
                return []
        cache.set(CACHE_KEY, raw)

    return _to_events(raw)


def is_news_blackout(
    now: Optional[datetime] = None,
    before_h: int = 24,
    after_h: int = 2,
) -> tuple[bool, Optional[NewsEvent]]:
    """Return (blocked, event) where blocked is True if *now* falls in a blackout window.

    Args:
        now:      Current UTC datetime (defaults to now, UTC).
        before_h: Hours before the event to block.
        after_h:  Hours after the event to unblock.

    Returns:
        (True, triggering_event) if blocked, else (False, None).
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    for ev in fetch_calendar():
        start = ev.dt - timedelta(hours=before_h)
        end = ev.dt + timedelta(hours=after_h)
        if start <= now <= end:
            return True, ev
    return False, None


def next_high_impact_event(now: Optional[datetime] = None) -> Optional[NewsEvent]:
    """Return the next upcoming High-impact USD event after *now*."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    for ev in fetch_calendar():
        if ev.dt >= now:
            return ev
    return None
