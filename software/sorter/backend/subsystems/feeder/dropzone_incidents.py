from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from defs.channel import ChannelDetection
from subsystems.channels.base import (
    CHANNEL_DROPZONE_STUCK_INCIDENT_KIND,
    publish_channel_dropzone_stuck_incident,
)
from subsystems.feeder.analysis import bboxSectionOverlapRatio, getBboxSections


DROPZONE_STUCK_OVERLAP_THRESHOLD: float = 2.0 / 3.0
DROPZONE_STUCK_STALL_MS: int = 5000
DROPZONE_IGNORED_MISSING_GRACE_S: float = 0.75


@dataclass
class _DropzoneTrackState:
    first_seen_mono: float
    last_seen_mono: float
    last_update_mono: float
    was_rotating: bool
    accumulated_motion_s: float
    max_overlap: float
    bbox: tuple[int, int, int, int]


@dataclass
class _IgnoredDropzoneTrack:
    acknowledged_at_mono: float
    last_seen_mono: float
    bbox: tuple[int, int, int, int]


class DropzoneStuckIncidentManager:
    """Detect and manage C2/C3/C4 objects parked in a dropzone.

    A newly stuck track is operator-facing and blocks the process via
    ``runtime_stats.active_incident``. Once acknowledged, only that exact track
    is ignored for dropzone backpressure / intake admission until it leaves the
    dropzone or disappears for a short grace period.
    """

    def __init__(
        self,
        *,
        gc: Any,
        overlap_threshold: float = DROPZONE_STUCK_OVERLAP_THRESHOLD,
        stall_ms: int = DROPZONE_STUCK_STALL_MS,
        missing_grace_s: float = DROPZONE_IGNORED_MISSING_GRACE_S,
        on_ignored_change: Callable[[int, int, bool], None] | None = None,
    ) -> None:
        self._gc = gc
        self._overlap_threshold = float(overlap_threshold)
        self._stall_ms = int(stall_ms)
        self._missing_grace_s = float(missing_grace_s)
        self._on_ignored_change = on_ignored_change
        self._candidates: dict[tuple[int, int], _DropzoneTrackState] = {}
        self._ignored: dict[tuple[int, int], _IgnoredDropzoneTrack] = {}
        self._pending_motion_s_by_channel: dict[int, float] = {}

    def ignored_detection_ids(self) -> set[tuple[int, int]]:
        return set(self._ignored.keys())

    def note_channel_motion(self, channel_id: int, duration_s: float) -> None:
        """Credit commanded channel motion to stuck candidates on next update."""
        channel = int(channel_id)
        if channel not in (2, 3, 4):
            return
        duration = max(0.0, float(duration_s))
        if duration <= 0.0:
            return
        self._pending_motion_s_by_channel[channel] = (
            self._pending_motion_s_by_channel.get(channel, 0.0) + duration
        )

    def update(
        self,
        detections: Iterable[ChannelDetection],
        now_mono: float,
        *,
        rotating_channel_ids: set[int] | None = None,
    ) -> bool:
        """Update state and publish an incident if a track is stuck.

        The incident timer is accumulated rotor-active time, not wall-clock
        time. A piece may sit in a dropzone while the sorter is paused without
        getting blamed; only C2/C3/C4 motion while it remains in that dropzone
        counts toward the threshold.

        Returns True when this call published a new blocking incident, allowing
        the feeder tick to stop before sending more pulses.
        """
        rotating_channel_ids = rotating_channel_ids or set()
        motion_credit_by_channel = self._pending_motion_s_by_channel
        self._pending_motion_s_by_channel = {}
        seen_in_dropzone: set[tuple[int, int]] = set()
        seen_currently: set[tuple[int, int]] = set()
        published = False

        for det in detections:
            key = self._key_for_detection(det)
            if key is None:
                continue
            seen_currently.add(key)
            overlap = bboxSectionOverlapRatio(det.bbox, det.channel, det.channel.dropzone_sections)
            blocks_dropzone = self._blocks_dropzone(det, overlap)
            if blocks_dropzone:
                seen_in_dropzone.add(key)

            ignored = self._ignored.get(key)
            if ignored is not None:
                if blocks_dropzone:
                    ignored.last_seen_mono = float(now_mono)
                    ignored.bbox = self._bbox(det)
                else:
                    self._clear_ignored(key)
                self._candidates.pop(key, None)
                continue

            if not blocks_dropzone:
                self._candidates.pop(key, None)
                continue

            state = self._candidates.get(key)
            rotating_now = int(det.channel_id) in rotating_channel_ids
            if state is None:
                state = _DropzoneTrackState(
                    first_seen_mono=float(now_mono),
                    last_seen_mono=float(now_mono),
                    last_update_mono=float(now_mono),
                    was_rotating=rotating_now,
                    accumulated_motion_s=0.0,
                    max_overlap=float(overlap),
                    bbox=self._bbox(det),
                )
                self._candidates[key] = state
            else:
                state.accumulated_motion_s += motion_credit_by_channel.get(
                    int(det.channel_id),
                    0.0,
                )
                if rotating_now and state.was_rotating:
                    state.accumulated_motion_s += max(
                        0.0,
                        float(now_mono) - state.last_update_mono,
                    )
                state.last_seen_mono = float(now_mono)
                state.last_update_mono = float(now_mono)
                state.was_rotating = rotating_now
                state.max_overlap = max(state.max_overlap, float(overlap))
                state.bbox = self._bbox(det)

            stall_ms = int(round(state.accumulated_motion_s * 1000.0))
            if stall_ms >= self._stall_ms:
                published = self._publish(det, state, stall_ms) or published

        self._prune_missing_candidates(seen_in_dropzone, float(now_mono))
        self._prune_missing_ignored(seen_in_dropzone, seen_currently, float(now_mono))
        return published

    def acknowledge_active_incident(self, active: dict[str, Any], now_mono: float) -> dict[str, Any]:
        channel_id, global_id = self._key_for_incident(active)
        bbox = self._bbox_from_incident(active)
        key = (channel_id, global_id)
        self._set_ignored(
            key,
            _IgnoredDropzoneTrack(
                acknowledged_at_mono=float(now_mono),
                last_seen_mono=float(now_mono),
                bbox=bbox,
            ),
        )
        self._candidates.pop(key, None)
        runtime_stats = getattr(self._gc, "runtime_stats", None)
        if runtime_stats is not None and hasattr(runtime_stats, "clearActiveIncident"):
            runtime_stats.clearActiveIncident(
                kind=CHANNEL_DROPZONE_STUCK_INCIDENT_KIND, resolved_by="operator"
            )
        return {
            "ok": True,
            "acknowledged": True,
            "ignored_until_dropzone_clear": True,
            "channel": active.get("channel"),
            "global_id": global_id,
            "track_id": global_id,
        }

    def clear_active_incident(self, active: dict[str, Any]) -> dict[str, Any]:
        channel_id, global_id = self._key_for_incident(active)
        key = (channel_id, global_id)
        self._candidates.pop(key, None)
        self._clear_ignored(key)
        runtime_stats = getattr(self._gc, "runtime_stats", None)
        if runtime_stats is not None and hasattr(runtime_stats, "clearActiveIncident"):
            runtime_stats.clearActiveIncident(
                kind=CHANNEL_DROPZONE_STUCK_INCIDENT_KIND, resolved_by="operator"
            )
        return {
            "ok": True,
            "cleared": True,
            "channel": active.get("channel"),
            "global_id": global_id,
            "track_id": global_id,
        }

    def _set_ignored(
        self,
        key: tuple[int, int],
        ignored: _IgnoredDropzoneTrack,
    ) -> None:
        self._ignored[key] = ignored
        if self._on_ignored_change is not None:
            self._on_ignored_change(int(key[0]), int(key[1]), True)

    def _clear_ignored(self, key: tuple[int, int]) -> None:
        had_key = key in self._ignored
        self._ignored.pop(key, None)
        if had_key and self._on_ignored_change is not None:
            self._on_ignored_change(int(key[0]), int(key[1]), False)

    def _publish(
        self,
        det: ChannelDetection,
        state: _DropzoneTrackState,
        stall_ms: int,
    ) -> bool:
        info = self._channel_info(det.channel_id)
        if info is None:
            return False
        channel, role, label = info
        global_id = getattr(det, "global_id", None)
        if not isinstance(global_id, int):
            return False
        if self._automatic_enabled(CHANNEL_DROPZONE_STUCK_INCIDENT_KIND):
            key = (int(det.channel_id), int(global_id))
            self._set_ignored(
                key,
                _IgnoredDropzoneTrack(
                    acknowledged_at_mono=float(state.last_seen_mono),
                    last_seen_mono=float(state.last_seen_mono),
                    bbox=state.bbox,
                ),
            )
            self._candidates.pop(key, None)
            logger = getattr(self._gc, "logger", None)
            if logger is not None and hasattr(logger, "warning"):
                logger.warning(
                    "Feeder: auto-acknowledged %s dropzone incident for track #%d "
                    "after %d ms accumulated channel motion"
                    % (channel, int(global_id), int(stall_ms))
                )
            return False
        return publish_channel_dropzone_stuck_incident(
            self._gc,
            channel=channel,
            role=role,
            channel_label=label,
            global_id=int(global_id),
            bbox=state.bbox,
            overlap_ratio=state.max_overlap,
            overlap_threshold=self._overlap_threshold,
            stall_ms=stall_ms,
        )

    def _prune_missing_candidates(
        self,
        seen_in_dropzone: set[tuple[int, int]],
        now_mono: float,
    ) -> None:
        for key, state in list(self._candidates.items()):
            if key in seen_in_dropzone:
                continue
            if (now_mono - state.last_seen_mono) >= self._missing_grace_s:
                self._candidates.pop(key, None)

    def _prune_missing_ignored(
        self,
        seen_in_dropzone: set[tuple[int, int]],
        seen_currently: set[tuple[int, int]],
        now_mono: float,
    ) -> None:
        for key, state in list(self._ignored.items()):
            if key in seen_in_dropzone:
                continue
            if key in seen_currently or (now_mono - state.last_seen_mono) >= self._missing_grace_s:
                self._clear_ignored(key)

    @staticmethod
    def _key_for_detection(det: ChannelDetection) -> tuple[int, int] | None:
        channel_id = getattr(det, "channel_id", None)
        global_id = getattr(det, "global_id", None)
        if channel_id not in (2, 3, 4) or not isinstance(global_id, int):
            return None
        return int(channel_id), int(global_id)

    @staticmethod
    def _key_for_incident(active: dict[str, Any]) -> tuple[int, int]:
        channel = str(active.get("channel") or "").lower()
        if channel == "c2":
            channel_id = 2
        elif channel == "c3":
            channel_id = 3
        elif channel == "c4":
            channel_id = 4
        else:
            raise ValueError("Unsupported dropzone incident channel.")
        global_id = active.get("global_id", active.get("track_id"))
        if not isinstance(global_id, int):
            raise ValueError("Dropzone incident does not identify a tracker id.")
        return channel_id, int(global_id)

    @staticmethod
    def _channel_info(channel_id: int) -> tuple[str, str, str] | None:
        if channel_id == 2:
            return "c2", "c_channel_2", "C-Channel 2"
        if channel_id == 3:
            return "c3", "c_channel_3", "C-Channel 3"
        if channel_id == 4:
            return "c4", "carousel", "Classification Channel"
        return None

    @staticmethod
    def _bbox(det: ChannelDetection) -> tuple[int, int, int, int]:
        return tuple(int(value) for value in det.bbox[:4])

    def _blocks_dropzone(self, det: ChannelDetection, overlap: float) -> bool:
        """Mirror feeder backpressure so every blocker can become an incident."""
        if overlap >= self._overlap_threshold:
            return True
        try:
            return bool(getBboxSections(det.bbox, det.channel) & det.channel.dropzone_sections)
        except Exception:
            return overlap > 0.0

    @staticmethod
    def _bbox_from_incident(active: dict[str, Any]) -> tuple[int, int, int, int]:
        bbox = active.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            return (0, 0, 0, 0)
        return tuple(int(value) for value in bbox[:4])

    @staticmethod
    def _automatic_enabled(kind: str) -> bool:
        try:
            from toml_config import incidentHandlingAutomatic

            return bool(incidentHandlingAutomatic(kind))
        except Exception:
            return False
