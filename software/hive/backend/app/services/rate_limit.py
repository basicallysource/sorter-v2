"""Per-user, role-aware request rate limiting.

A small self-contained token-bucket limiter used to cap how fast a windowed user
can pull piece-bbox data — the window bounds *how much* of the set they can see,
this bounds *how fast* they can drain it. Admins are exempt; reviewers get a
generous cap (real labeling is bursty but bounded); members are tighter.

In-memory and per-process. The dev/prod backend runs a single uvicorn worker so
this is global there; if the deployment ever fans out to multiple workers the
cap becomes per-worker (still a meaningful backstop). Move to Redis if a hard
cross-process guarantee is ever needed.
"""

from __future__ import annotations

import threading
import time

from fastapi import Depends, HTTPException

from app.deps import get_current_user
from app.models.user import User

WINDOW_S = 60.0

# requests per WINDOW_S, per user, per bucket. None => unlimited for that role.
LIMITS: dict[str, dict[str, int | None]] = {
    # Image byte pulls — the primary exfil vector.
    "labeling_image": {"member": 120, "reviewer": 600, "admin": None},
    # Metadata list/detail calls that enumerate the set.
    "labeling_list": {"member": 30, "reviewer": 180, "admin": None},
}


class _Bucket:
    __slots__ = ("tokens", "updated")

    def __init__(self, tokens: float, updated: float) -> None:
        self.tokens = tokens
        self.updated = updated


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: float) -> tuple[bool, int]:
        """Consume one token. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        rate = limit / window_s
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(float(limit), now)
                self._buckets[key] = bucket
            else:
                bucket.tokens = min(float(limit), bucket.tokens + (now - bucket.updated) * rate)
                bucket.updated = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0
            retry_after = int((1.0 - bucket.tokens) / rate) + 1
            return False, retry_after


_limiter = RateLimiter()


def rate_limit(bucket: str):
    """FastAPI dependency factory. Caps the caller on ``bucket`` by their role."""

    def dependency(current_user: User = Depends(get_current_user)) -> None:
        role_limits = LIMITS.get(bucket, {})
        # Unknown roles fall back to the tightest configured limit.
        limit = role_limits.get(current_user.role, role_limits.get("member"))
        if limit is None:
            return
        allowed, retry_after = _limiter.check(f"{bucket}:{current_user.id}", limit, WINDOW_S)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Slow down.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
