"""How long each kind of request takes, kept in memory by the process that
serves them.

For every HTTP request the middleware records, against its route template
(``GET /api/samples/{sample_id}``, never the raw path, so there are only as
many keys as the app has routes): how long it took, whether it ended in a
5xx, and how long it spent in database queries. The admin Server page shows
the last hour of it (``RequestStats.snapshot``).

Memory stays the same however many requests arrive: one slot per minute for
the last ``WINDOW_MINUTES``, and in each slot one row per route seen that
minute, holding a count, a few sums and a latency histogram of ``_BINS``
counters. Percentiles are read off the merged histogram, whose bins are 20%
wide, so a percentile is within about 10% of the exact one. A method outside
the usual set counts as ``OTHER`` and a request no route matched as
``(no route)``, so a client making up paths or methods cannot add keys.

A request that takes ``SLOW_REQUEST_S`` or longer writes one warning line:
the route, the status, the total time and the time in the database.

Database time comes from SQLAlchemy's cursor events. The middleware puts a
small timer in a context variable, and every query run while the request is
served (on the event loop, or in the threadpool, which copies the context)
adds its time to it. A query from a background thread finds no timer and
costs one context-variable read.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from array import array
from contextvars import ContextVar
from datetime import datetime, timezone
from itertools import count
from typing import Any, Callable

from sqlalchemy import event
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

SLOW_REQUEST_S = 2.0
WINDOW_MINUTES = 60
NO_ROUTE = "(no route)"
_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
# The requests still running that a snapshot lists, oldest first.
_IN_FLIGHT_LISTED = 5
_PATH_KEPT = 200

# The latency histogram, in milliseconds: bin 0 holds what took under 1 ms,
# bin i what took from 1.2^(i-1) up to 1.2^i, and the last bin everything
# from about three minutes up.
_GROWTH = 1.2
_LOG_GROWTH = math.log(_GROWTH)
_BINS = 68


def _bin(ms: float) -> int:
    if ms < 1.0:
        return 0
    return min(_BINS - 1, int(math.log(ms) / _LOG_GROWTH) + 1)


def _bin_edges(index: int) -> tuple[float, float]:
    if index == 0:
        return 0.0, 1.0
    return _GROWTH ** (index - 1), _GROWTH**index


def _percentile(hist, total: int, q: float, max_ms: float) -> float:
    """The q-th percentile of ``total`` durations counted in ``hist``: the
    bin holding that rank, interpolated across the bin, never above the
    largest duration seen."""
    if total <= 0:
        return 0.0
    rank = max(1, math.ceil(q * total))
    seen = 0
    for index, n in enumerate(hist):
        if not n:
            continue
        if seen + n >= rank:
            low, high = _bin_edges(index)
            if index == _BINS - 1 or high > max_ms:
                high = max(max_ms, low)
            value = low + (high - low) * (rank - seen) / n
            return round(min(value, max_ms), 1)
        seen += n
    return round(max_ms, 1)


class _RouteMinute:
    """One route's requests in one minute."""

    __slots__ = ("count", "errors", "slow", "total_ms", "db_ms", "max_ms", "hist")

    def __init__(self) -> None:
        self.count = 0
        self.errors = 0
        self.slow = 0
        self.total_ms = 0.0
        self.db_ms = 0.0
        self.max_ms = 0.0
        self.hist = array("I", [0]) * _BINS


class _Minute:
    """Every route's requests in one minute, and the wall clock and the
    process's CPU time when the minute's first request ended, from which a
    snapshot tells how busy the process has been."""

    __slots__ = ("minute", "routes", "wall", "cpu")

    def __init__(self, minute: int, wall: float, cpu: float) -> None:
        self.minute = minute
        self.routes: dict[tuple[str, str], _RouteMinute] = {}
        self.wall = wall
        self.cpu = cpu


