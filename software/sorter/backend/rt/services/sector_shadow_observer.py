"""Sector-based shadow observer.

A non-invasive comparison layer: at every tick, it takes the live
piece-track angles (from BoxMot) and computes what the *legacy main*
feeder logic would have decided. The observer does not change runtime
behaviour — it logs side-by-side what sorthive's actual decision was
and what Main's sector-based decision would have been, so we can quantify
the architectural difference.

Inspiration: ``software/client/subsystems/feeder/feeding.py`` and
``analysis.py`` on the ``main`` branch. Main treats each C-channel
purely as a state machine over angular *sections*:

* if a track sits in the "precise" (near-exit) arc → PULSE_PRECISE
* elif any track is on the platter → PULSE_NORMAL
* else IDLE

Backpressure is just one bool per channel (``intake_arc_occupied``):
the upstream channel is blocked while the downstream channel's intake
arc is occupied. No leases, no dossiers, no hysteresis.

We keep BoxMot tracking for image-collection / classification so this
observer reads the *same* angle field every other gate consumes — only
the decision interpretation differs.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ChannelAction = str  # "idle" | "pulse_normal" | "pulse_precise"

ACTION_IDLE = "idle"
ACTION_PULSE_NORMAL = "pulse_normal"
ACTION_PULSE_PRECISE = "pulse_precise"


@dataclass(frozen=True, slots=True)
class ChannelGeometry:
    """Per-channel angular geometry, in degrees.

    Angles match the convention of the runtime track snapshots:
    ``angle_deg in [-180, 180]`` with ``0°`` being the channel's exit
    reference. ``intake_center_deg`` is where pieces arrive from the
    upstream channel (often near ±180°).
    """

    name: str
    exit_arc_deg: float          # half-width of the precise arc around exit (0°)
    intake_center_deg: float     # center angle of the intake/dropzone
    intake_arc_deg: float        # half-width of the intake arc


@dataclass(slots=True)
class _ChannelObservation:
    name: str
    piece_count: int = 0
    pieces_in_exit: int = 0
    pieces_in_intake: int = 0
    action: ChannelAction = ACTION_IDLE
    intake_occupied: bool = False


@dataclass(slots=True)
class _ShadowSample:
    ts_mono: float
    ts_wall: float
    c2: _ChannelObservation
    c3: _ChannelObservation
    main_allow_c1: bool
    main_allow_c2: bool
    main_allow_c3: bool
    sorthive_c1_blocked_reason: str | None
    sorthive_c2_blocked_reason: str | None
    sorthive_c3_blocked_reason: str | None
    divergence_c1: bool
    divergence_c2: bool
    divergence_c3: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts_mono": self.ts_mono,
            "ts_wall": self.ts_wall,
            "c2": {
                "piece_count": self.c2.piece_count,
                "pieces_in_exit": self.c2.pieces_in_exit,
                "pieces_in_intake": self.c2.pieces_in_intake,
                "action": self.c2.action,
                "intake_occupied": self.c2.intake_occupied,
            },
            "c3": {
                "piece_count": self.c3.piece_count,
                "pieces_in_exit": self.c3.pieces_in_exit,
                "pieces_in_intake": self.c3.pieces_in_intake,
                "action": self.c3.action,
                "intake_occupied": self.c3.intake_occupied,
            },
            "main_allow_c1": self.main_allow_c1,
            "main_allow_c2": self.main_allow_c2,
            "main_allow_c3": self.main_allow_c3,
            "sorthive_c1_blocked_reason": self.sorthive_c1_blocked_reason,
            "sorthive_c2_blocked_reason": self.sorthive_c2_blocked_reason,
            "sorthive_c3_blocked_reason": self.sorthive_c3_blocked_reason,
            "divergence_c1": self.divergence_c1,
            "divergence_c2": self.divergence_c2,
            "divergence_c3": self.divergence_c3,
        }


# Tracks are passed in as a list of ``(angle_deg, piece_uuid_or_global_id)``
# pairs. Keeping it primitive avoids leaking the runtime contract into the
# observer.
TrackList = list[tuple[float, str | int | None]]
SnapshotProvider = Callable[[], dict[str, Any]]


def _wrap_180(angle_deg: float) -> float:
    a = float(angle_deg) % 360.0
    if a > 180.0:
        a -= 360.0
    elif a <= -180.0:
        a += 360.0
    return a


def _angular_distance_deg(a: float, b: float) -> float:
    """Smallest absolute difference on the unit circle, in degrees."""
    diff = (float(a) - float(b)) % 360.0
    if diff > 180.0:
        diff = 360.0 - diff
    return diff


def classify_channel(
    geometry: ChannelGeometry,
    track_angles_deg: list[float],
) -> _ChannelObservation:
    """Apply Main's per-channel sector logic to a list of track angles.

    Returns the inferred action plus piece counts in the exit and
    intake arcs. The caller is responsible for telling the observer
    *which* channel this is (geometry.name) so the report is keyed.
    """
    obs = _ChannelObservation(name=geometry.name)
    obs.piece_count = len(track_angles_deg)
    for angle in track_angles_deg:
        if _angular_distance_deg(angle, 0.0) <= geometry.exit_arc_deg:
            obs.pieces_in_exit += 1
        if (
            _angular_distance_deg(angle, geometry.intake_center_deg)
            <= geometry.intake_arc_deg
        ):
            obs.pieces_in_intake += 1
    if obs.pieces_in_exit > 0:
        obs.action = ACTION_PULSE_PRECISE
    elif obs.piece_count > 0:
        obs.action = ACTION_PULSE_NORMAL
    else:
        obs.action = ACTION_IDLE
    obs.intake_occupied = obs.pieces_in_intake > 0
    return obs


# Reasons in sorthive's capacity_debug.c1.reason that map to "blocked".
# A reason that *would* have allowed C1 in Main's model counts as a
# divergence. (Anything else — e.g. ``ok`` — is treated as "allowed".)
_BLOCKED_REASONS_NOT_DROPZONE = frozenset(
    {
        "vision_target_high",
        "vision_target_band",
        "vision_density_clump",
        "vision_exit_queue",
        "backlog_dossiers",
        "backlog_raw",
        "backlog_dossiers_holding",
        "backlog_raw_holding",
    }
)


class SectorShadowObserver:
    """Periodic shadow inference of Main's sector-based feeder logic.

    Hooked from the orchestrator: ``tick()`` runs at the orchestrator
    cadence (50 Hz by default), but the observer downsamples to a
    configurable wall-clock period to keep the JSONL manageable.

    The observer is responsible for everything below — the orchestrator
    only injects the snapshot provider.
    """

    DEFAULT_SAMPLE_PERIOD_S = 0.5
    DEFAULT_HISTORY = 600

    def __init__(
        self,
        *,
        snapshot_provider: SnapshotProvider,
        c2_geometry: ChannelGeometry,
        c3_geometry: ChannelGeometry,
        log_path: Path | str | None = None,
        sample_period_s: float = DEFAULT_SAMPLE_PERIOD_S,
        history_limit: int = DEFAULT_HISTORY,
        logger: logging.Logger | None = None,
    ) -> None:
        if sample_period_s <= 0.0:
            raise ValueError("sample_period_s must be > 0")
        self._provider = snapshot_provider
        self._c2_geometry = c2_geometry
        self._c3_geometry = c3_geometry
        self._log_path = Path(log_path) if log_path is not None else None
        self._sample_period_s = float(sample_period_s)
        self._history_limit = max(1, int(history_limit))
        self._logger = logger or logging.getLogger("rt.sector_shadow_observer")
        self._lock = threading.Lock()
        self._next_sample_at_mono: float = 0.0
        self._samples: list[_ShadowSample] = []
        self._divergence_counts: dict[str, int] = {
            "c1": 0,
            "c2": 0,
            "c3": 0,
        }
        self._sample_count = 0

    # ------------------------------------------------------------------
    # Public API

    def tick(self, now_mono: float | None = None) -> None:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        if ts < self._next_sample_at_mono:
            return
        self._next_sample_at_mono = ts + self._sample_period_s
        try:
            payload = dict(self._provider() or {})
        except Exception:
            self._logger.exception(
                "SectorShadowObserver: snapshot provider raised"
            )
            return
        self._record(payload, ts)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "sample_count": int(self._sample_count),
                "history_count": int(len(self._samples)),
                "sample_period_s": float(self._sample_period_s),
                "divergence_counts": dict(self._divergence_counts),
                "c2_geometry": {
                    "exit_arc_deg": self._c2_geometry.exit_arc_deg,
                    "intake_center_deg": self._c2_geometry.intake_center_deg,
                    "intake_arc_deg": self._c2_geometry.intake_arc_deg,
                },
                "c3_geometry": {
                    "exit_arc_deg": self._c3_geometry.exit_arc_deg,
                    "intake_center_deg": self._c3_geometry.intake_center_deg,
                    "intake_arc_deg": self._c3_geometry.intake_arc_deg,
                },
                "log_path": str(self._log_path) if self._log_path else None,
            }

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        cap = max(1, int(limit))
        with self._lock:
            return [s.to_dict() for s in self._samples[-cap:]]

    # ------------------------------------------------------------------
    # Internals

    def _record(self, payload: dict[str, Any], ts_mono: float) -> None:
        c2_angles = _angles_from(payload.get("c2_tracks") or [])
        c3_angles = _angles_from(payload.get("c3_tracks") or [])
        c2 = classify_channel(self._c2_geometry, c2_angles)
        c3 = classify_channel(self._c3_geometry, c3_angles)

        # Main's gates: a channel may pulse if its downstream's intake
        # is clear. C3's downstream in this system is C4 (the polar
        # classifier, equivalent to the carousel feeder slot), so we
        # take that bool from the actual runtime instead of inferring it.
        c4_intake_blocked = bool(payload.get("c4_intake_blocked", False))
        main_allow_c1 = not c2.intake_occupied
        main_allow_c2 = not c3.intake_occupied
        main_allow_c3 = not c4_intake_blocked

        sorthive_c1_reason = payload.get("sorthive_c1_blocked_reason")
        sorthive_c2_reason = payload.get("sorthive_c2_blocked_reason")
        sorthive_c3_reason = payload.get("sorthive_c3_blocked_reason")

        sorthive_c1_blocked = sorthive_c1_reason is not None
        sorthive_c2_blocked = sorthive_c2_reason is not None
        sorthive_c3_blocked = sorthive_c3_reason is not None

        # Divergence: Main would allow but sorthive blocked, or vice-versa.
        # In practice the interesting direction is "Main would have let
        # this through but sorthive held back" — that's where main's
        # higher PPM came from.
        divergence_c1 = main_allow_c1 != (not sorthive_c1_blocked)
        divergence_c2 = main_allow_c2 != (not sorthive_c2_blocked)
        divergence_c3 = main_allow_c3 != (not sorthive_c3_blocked)

        sample = _ShadowSample(
            ts_mono=ts_mono,
            ts_wall=time.time(),
            c2=c2,
            c3=c3,
            main_allow_c1=main_allow_c1,
            main_allow_c2=main_allow_c2,
            main_allow_c3=main_allow_c3,
            sorthive_c1_blocked_reason=sorthive_c1_reason,
            sorthive_c2_blocked_reason=sorthive_c2_reason,
            sorthive_c3_blocked_reason=sorthive_c3_reason,
            divergence_c1=divergence_c1,
            divergence_c2=divergence_c2,
            divergence_c3=divergence_c3,
        )
        with self._lock:
            self._samples.append(sample)
            if len(self._samples) > self._history_limit:
                drop = len(self._samples) - self._history_limit
                self._samples = self._samples[drop:]
            self._sample_count += 1
            if divergence_c1:
                self._divergence_counts["c1"] += 1
            if divergence_c2:
                self._divergence_counts["c2"] += 1
            if divergence_c3:
                self._divergence_counts["c3"] += 1
        self._maybe_persist(sample)

    def _maybe_persist(self, sample: _ShadowSample) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(sample.to_dict(), separators=(",", ":")) + "\n")
        except Exception:
            self._logger.exception(
                "SectorShadowObserver: failed to persist sample"
            )


def _angles_from(items: list[Any]) -> list[float]:
    """Pull ``angle_deg`` out of either dicts or (angle, _) tuples."""
    out: list[float] = []
    for item in items:
        if isinstance(item, dict):
            angle = item.get("angle_deg")
        elif isinstance(item, (tuple, list)) and item:
            angle = item[0]
        else:
            angle = None
        if isinstance(angle, (int, float)):
            out.append(_wrap_180(float(angle)))
    return out


__all__ = [
    "SectorShadowObserver",
    "ChannelGeometry",
    "classify_channel",
    "ACTION_IDLE",
    "ACTION_PULSE_NORMAL",
    "ACTION_PULSE_PRECISE",
]
