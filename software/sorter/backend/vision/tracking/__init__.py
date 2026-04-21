"""Feeder multi-object tracker + cross-camera piece handoff.

Default tracker is :class:`PolarFeederTracker`, which tracks pieces in
``(angle, radius)`` space to match the circular channel geometry. The
ByteTrack wrapper is kept around as a fallback for situations where
channel geometry isn't available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Any

from .base import PendingHandoff, TrackedPiece, Tracker
from .bytetrack_tracker import ByteTrackFeederTracker
from .drop_zone_burst import DropZoneBurstCollector, RollingFrameBuffer
from .handoff import PieceHandoffManager
from .history import DropZoneBurstFrame, PieceHistoryBuffer, TrackHistoryEntry, TrackSegment
from .polar_tracker import PolarFeederTracker


DEFAULT_HISTORY_PERSIST_DIR = (
    Path(__file__).resolve().parent.parent.parent / "blob" / "tracked_history"
)


# Backwards-compatible alias for call sites / tests that still import the
# old name. Default implementation is the polar tracker.
SortFeederTracker = PolarFeederTracker


def build_feeder_tracker_system(
    roles: tuple[str, ...] = ("c_channel_2", "c_channel_3"),
    *,
    handoff_window_s: float = 6.0,
    detection_score_threshold: float = 0.1,
    history: PieceHistoryBuffer | None = None,
    frame_rate: int = 5,  # kept for signature compat with older callers
    exit_observer: Callable[..., Any] | None = None,
    ghost_reject_observer: Callable[..., Any] | None = None,
    embedding_rebind_observer: Callable[..., Any] | None = None,
    stale_pending_observer: Callable[..., Any] | None = None,
    id_switch_suspect_observer: Callable[..., Any] | None = None,
) -> tuple[PieceHandoffManager, dict[str, PolarFeederTracker], PieceHistoryBuffer]:
    """Create a handoff manager + per-role polar trackers wired together.

    ``roles`` ordering determines the default handoff chain: each role pours
    into the next, with one intentional exception — ``c_channel_2`` is
    **not** registered as an upstream handoff source. Clumping in C2 made
    the C2→C3 cross-camera identity transfer unreliable and actively harmful
    (user decision), so C3 tracks always get fresh ``global_id``s. The C2
    tracker is still built for per-channel feeder analysis / exit-section
    wiggle; only the handoff edge is dropped. The C3→carousel edge stays.

    The returned ``PieceHistoryBuffer`` is shared by all trackers — when a
    piece dies on one camera, its final ``TrackSegment`` is recorded; if it
    later inherits the same ``global_id`` downstream, the new segment is
    appended to the same history entry.
    """
    _ = frame_rate  # unused by the polar tracker, accepted for compat
    # Drop the c_channel_2 → c_channel_3 edge: see docstring above. Every
    # other adjacent pair in ``roles`` is wired as usual.
    chain = {
        roles[i]: roles[i + 1]
        for i in range(len(roles) - 1)
        if roles[i] != "c_channel_2"
    }
    # Late-bound probe — trackers dict is populated below, but the manager
    # is needed to construct them. The closure references the dict by name
    # so the trackers defined later are visible at call time.
    trackers: dict[str, PolarFeederTracker] = {}

    def _live_ids_probe(upstream_role: str) -> set[int]:
        tracker = trackers.get(upstream_role)
        if tracker is None:
            return set()
        try:
            return tracker.live_global_ids()
        except Exception:
            return set()

    manager = PieceHandoffManager(
        handoff_chain=chain,
        handoff_window_s=handoff_window_s,
        exit_observer=exit_observer,
        ghost_reject_observer=ghost_reject_observer,
        embedding_rebind_observer=embedding_rebind_observer,
        upstream_live_ids_probe=_live_ids_probe,
        stale_pending_observer=stale_pending_observer,
    )
    if history is None:
        history = PieceHistoryBuffer(persist_dir=DEFAULT_HISTORY_PERSIST_DIR)
    # Seed the id counter past any persisted global_id so fresh tracks
    # after a restart don't append segments to an existing (and unrelated)
    # history entry.
    try:
        manager.seed_id_counter(history.max_global_id())
    except Exception:
        pass
    for role in roles:
        tracker_kwargs = {
            "role": role,
            "handoff_manager": manager,
            "detection_score_threshold": detection_score_threshold,
            "history": history,
            "id_switch_suspect_observer": id_switch_suspect_observer,
        }
        if role == "carousel":
            # The dedicated classification channel is especially sensitive to
            # static ghost boxes when the plate is empty. Be more aggressive
            # there, while leaving c_channel_2 / c_channel_3 unchanged.
            tracker_kwargs.update(
                persist_static_ghost_regions=True,
                enable_stagnant_false_track_filter=True,
                stagnant_false_track_max_age_s=1.5,
                stagnant_false_track_min_displacement_px=24.0,
                stagnant_false_track_min_path_length_px=60.0,
                stagnant_false_track_suppression_radius_px=56.0,
                stagnant_false_track_suppression_ttl_s=5.0,
                # Pieces physically parked at the drop zone waiting for
                # distribution_ready would otherwise be killed by the
                # stagnant filter (1.5s max age, 24px min displacement).
                # The classification channel state machine pins them via
                # mark_pending_drop() until the chute actually fires.
                stagnant_false_track_pending_drop_protect_s=4.0,
            )
        elif role == "c_channel_2":
            # The upstream singulation channel can briefly park real pieces,
            # so keep the stagnant-track suppression conservative here.
            # Persist ghost regions across sessions so stationary apparatus
            # artefacts (screws, reflections, guides) stay suppressed after
            # a restart instead of having to re-learn them each run.
            tracker_kwargs.update(
                persist_static_ghost_regions=True,
                enable_stagnant_false_track_filter=True,
                stagnant_false_track_max_age_s=6.0,
                stagnant_false_track_min_displacement_px=14.0,
                stagnant_false_track_min_path_length_px=24.0,
                stagnant_false_track_suppression_radius_px=60.0,
                stagnant_false_track_suppression_ttl_s=8.0,
            )
        elif role == "c_channel_3":
            # C3 tends to see mount / guide ghosts that can block the whole
            # feeder if they linger. Cull non-moving tracks sooner than on
            # C2, and keep a wider suppression bubble around them so they do
            # not immediately respawn on the next frame. Persist the
            # learned regions so apparatus-bound ghosts (which never move)
            # survive restarts.
            tracker_kwargs.update(
                persist_static_ghost_regions=True,
                enable_stagnant_false_track_filter=True,
                stagnant_false_track_max_age_s=3.0,
                stagnant_false_track_min_displacement_px=18.0,
                stagnant_false_track_min_path_length_px=30.0,
                stagnant_false_track_suppression_radius_px=72.0,
                stagnant_false_track_suppression_ttl_s=12.0,
            )
        trackers[role] = PolarFeederTracker(**tracker_kwargs)
    return manager, trackers, history


__all__ = [
    "ByteTrackFeederTracker",
    "DropZoneBurstCollector",
    "DropZoneBurstFrame",
    "PendingHandoff",
    "PieceHandoffManager",
    "PieceHistoryBuffer",
    "PolarFeederTracker",
    "RollingFrameBuffer",
    "SortFeederTracker",
    "TrackHistoryEntry",
    "TrackSegment",
    "TrackedPiece",
    "Tracker",
    "build_feeder_tracker_system",
]