class RequestStats:
    """The rolling window. ``record`` adds a finished request, ``begin`` and
    ``end`` bracket one so a snapshot can list what is still running, and
    ``snapshot`` reads it all. Thread-safe: requests end on the event loop
    while a snapshot is usually taken from the threadpool."""

    def __init__(
        self,
        window_minutes: int = WINDOW_MINUTES,
        *,
        slow_s: float = SLOW_REQUEST_S,
        clock: Callable[[], float] = time.time,
        cpu_clock: Callable[[], float] = time.process_time,
    ) -> None:
        self.window_minutes = window_minutes
        self.slow_ms = slow_s * 1000.0
        self._clock = clock
        self._cpu_clock = cpu_clock
        self._lock = threading.Lock()
        self._slots: list[_Minute | None] = [None] * window_minutes
        self._in_flight: dict[int, tuple[str, str, float]] = {}
        self._ids = count()
        self.started_at = clock()

    def begin(self, method: str, path: str) -> int:
        token = next(self._ids)
        with self._lock:
            self._in_flight[token] = (method, path[:_PATH_KEPT], time.perf_counter())
        return token

    def end(self, token: int, method: str, route: str, status: int, total_ms: float, db_ms: float) -> None:
        self.record(method, route, status, total_ms, db_ms, in_flight=token)

    def record(
        self,
        method: str,
        route: str,
        status: int,
        total_ms: float,
        db_ms: float = 0.0,
        *,
        in_flight: int | None = None,
    ) -> None:
        now = self._clock()
        minute = int(now // 60)
        index = minute % self.window_minutes
        with self._lock:
            if in_flight is not None:
                self._in_flight.pop(in_flight, None)
            slot = self._slots[index]
            if slot is None or slot.minute != minute:
                slot = self._slots[index] = _Minute(minute, now, self._cpu_clock())
            row = slot.routes.get((method, route))
            if row is None:
                row = slot.routes[(method, route)] = _RouteMinute()
            row.count += 1
            if status >= 500:
                row.errors += 1
            if total_ms >= self.slow_ms:
                row.slow += 1
            row.total_ms += total_ms
            row.db_ms += db_ms
            if total_ms > row.max_ms:
                row.max_ms = total_ms
            row.hist[_bin(total_ms)] += 1

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        oldest_kept = int(now // 60) - self.window_minutes + 1
        with self._lock:
            slots = [s for s in self._slots if s is not None and s.minute >= oldest_kept]
            # Copied under the lock (each histogram is one memcpy), merged after it.
            rows = [
                (key, r.count, r.errors, r.slow, r.total_ms, r.db_ms, r.max_ms, array("I", r.hist))
                for s in slots
                for key, r in s.routes.items()
            ]
            running = sorted(self._in_flight.values(), key=lambda f: f[2])
        perf_now = time.perf_counter()
        first = min(slots, key=lambda s: s.minute) if slots else None
        window_start = max(first.minute * 60, self.started_at) if first else now
        window_s = max(1.0, now - window_start)

        merged: dict[tuple[str, str], list] = {}
        for key, n, errors, slow, total_ms, db_ms, max_ms, hist in rows:
            m = merged.get(key)
            if m is None:
                merged[key] = [n, errors, slow, total_ms, db_ms, max_ms, [hist]]
            else:
                m[0] += n
                m[1] += errors
                m[2] += slow
                m[3] += total_ms
                m[4] += db_ms
                m[5] = max(m[5], max_ms)
                m[6].append(hist)

        routes = []
        all_hists = []
        for (method, route), (n, errors, slow, total_ms, db_ms, max_ms, hists) in merged.items():
            hist = hists[0] if len(hists) == 1 else [sum(column) for column in zip(*hists)]
            all_hists.append(hist)
            routes.append({"method": method, "route": route} | _summary(n, errors, slow, total_ms, db_ms, max_ms, hist, window_s))
        routes.sort(key=lambda r: r["total_s"], reverse=True)

        n = sum(r["count"] for r in routes)
        totals = _summary(
            n,
            sum(r["errors"] for r in routes),
            sum(r["slow"] for r in routes),
            sum(m[3] for m in merged.values()),
            sum(m[4] for m in merged.values()),
            max((m[5] for m in merged.values()), default=0.0),
            [sum(column) for column in zip(*all_hists)] if all_hists else [],
            window_s,
        )
        return {
            "window_s": round(window_s),
            "since": datetime.fromtimestamp(window_start, timezone.utc).isoformat(),
            "slow_s": self.slow_ms / 1000.0,
            "totals": totals,
            "routes": routes,
            "in_flight": {
                "count": len(running),
                "oldest": [
                    {"method": method, "path": path, "running_s": round(perf_now - started, 1)}
                    for method, path, started in running[:_IN_FLIGHT_LISTED]
                ],
            },
            "cpu": self._cpu_use(slots, now),
        }

    def _cpu_use(self, slots: list[_Minute], now: float) -> dict[str, Any]:
        """How many cores this process has kept busy (all its threads, so
        background work in it too): since the window's first minute, and
        since the first minute of the last five."""
        if not slots:
            return {"window_cores": None, "recent_cores": None, "recent_s": None}
        cpu_now = self._cpu_clock()
        ordered = sorted(slots, key=lambda s: s.minute)
        first = ordered[0]
        recent = next((s for s in ordered if s.minute >= int(now // 60) - 4), ordered[-1])

        def cores(since: _Minute) -> float | None:
            elapsed = now - since.wall
            return round((cpu_now - since.cpu) / elapsed, 3) if elapsed >= 1.0 else None

        return {
            "window_cores": cores(first),
            "recent_cores": cores(recent),
            "recent_s": round(now - recent.wall),
        }


def _summary(n, errors, slow, total_ms, db_ms, max_ms, hist, window_s: float) -> dict[str, Any]:
    return {
        "count": n,
        "per_minute": round(n * 60.0 / window_s, 2),
        "errors": errors,
        "slow": slow,
        "p50_ms": _percentile(hist, n, 0.50, max_ms),
        "p90_ms": _percentile(hist, n, 0.90, max_ms),
        "p99_ms": _percentile(hist, n, 0.99, max_ms),
        "max_ms": round(max_ms, 1),
        "mean_ms": round(total_ms / n, 1) if n else 0.0,
        "total_s": round(total_ms / 1000.0, 2),
        "db_s": round(db_ms / 1000.0, 2),
    }


# The process's window, read by the admin Server page.
request_stats = RequestStats()


class _RequestTimer:
    __slots__ = ("db_s", "queries")

    def __init__(self) -> None:
        self.db_s = 0.0
        self.queries = 0


_current: ContextVar[_RequestTimer | None] = ContextVar("request_timer", default=None)


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    if context is not None and _current.get() is not None:
        try:
            context._request_timing_started = time.perf_counter()
        except AttributeError:  # a context that takes no attributes goes untimed
            pass


def _query_ended(context) -> None:
    started = getattr(context, "_request_timing_started", None) if context is not None else None
    if started is None:
        return
    context._request_timing_started = None  # counted once, even if an error follows
    timer = _current.get()
    if timer is not None:
        timer.db_s += time.perf_counter() - started
        timer.queries += 1


def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    _query_ended(context)


def _handle_error(exception_context) -> None:
    # A query that fails (a statement timeout, say) still spent its time.
    _query_ended(exception_context.execution_context)


_installed = False
_install_lock = threading.Lock()


def install_query_timing() -> None:
    """Listen to every engine's cursor events, once per process."""
    global _installed
    with _install_lock:
        if _installed:
            return
        event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
        event.listen(Engine, "after_cursor_execute", _after_cursor_execute)
        event.listen(Engine, "handle_error", _handle_error)
        _installed = True


class RequestTimingMiddleware:
    """Times every HTTP request into ``request_stats``.

    Pure ASGI rather than Starlette's BaseHTTPMiddleware, which runs the
    endpoint in a task of its own and adds that cost to every request.
    Registered after the other middleware, so it is the outermost and its
    time is the whole of what the app spent on the request.
    """

    def __init__(self, app, stats: RequestStats | None = None) -> None:
        self.app = app
        self.stats = stats if stats is not None else request_stats
        install_query_timing()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method") or "OTHER"
        if method not in _METHODS:
            method = "OTHER"
        timer = _RequestTimer()
        reset = _current.set(timer)
        token = self.stats.begin(method, scope.get("path") or "")
        # A request that raises before it answers is answered with a 500 by
        # the error middleware outside this one.
        status = 500
        started = time.perf_counter()

        async def send_noting_status(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_noting_status)
        finally:
            total_ms = (time.perf_counter() - started) * 1000.0
            _current.reset(reset)
            try:
                self._note(scope, token, method, status, total_ms, timer)
            except Exception:
                # Measuring must never be why a request fails.
                log.exception("request timing: could not record a request")

    def _note(self, scope, token: int, method: str, status: int, total_ms: float, timer: _RequestTimer) -> None:
        # FastAPI leaves the route it matched in the scope.
        route = getattr(scope.get("route"), "path", None) or NO_ROUTE
        db_ms = timer.db_s * 1000.0
        self.stats.end(token, method, route, status, total_ms, db_ms)
        if total_ms >= self.stats.slow_ms:
            log.warning(
                "slow request: %s %s answered %d in %.0f ms, %.0f ms of it in %d database queries",
                method,
                route,
                status,
                total_ms,
                db_ms,
                timer.queries,
            )
