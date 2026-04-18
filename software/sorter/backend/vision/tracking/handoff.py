"""Cross-camera piece identity handoff.

When a track dies inside a camera's ``exit_zone`` it is queued as a
``PendingHandoff``. When a new track is born inside the downstream camera's
``entry_zone`` within ``HANDOFF_WINDOW_S`` it inherits the pending
``global_id`` (FIFO match against all pendings from that upstream camera).

Zones are polygons in frame-pixel coordinates of the source camera. Callers
provide both via :meth:`PieceHandoffManager.set_zones`. The manager is
intentionally camera-pair-agnostic — the ``handoff_chain`` mapping says which
camera pours into which.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Iterable

from .base import PendingHandoff


def _point_in_polygon(point: tuple[float, float], polygon: Iterable[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test. Tolerant of open polygons."""
    px, py = point
    poly = list(polygon)
    if len(poly) < 3:
        return False
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        intersect = ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-9) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


class PieceHandoffManager:
    """Single source of global piece IDs + cross-camera handoff queue."""

    DEFAULT_HANDOFF_WINDOW_S: float = 2.0

    def __init__(
        self,
        handoff_chain: dict[str, str] | None = None,
        handoff_window_s: float = DEFAULT_HANDOFF_WINDOW_S,
    ) -> None:
        # upstream role → downstream role. Default reflects the physical rig:
        # c_channel_2 pours into c_channel_3.
        self._handoff_chain: dict[str, str] = dict(handoff_chain or {"c_channel_2": "c_channel_3"})
        self._reverse_chain: dict[str, str] = {v: k for k, v in self._handoff_chain.items()}
        self._window_s = float(handoff_window_s)
        self._lock = threading.Lock()
        self._id_counter = 0
        # Pending queue keyed by upstream role; each role holds a FIFO of deaths.
        self._pending: dict[str, deque[PendingHandoff]] = {role: deque() for role in self._handoff_chain}
        self._entry_zones: dict[str, list[tuple[float, float]]] = {}
        self._exit_zones: dict[str, list[tuple[float, float]]] = {}

    def seed_id_counter(self, last_used_global_id: int) -> None:
        """Bump the counter past an already-used id so future tracks
        don't collide with persisted history after a backend restart.
        """
        with self._lock:
            if int(last_used_global_id) > self._id_counter:
                self._id_counter = int(last_used_global_id)

    # ---- Config --------------------------------------------------------

    def set_zones(
        self,
        role: str,
        *,
        entry_polygon: Iterable[tuple[float, float]] | None = None,
        exit_polygon: Iterable[tuple[float, float]] | None = None,
    ) -> None:
        with self._lock:
            if entry_polygon is not None:
                self._entry_zones[role] = [(float(x), float(y)) for x, y in entry_polygon]
            if exit_polygon is not None:
                self._exit_zones[role] = [(float(x), float(y)) for x, y in exit_polygon]

    # ---- Live hooks ----------------------------------------------------

    def register_track(self, role: str, center: tuple[float, float], timestamp: float) -> tuple[int, str | None]:
        """Called on new-track birth. Returns ``(global_id, handoff_from)``."""
        with self._lock:
            self._prune_locked(timestamp)
            upstream = self._reverse_chain.get(role)
            entry = self._entry_zones.get(role)
            if upstream and entry and _point_in_polygon(center, entry):
                bucket = self._pending.get(upstream)
                if bucket:
                    claimed = bucket.popleft()
                    return claimed.global_id, upstream
            self._id_counter += 1
            return self._id_counter, None

    def notify_track_death(
        self,
        role: str,
        global_id: int,
        last_center: tuple[float, float],
        last_seen_ts: float,
        death_ts: float | None = None,
    ) -> None:
        """Called when a tracker loses a track. Queue it for downstream pickup if in exit zone.

        The handoff window starts at ``death_ts`` (i.e. the tick where we gave
        up on the track), not ``last_seen_ts`` — otherwise tracks that coasted
        for a few frames before being killed would expire instantly.
        """
        with self._lock:
            if role not in self._handoff_chain:
                return
            exit_zone = self._exit_zones.get(role)
            if exit_zone is None or not _point_in_polygon(last_center, exit_zone):
                return
            anchor = float(death_ts) if death_ts is not None else float(last_seen_ts)
            pending = PendingHandoff(
                from_role=role,
                global_id=global_id,
                last_center=last_center,
                last_seen_ts=last_seen_ts,
                expires_at=anchor + self._window_s,
            )
            self._pending.setdefault(role, deque()).append(pending)

    # ---- Maintenance ---------------------------------------------------

    def prune(self, now: float) -> None:
        with self._lock:
            self._prune_locked(now)

    def _prune_locked(self, now: float) -> None:
        for bucket in self._pending.values():
            while bucket and bucket[0].expires_at < now:
                bucket.popleft()

    def reset(self) -> None:
        """Clear pending handoff queues. Intentionally keeps ``_id_counter``
        monotonic across the process lifetime — zeroing it here meant
        every profile switch / pause cycle handed out ``global_id=1``
        again and ``record_segment`` appended to the wrong history entry.
        """
        with self._lock:
            for bucket in self._pending.values():
                bucket.clear()

    # ---- Introspection -------------------------------------------------

    def pending_snapshot(self) -> list[dict]:
        with self._lock:
            snap: list[dict] = []
            for role, bucket in self._pending.items():
                for entry in bucket:
                    snap.append(
                        {
                            "from_role": role,
                            "global_id": entry.global_id,
                            "last_center": list(entry.last_center),
                            "last_seen_ts": entry.last_seen_ts,
                            "expires_at": entry.expires_at,
                        }
                    )
            return snap

    @property
    def handoff_window_s(self) -> float:
        return self._window_s
