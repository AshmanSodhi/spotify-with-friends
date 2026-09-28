"""Tiny in-memory sliding-window rate limiter (PRD §18).

Conservative defaults; per-process. Good enough for a car full of friends.
"""
from __future__ import annotations

import time
from collections import deque

_BUCKETS: dict[str, deque[float]] = {}

LIMITS = {
    "search": (30, 60.0),   # 30 searches / minute per key
    "nowplaying": (30, 60.0),  # 30 queue-view reads / minute per key
    "queue": (12, 60.0),    # 12 queue adds / minute per key
    "join": (20, 60.0),     # 20 joins / minute per key
    "room_create": (10, 300.0),
}


def check(key: str, bucket: str) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds)."""
    limit, window = LIMITS.get(bucket, (30, 60.0))
    now = time.monotonic()
    dq = _BUCKETS.setdefault(f"{bucket}:{key}", deque())
    while dq and now - dq[0] > window:
        dq.popleft()
    if len(dq) >= limit:
        retry = int(window - (now - dq[0])) + 1
        return False, max(retry, 1)
    dq.append(now)
    return True, 0


def reset() -> None:
    _BUCKETS.clear()
