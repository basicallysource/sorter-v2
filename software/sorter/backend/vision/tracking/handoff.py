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

import math
import threading
from collections import deque
from typing import Callable, Iterable

from .base import PendingHandoff


# Defaults for the ghost-reject heuristic. A dying upstream track counts as
# "stationary" when its max-displacement stayed below
# ``DEFAULT_GHOST_STATIONARY_THRESHOLD_PX``; a downstream claim is rejected
# when the new detection also sits within ``DEFAULT_GHOST_REJECT_RADIUS_PX``
# of the ghost's last known pixel position.
DEFAULT_GHOST_REJECT_RADIUS_PX: float = 25.0
DEFAULT_GHOST_STATIONARY_THRESHOLD_PX: float = 8.0


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
        exit_observer: Callable[..., None] | None = None,
        ghost_reject_radius_px: float = DEFAULT_GHOST_REJECT_RADIUS_PX,
        ghost_stationary_threshold_px: float = DEFAULT_GHOST_STATIONARY_THRESHOLD_PX,
        ghost_reject_observer: Callable[..., None] | None = None,
        upstream_live_ids_probe: Callable[[str], set[int]] | None = None,
        stale_pending_observer: Callable[..., None] | None = None,
    ) -> None:
        # upstream role → downstream role. An explicit empty dict means
        # "no cross-camera handoffs"; only fall back to the rig default when
        # the caller passes ``None``. (Changed when C2 was removed from the
        # handoff chain — see ``build_feeder_tracker_system``.)
        if handoff_chain is None:
            handoff_chain = {"c_channel_3": "carousel"}
        self._handoff_chain: dict[str, str] = dict(handoff_chain)
        self._reverse_chain: dict[str, str] = {v: k for k, v in self._handoff_chain.items()}
        self._window_s = float(handoff_window_s)
        self._lock = threading.Lock()
        self._id_counter = 0
        # Pending queue keyed by upstream role; each role holds a FIFO of deaths.
        self._pending: dict[str, deque[PendingHandoff]] = {role: deque() for role in self._handoff_chain}
        self._entry_zones: dict[str, list[tuple[float, float]]] = {}
        self._exit_zones: dict[str, list[tuple[float, float]]] = {}
        self._exit_observer = exit_observer
        self._ghost_reject_radius_px = max(0.0, float(ghost_reject_radius_px))
        self._ghost_stationary_threshold_px = max(0.0, float(ghost_stationary_threshold_px))
        self._ghost_reject_observer = ghost_reject_observer
        self._ghost_rejected_total = 0
        self._upstream_live_ids_probe = upstream_live_ids_probe
        self._stale_pending_observer = stale_pending_observer
        self._stale_pending_dropped_total = 0

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

    def register_track(
        self,
        role: str,
        center: tuple[float, float],
        timestamp: float,
    ) -> tuple[int, str | None]:
        """Called on new-track birth. Returns ``(global_id, handoff_from)``.

        Pickup follows strict FIFO order on the upstream bucket. Ghost
        rejection and upstream-liveness filtering still apply; any
        non-stale, non-ghost pending head claims the new track.
        """
        ghost_reject_payload: dict[str, object] | None = None
        stale_payloads: list[dict[str, object]] = []
        claimed_result: tuple[int, str] | None = None
        new_id: int | None = None

        with self._lock:
            self._prune_locked(timestamp)
            upstream = self._reverse_chain.get(role)
            # Upstream-liveness probe: any pending whose global_id is still
            # physically alive on the upstream tracker is stale — the piece
            # hasn't actually left yet, so the death that queued this pending
            # was a mis-drop (coast expiry on a real piece still on camera).
            live_ids: set[int] = set()
            if self._upstream_live_ids_probe is not None and upstream is not None:
                try:
                    live_ids = set(self._upstream_live_ids_probe(upstream))
                except Exception:
                    live_ids = set()
            entry = self._entry_zones.get(role)
            if upstream and entry and _point_in_polygon(center, entry):
                bucket = self._pending.get(upstream)
                # Pop any FIFO-head pending that the upstream tracker still
                # holds alive — it was queued by a premature coast-death but
                # the piece is still on camera. These were never valid
                # handoff candidates.
                while bucket and bucket[0].global_id in live_ids:
                    stale = bucket.popleft()
                    self._stale_pending_dropped_total += 1
                    stale_payloads.append(
                        {
                            "from_role": upstream,
                            "to_role": role,
                            "stale_global_id": int(stale.global_id),
                            "claim_center": (float(center[0]), float(center[1])),
                            "timestamp": float(timestamp),
                        }
                    )
                if bucket:
                    head = bucket[0]
                    if self._is_ghost_claim(head, center):
                        # Drop the ghost pending so it can't block legitimate
                        # future claims and don't inherit its id. The new
                        # track falls through to the fresh-id path below.
                        bucket.popleft()
                        self._ghost_rejected_total += 1
                        ghost_reject_payload = {
                            "from_role": upstream,
                            "to_role": role,
                            "ghost_global_id": int(head.global_id),
                            "ghost_last_center": (
                                float(head.last_center[0]),
                                float(head.last_center[1]),
                            ),
                            "claim_center": (float(center[0]), float(center[1])),
                            "ghost_displacement_px": float(head.last_displacement_px),
                            "timestamp": float(timestamp),
                        }
                    else:
                        non_stale_indices = [
                            idx for idx, p in enumerate(bucket)
                            if int(p.global_id) not in live_ids
                        ]
                        if non_stale_indices:
                            pick_idx = non_stale_indices[0]
                            claimed = bucket[pick_idx]
                            del bucket[pick_idx]
                            claimed_result = (int(claimed.global_id), upstream)
            if claimed_result is None:
                self._id_counter += 1
                new_id = self._id_counter

        if ghost_reject_payload is not None and self._ghost_reject_observer is not None:
            try:
                self._ghost_reject_observer(**ghost_reject_payload)
            except Exception:
                pass
        if stale_payloads and self._stale_pending_observer is not None:
            for payload in stale_payloads:
                try:
                    self._stale_pending_observer(**payload)
                except Exception:
                    pass
        if claimed_result is not None:
            return claimed_result
        return int(new_id), None  # type: ignore[arg-type]

    def _is_ghost_claim(
        self,
        pending: PendingHandoff,
        claim_center: tuple[float, float],
    ) -> bool:
        """True when a downstream claim looks like a cross-camera ghost.

        A claim is a ghost when the dying upstream track was stationary
        (max displacement below threshold) AND the new downstream detection
        sits within the reject radius of the ghost's last known center.
        """
        if pending.last_displacement_px >= self._ghost_stationary_threshold_px:
            return False
        gx, gy = pending.last_center
        cx, cy = claim_center
        if math.hypot(cx - gx, cy - gy) > self._ghost_reject_radius_px:
            return False
        return True

    def notify_track_death(
        self,
        role: str,
        global_id: int,
        last_center: tuple[float, float],
        last_seen_ts: float,
        death_ts: float | None = None,
        last_displacement_px: float = 0.0,
    ) -> None:
        """Called when a tracker loses a track. Queue it for downstream pickup if in exit zone.

        The handoff window starts at ``death_ts`` (i.e. the tick where we gave
        up on the track), not ``last_seen_ts`` — otherwise tracks that coasted
        for a few frames before being killed would expire instantly.
        """
        callback: Callable[..., None] | None = None
        callback_payload: dict[str, object] | None = None
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
                last_displacement_px=max(0.0, float(last_displacement_px)),
            )
            self._pending.setdefault(role, deque()).append(pending)
            callback = self._exit_observer
            callback_payload = {
                "channel": role,
                "global_id": int(global_id),
                "exited_at": anchor,
                "last_seen_ts": float(last_seen_ts),
                "last_center": (float(last_center[0]), float(last_center[1])),
            }
        if callback is not None and callback_payload is not None:
            try:
                callback(**callback_payload)
            except Exception:
                pass

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
                            "last_displacement_px": entry.last_displacement_px,
                        }
                    )
            return snap

    @property
    def handoff_window_s(self) -> float:
        return self._window_s

    @property
    def ghost_rejected_total(self) -> int:
        """Cumulative count of handoff claims rejected as cross-camera ghosts."""
        with self._lock:
            return int(self._ghost_rejected_total)

    @property
    def stale_pending_dropped_total(self) -> int:
        """Cumulative count of pendings dropped because the upstream piece
        was still physically alive when a downstream claim arrived."""
        with self._lock:
            return int(self._stale_pending_dropped_total)
