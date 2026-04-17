"""Feeder multi-object tracker + cross-camera piece handoff.

Default tracker is :class:`PolarFeederTracker`, which tracks pieces in
``(angle, radius)`` space to match the circular channel geometry. The
ByteTrack wrapper is kept around as a fallback for situations where
channel geometry isn't available.
"""

from __future__ import annotations

from .base import PendingHandoff, TrackedPiece, Tracker
from .bytetrack_tracker import ByteTrackFeederTracker
from .handoff import PieceHandoffManager
from .history import PieceHistoryBuffer, TrackHistoryEntry, TrackSegment
from .polar_tracker import PolarFeederTracker


# Backwards-compatible alias for call sites / tests that still import the
# old name. Default implementation is the polar tracker.
SortFeederTracker = PolarFeederTracker


def build_feeder_tracker_system(
    roles: tuple[str, ...] = ("c_channel_2", "c_channel_3"),
    *,
    handoff_window_s: float = 4.0,
    detection_score_threshold: float = 0.1,
    history: PieceHistoryBuffer | None = None,
    frame_rate: int = 5,  # kept for signature compat with older callers
) -> tuple[PieceHandoffManager, dict[str, PolarFeederTracker], PieceHistoryBuffer]:
    """Create a handoff manager + per-role polar trackers wired together.

    ``roles`` ordering determines the default handoff chain: each role pours
    into the next (``c_channel_2 → c_channel_3``). The returned
    ``PieceHistoryBuffer`` is shared by all trackers — when a piece dies on
    one camera, its final ``TrackSegment`` is recorded; if it later inherits
    the same ``global_id`` downstream, the new segment is appended to the
    same history entry.
    """
    _ = frame_rate  # unused by the polar tracker, accepted for compat
    chain = {roles[i]: roles[i + 1] for i in range(len(roles) - 1)}
    manager = PieceHandoffManager(handoff_chain=chain, handoff_window_s=handoff_window_s)
    if history is None:
        history = PieceHistoryBuffer()
    trackers = {
        role: PolarFeederTracker(
            role=role,
            handoff_manager=manager,
            detection_score_threshold=detection_score_threshold,
            history=history,
        )
        for role in roles
    }
    return manager, trackers, history


__all__ = [
    "ByteTrackFeederTracker",
    "PendingHandoff",
    "PieceHandoffManager",
    "PieceHistoryBuffer",
    "PolarFeederTracker",
    "SortFeederTracker",
    "TrackHistoryEntry",
    "TrackSegment",
    "TrackedPiece",
    "Tracker",
    "build_feeder_tracker_system",
]
