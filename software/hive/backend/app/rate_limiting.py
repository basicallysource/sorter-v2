"""Rate limiting shared by the routes machines send data to, and the app's 429
response.

slowapi buckets requests by a key function. Keyed by client address, every
machine behind the same reverse proxy (or the same NAT) would share one bucket,
so one busy machine could starve the rest. The machine routes key by the
machine's bearer token instead.
"""

from __future__ import annotations

import hashlib
import math
import time

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


def machine_rate_limit_key(request: Request) -> str:
    """The bucket for a request to a machine route: one per machine token.

    Only a hash of the token is used, so the limiter's storage never holds a
    credential. Requests without a bearer token fall back to the client
    address. On the machine routes a request with a bad token never reaches the
    limiter at all: the route's machine authentication runs first and refuses it.
    """
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token:
            return "machine:" + hashlib.sha256(token.encode()).hexdigest()
    return get_remote_address(request)


# One limiter for every route a machine uploads to. Limits are still per route:
# slowapi scopes each limit to the route's path.
machine_limiter = Limiter(key_func=machine_rate_limit_key)


def _retry_after_seconds(request: Request, exc: RateLimitExceeded) -> int:
    window = max(1, int(exc.limit.limit.get_expiry()))
    current = getattr(request.state, "view_rate_limit", None)
    if current is not None:
        item, identifiers = current
        try:
            reset_at, remaining = machine_limiter.limiter.get_window_stats(item, *identifiers)
        except Exception:
            remaining = None
        # Only the machine limiter can say exactly when its window resets; a
        # limit from any other limiter is answered with its full window, which
        # is never too short.
        if remaining == 0:
            return max(1, min(window, math.ceil(reset_at - time.time())))
    return window


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """slowapi's own 429 body, plus a Retry-After header saying how many seconds
    to wait. slowapi only writes that header for a limiter created with headers
    enabled, and that setting requires every limited route to return a Response
    object, which these routes do not."""
    response = JSONResponse({"error": f"Rate limit exceeded: {exc.detail}"}, status_code=429)
    response.headers["Retry-After"] = str(_retry_after_seconds(request, exc))
    return response
