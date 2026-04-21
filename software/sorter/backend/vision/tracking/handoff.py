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

import numpy as np

from .base import PendingHandoff


# Defaults for the ghost-reject heuristic. A dying upstream track counts as
# "stationary" when its max-displacement stayed below
# ``DEFAULT_GHOST_STATIONARY_THRESHOLD_PX``; a downstream claim is rejected
# when the new detection also sits within ``DEFAULT_GHOST_REJECT_RADIUS_PX``
# of the ghost's last known pixel position.
DEFAULT_GHOST_REJECT_RADIUS_PX: float = 25.0
DEFAULT_GHOST_STATIONARY_THRESHOLD_PX: float = 8.0

# Cosine-similarity floor for the embedding-based rebind. A candidate pending
# is only preferred over the FIFO head if its similarity with the claim
# exceeds this threshold — otherwise we fall back to strict FIFO, same as
# before the rebind logic existed. 0.35 is loose enough to survive one-sided
# lighting drift between cameras while still separating two distinct LEGO
# parts reliably (same-part cross-camera similarity is typically 0.5–0.8).
DEFAULT_SIMILARITY_THRESHOLD: float = 0.35


def _cosine_similarity(a: "np.ndarray | None", b: "np.ndarray | None") -> float:
    if a is None or b is None:
        return 0.0
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb + 1e-9))


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
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        embedding_rebind_observer: Callable[..., None] | None = None,
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
        self._similarity_threshold = max(0.0, float(similarity_threshold))
        self._embedding_rebind_observer = embedding_rebind_observer
        self._embedding_rebind_total = 0
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
        embedding: "np.ndarray | None" = None,
    ) -> tuple[int, str | None, str | None]:
        """Called on new-track birth. Returns
        ``(global_id, handoff_from, piece_uuid)``.

        ``piece_uuid`` is populated when a pending handoff claim is picked
        up AND the dying upstream track already had an early-bound piece
        dossier uuid (Phase 4). Otherwise ``None``. The polar tracker uses
        this third element to inherit the same dossier across the
        C3→Carousel transition.

        When multiple pendings are queued on the same upstream bucket and
        the claim carries an OSNet embedding, the manager picks the pending
        whose embedding has the highest cosine similarity to the claim
        (provided it clears ``similarity_threshold``). Otherwise the old
        FIFO behaviour stands — safe even when the embedder is disabled.
        """
        ghost_reject_payload: dict[str, object] | None = None
        rebind_payload: dict[str, object] | None = None
        stale_payloads: list[dict[str, object]] = []
        claimed_result: tuple[int, str, str | None] | None = None
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
                        pick_idx = self._pick_pending_idx(
                            bucket, embedding, live_ids
                        )
                        if pick_idx is not None:
                            claimed = bucket[pick_idx]
                            del bucket[pick_idx]
                            if pick_idx != 0:
                                self._embedding_rebind_total += 1
                                rebind_payload = {
                                    "from_role": upstream,
                                    "to_role": role,
                                    "claimed_global_id": int(claimed.global_id),
                                    "fifo_head_global_id": int(head.global_id),
                                    "claim_center": (float(center[0]), float(center[1])),
                                    "timestamp": float(timestamp),
                                }
                            claimed_result = (
                                int(claimed.global_id),
                                upstream,
                                claimed.piece_uuid,
                            )
            if claimed_result is None:
                self._id_counter += 1
                new_id = self._id_counter

        if ghost_reject_payload is not None and self._ghost_reject_observer is not None:
            try:
                self._ghost_reject_observer(**ghost_reject_payload)
            except Exception:
                pass
        if rebind_payload is not None and self._embedding_rebind_observer is not None:
            try:
                self._embedding_rebind_observer(**rebind_payload)
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
        return int(new_id), None, None  # type: ignore[arg-type]

    def _pick_pending_idx(
        self,
        bucket: "deque[PendingHandoff]",
        claim_embedding: "np.ndarray | None",
        live_ids: set[int] | None = None,
    ) -> int | None:
        """Choose which pending to hand the claim to.

        Returns ``None`` when every pending is stale (still alive upstream),
        signalling that the claim should get a fresh global id instead.

        Falls back to FIFO head (first non-stale pending) whenever:
          - the bucket has a single non-stale pending, OR
          - the claim carries no embedding, OR
          - no non-stale pending clears ``similarity_threshold``.
        """
        live = live_ids or set()
        non_stale_indices = [
            idx for idx, p in enumerate(bucket) if int(p.global_id) not in live
        ]
        if not non_stale_indices:
            return None
        if len(non_stale_indices) == 1 or claim_embedding is None:
            return non_stale_indices[0]
        best_idx = non_stale_indices[0]
        best_sim = -1.0
        for idx in non_stale_indices:
            pending = bucket[idx]
            sim = _cosine_similarity(claim_embedding, pending.embedding)
            if sim > best_sim:
                best_sim = sim
                best_idx = idx
        if best_sim < self._similarity_threshold:
            return non_stale_indices[0]
        return best_idx

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
        embedding: "np.ndarray | None" = None,
        piece_uuid: str | None = None,
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
                embedding=embedding,
                piece_uuid=piece_uuid,
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
    def embedding_rebind_total(self) -> int:
        """Cumulative count of claims where embedding similarity beat FIFO."""
        with self._lock:
            return int(self._embedding_rebind_total)

    @property
    def stale_pending_dropped_total(self) -> int:
        """Cumulative count of pendings dropped because the upstream piece
        was still physically alive when a downstream claim arrived."""
        with self._lock:
            return int(self._stale_pending_dropped_total)
