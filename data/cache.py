"""Simple on-disk JSON cache with TTL.

Storage format per entry:
    {"ts": <unix_timestamp_float>, "data": <any_json_serialisable>}

Used for:
  - ForexFactory weekly XML  (TTL 6 days)
  - Tradier option expirations (TTL 1 day)
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional


DEFAULT_CACHE_DIR: Path = Path(".cache")

_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]+")


def _path_for(key: str, cache_dir: Path) -> Path:
    """Map a cache key to a safe on-disk JSON path."""
    safe = _SAFE_KEY.sub("_", key)
    return cache_dir / f"{safe}.json"


def get(key: str, ttl_seconds: float, cache_dir: Path = DEFAULT_CACHE_DIR) -> Optional[Any]:
    """Return cached value for *key* if it exists and has not expired, else None."""
    path = _path_for(key, cache_dir)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            entry = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    ts = entry.get("ts")
    if ts is None or (time.time() - float(ts)) > ttl_seconds:
        return None
    return entry.get("data")


def set(key: str, value: Any, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:  # noqa: A001
    """Write *value* to the cache under *key*, recording the current timestamp."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _path_for(key, cache_dir)
    entry = {"ts": time.time(), "data": value}
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(entry, fh)
    tmp.replace(path)  # atomic on POSIX


def invalidate(key: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:
    """Remove a cached entry (no-op if it does not exist)."""
    _path_for(key, cache_dir).unlink(missing_ok=True)
