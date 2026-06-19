"""Simple on-disk JSON cache with TTL.

Storage format per entry:
    {"ts": <unix_timestamp_float>, "data": <any_json_serialisable>}

Used for:
  - ForexFactory weekly XML  (TTL 6 days)
  - Tradier option expirations (TTL 1 day)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


DEFAULT_CACHE_DIR: Path = Path(".cache")


def get(key: str, ttl_seconds: float, cache_dir: Path = DEFAULT_CACHE_DIR) -> Optional[Any]:
    """Return cached value for *key* if it exists and has not expired, else None."""
    raise NotImplementedError


def set(key: str, value: Any, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:  # noqa: A001
    """Write *value* to the cache under *key*, recording the current timestamp."""
    raise NotImplementedError


def invalidate(key: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:
    """Remove a cached entry (no-op if it does not exist)."""
    raise NotImplementedError
