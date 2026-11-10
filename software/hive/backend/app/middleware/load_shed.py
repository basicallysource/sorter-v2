"""Turning sorters' file uploads away while Hive is overloaded.

The fleet sends several files a second (piece images, channel crops, control
data, training samples). When the box stalls (a slow disk, a busy database),
those requests keep arriving while the ones before them have not finished.
Each one waiting holds its upload in memory, so a stall of a few minutes is
enough to push the web process past its memory ceiling and have it killed,
which takes every page and every machine down with it.

None of those uploads has to arrive. A sorter keeps what Hive has not
accepted and sends it again later, and losing some is better than losing
Hive. So while the process is overloaded, this middleware answers those routes
at once with a 429 and a Retry-After, without parsing the upload, opening a
database session or touching storage. A sorter treats a 429 as "the target is
busy" and backs its whole sync off for at least Retry-After seconds; versions
older than Retry-After support back off on any failed pass. Nothing else is
turned away: piece records, predictions, telemetry, heartbeats, profiles and
every page are answered as before.

Overloaded means any of:

- more of these uploads in flight at once than ``LOAD_SHED_MAX_UPLOADS_IN_FLIGHT``
  (the database or storage is not keeping up);
- more requests of any kind in flight than ``LOAD_SHED_MAX_REQUESTS_IN_FLIGHT``;
- the container's anonymous memory above ``LOAD_SHED_MEMORY_FRACTION`` of its
  limit (read from cgroup v2; skipped where there is no limit, as in
  development).

Once tripped, it keeps refusing uploads until ``LOAD_SHED_HOLD_S`` has passed
with nothing tripping, so a backlog does not rush back in the moment one
request finishes. The start and end of each episode are logged, with a
summary every minute in between, and both are sent to the operator alert
endpoint when one is configured (``services/admin_alert.py``).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from app.config import settings
from app.services import admin_alert

log = logging.getLogger(__name__)

# The routes a sorter uploads files to. Each one carries data Hive can do
# without, and a sorter resends what was not accepted.
SHEDDABLE_POST_PATHS = frozenset(
    {
        "/api/machine/sync/piece-image",
        "/api/machine/sync/channel-crop",
        "/api/machine/sync/channel-crop-batch",
        "/api/machine/sync/control-data-segment",
        "/api/machine/sync/sample",
        "/api/machine/upload",
    }
)

SUMMARY_INTERVAL_S = 60.0
# A refused upload's body is read and dropped so the connection stays usable
# (an unread body makes the proxy in front see a broken connection). Past this
# much, or this long, the answer goes anyway.
_DRAIN_MAX_BYTES = 64 * 1024 * 1024
_DRAIN_MAX_S = 30.0

_CGROUP = Path("/sys/fs/cgroup")
_MEMORY_CACHE_S = 1.0


def _read_cgroup_memory() -> tuple[int, int] | None:
    """(anonymous bytes, limit bytes) of this container, or None without a limit.

    Anonymous memory rather than memory.current: the page cache that file
    uploads leave behind counts in memory.current but is reclaimed before
    the OOM killer runs, so it says nothing about how close the process is.
    """
    try:
        raw_max = (_CGROUP / "memory.max").read_text().strip()
        if raw_max == "max":
            return None
        limit = int(raw_max)
        for line in (_CGROUP / "memory.stat").read_text().splitlines():
            key, _, value = line.partition(" ")
            if key == "anon":
                return int(value), limit
    except (OSError, ValueError):
        return None
    return None


class LoadShedder:
    """The overload state, shared by every request this process serves."""

    def __init__(
        self,
        *,
        max_uploads_in_flight: int,
        max_requests_in_flight: int,
        memory_fraction: float,
        hold_s: float,
        retry_after_s: int,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        read_memory: Callable[[], tuple[int, int] | None] = _read_cgroup_memory,
        alert: Callable[..., None] = admin_alert.send_in_background,
    ) -> None:
        self.max_uploads_in_flight = max_uploads_in_flight
        self.max_requests_in_flight = max_requests_in_flight
        self.memory_fraction = memory_fraction
        self.hold_s = hold_s
        self.retry_after_s = retry_after_s
        self._clock = clock
        self._wall_clock = wall_clock
        self._read_memory = read_memory
        self._alert = alert
        self._lock = threading.Lock()
        self.uploads_in_flight = 0
        self.requests_in_flight = 0
        self._memory: tuple[int, int] | None = None
        self._memory_read_at = float("-inf")
        # The current episode, if one is running.
        self.shedding = False
        self._episode_started_mono = 0.0
        self._episode_started_wall = 0.0
        self._episode_reason = ""
        self._last_trip = float("-inf")
        self._refused_total = 0
        self._refused_since_summary = 0
        self._last_summary = 0.0

    # Request accounting ----------------------------------------------------

    def request_started(self) -> None:
        with self._lock:
            self.requests_in_flight += 1

    def request_finished(self) -> None:
        with self._lock:
            self.requests_in_flight -= 1

    def upload_started(self) -> None:
        with self._lock:
            self.uploads_in_flight += 1

    def upload_finished(self) -> None:
        with self._lock:
            self.uploads_in_flight -= 1

    # The decision ----------------------------------------------------------

    def _memory_now(self, now: float) -> tuple[int, int] | None:
        if now - self._memory_read_at >= _MEMORY_CACHE_S:
            self._memory = self._read_memory()
            self._memory_read_at = now
        return self._memory

    def _trip_reason(self, now: float) -> str | None:
        """Why the process counts as overloaded right now, or None. Called
        with the lock held, for an upload that has not been counted yet."""
        if self.uploads_in_flight >= self.max_uploads_in_flight:
            return f"{self.uploads_in_flight} uploads already in flight (limit {self.max_uploads_in_flight})"
        if self.requests_in_flight > self.max_requests_in_flight:
            return f"{self.requests_in_flight} requests in flight (limit {self.max_requests_in_flight})"
        memory = self._memory_now(now)
        if memory is not None and self.memory_fraction > 0:
            used, limit = memory
            if used >= self.memory_fraction * limit:
                return f"memory at {used / limit:.0%} of its limit ({used // 2**20} of {limit // 2**20} MB)"
        return None

    def admit_upload(self) -> bool:
        """True to serve this upload, False to turn it away. An admitted upload
        is counted in flight; the caller calls upload_finished() after it."""
        now = self._clock()
        events: list[tuple[str, dict]] = []
        with self._lock:
            reason = self._trip_reason(now)
            if reason is not None:
                self._last_trip = now
                if not self.shedding:
                    self._start_episode(now, reason, events)
            elif self.shedding and now - self._last_trip >= self.hold_s:
                self._end_episode(now, events)
            if self.shedding:
                self._refused_total += 1
                self._refused_since_summary += 1
                if now - self._last_summary >= SUMMARY_INTERVAL_S:
                    self._summary(now)
                admitted = False
            else:
                self.uploads_in_flight += 1
                admitted = True
        for kind, fields in events:
            self._send_alert(kind, **fields)
        return admitted

    def tick(self) -> None:
        """End an episode whose hold has run out even if no upload arrives to
        notice (sorters back off, so the next one can be minutes away)."""
        now = self._clock()
        events: list[tuple[str, dict]] = []
        with self._lock:
            if self.shedding and self._trip_reason(now) is None and now - self._last_trip >= self.hold_s:
                self._end_episode(now, events)
        for kind, fields in events:
            self._send_alert(kind, **fields)

    # Episodes --------------------------------------------------------------

    def _start_episode(self, now: float, reason: str, events: list) -> None:
        self.shedding = True
        self._episode_started_mono = now
        self._episode_started_wall = self._wall_clock()
        self._episode_reason = reason
        self._refused_total = 0
        self._refused_since_summary = 0
        self._last_summary = now
        log.warning(
            "load shed: started refusing sorter uploads (429, Retry-After %ds): %s; %d requests in flight",
            self.retry_after_s,
            reason,
            self.requests_in_flight,
        )
        events.append(("start", {"reason": reason}))

    def _end_episode(self, now: float, events: list) -> None:
        self.shedding = False
        minutes = (now - self._episode_started_mono) / 60.0
        log.warning(
            "load shed: ended after %.1f min; %d sorter uploads refused (first reason: %s)",
            minutes,
            self._refused_total,
            self._episode_reason,
        )
        events.append(("end", {"minutes": minutes, "refused": self._refused_total}))

    def _summary(self, now: float) -> None:
        log.warning(
            "load shed: still refusing sorter uploads, %d in the last %.0f s (%d this episode); "
            "%d uploads and %d requests in flight",
            self._refused_since_summary,
            now - self._last_summary,
            self._refused_total,
            self.uploads_in_flight,
            self.requests_in_flight,
        )
        self._refused_since_summary = 0
        self._last_summary = now

    def _send_alert(self, kind: str, **fields) -> None:
        episode = f"hive-load-shed-{int(self._episode_started_wall)}"
        if kind == "start":
            self._alert(
                title="Hive is overloaded",
                message=(
                    "Hive is refusing sorters' image and crop uploads to stay up: "
                    f"{fields['reason']}. Sorters keep the data and retry later."
                ),
                request_id=f"{episode}-start",
                urgency="time_sensitive",
            )
        else:
            self._alert(
                title="Hive is taking uploads again",
                message=(
                    f"Hive stopped refusing sorter uploads after {fields['minutes']:.0f} min; "
                    f"{fields['refused']} uploads were turned away."
                ),
                request_id=f"{episode}-end",
                urgency="normal",
            )

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "shedding": self.shedding,
                "reason": self._episode_reason if self.shedding else None,
                "refused_this_episode": self._refused_total if self.shedding else 0,
                "uploads_in_flight": self.uploads_in_flight,
                "requests_in_flight": self.requests_in_flight,
            }


load_shedder = LoadShedder(
    max_uploads_in_flight=settings.LOAD_SHED_MAX_UPLOADS_IN_FLIGHT,
    max_requests_in_flight=settings.LOAD_SHED_MAX_REQUESTS_IN_FLIGHT,
    memory_fraction=settings.LOAD_SHED_MEMORY_FRACTION,
    hold_s=settings.LOAD_SHED_HOLD_S,
    retry_after_s=settings.LOAD_SHED_RETRY_AFTER_S,
)


async def _drain(receive) -> None:
    started = time.monotonic()
    seen = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return  # the client went away
        seen += len(message.get("body", b""))
        if not message.get("more_body", False):
            return
        if seen >= _DRAIN_MAX_BYTES or time.monotonic() - started >= _DRAIN_MAX_S:
            return


class LoadShedMiddleware:
    """Pure ASGI, so a refused upload costs no task, no form parsing and no
    database session."""

    def __init__(self, app, shedder: LoadShedder | None = None) -> None:
        self.app = app
        self.shedder = shedder if shedder is not None else load_shedder

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        shedder = self.shedder
        sheddable = scope.get("method") == "POST" and scope.get("path") in SHEDDABLE_POST_PATHS
        if not sheddable:
            shedder.tick()
            shedder.request_started()
            try:
                await self.app(scope, receive, send)
            finally:
                shedder.request_finished()
            return
        if not shedder.admit_upload():
            await _drain(receive)
            await self._refuse(send)
            return
        shedder.request_started()
        try:
            await self.app(scope, receive, send)
        finally:
            shedder.request_finished()
            shedder.upload_finished()

    async def _refuse(self, send) -> None:
        body = json.dumps(
            {
                "error": "Hive is under heavy load and is not recording this upload. Send it again later.",
                "code": "HIVE_OVERLOADED",
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"retry-after", str(self.shedder.retry_after_s).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
