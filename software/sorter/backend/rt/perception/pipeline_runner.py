"""PerceptionRunner: dedicated thread pulling frames through the pipeline.

Lifecycle: start() launches a daemon thread; stop() signals it to halt
and joins. The loop drains ``feed.latest()`` at roughly period_ms cadence,
skips duplicate frame_seq reads, and publishes each TrackBatch on the
optional EventBus under topic PERCEPTION_TRACKS. Exceptions in the loop
are logged; after MAX_CONSECUTIVE_ERRORS the runner stops and emits a
HARDWARE_ERROR event.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import replace
from typing import Any

from rt.contracts.events import Event, EventBus, Subscription
from rt.contracts.tracking import Track, TrackBatch, Tracker
from rt.events.topics import HARDWARE_ERROR, PERCEPTION_ROTATION, PERCEPTION_TRACKS
from rt.pieces.identity import new_tracker_epoch

from .pipeline import PerceptionFrameState, PerceptionPipeline
from .replay_capture import DetectorInputRecorder
from .track_stabilizer import TrackletStabilizer


_LOG = logging.getLogger(__name__)
_MAX_CONSECUTIVE_ERRORS = 10


def _track_preview(batch: TrackBatch | None) -> list[dict[str, Any]]:
    if batch is None:
        return []
    out: list[dict[str, Any]] = []
    for track in batch.tracks[:3]:
        angle_rad = getattr(track, "angle_rad", None)
        angle_deg = None
        if isinstance(angle_rad, (int, float)):
            angle_deg = round(math.degrees(float(angle_rad)), 3)
        first_seen_ts = getattr(track, "first_seen_ts", None)
        last_seen_ts = getattr(track, "last_seen_ts", None)
        age_s = None
        if isinstance(first_seen_ts, (int, float)) and isinstance(last_seen_ts, (int, float)):
            age_s = round(max(0.0, float(last_seen_ts) - float(first_seen_ts)), 3)
        out.append({
            "global_id": getattr(track, "global_id", None),
            "piece_uuid": getattr(track, "piece_uuid", None),
            "confirmed_real": bool(getattr(track, "confirmed_real", False)),
            "ghost": bool(getattr(track, "ghost", False)),
            "hit_count": getattr(track, "hit_count", None),
            "score": getattr(track, "score", None),
            "age_s": age_s,
            "angle_deg": angle_deg,
        })
    return out


def _track_center(track: Any) -> tuple[float, float] | None:
    bbox = getattr(track, "bbox_xyxy", None)
    if not isinstance(bbox, tuple) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox)
    except Exception:
        return None
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _compare_track_batches(
    primary: TrackBatch | None,
    shadow: TrackBatch | None,
    *,
    match_distance_px: float = 60.0,
) -> dict[str, Any] | None:
    if primary is None or shadow is None:
        return None
    primary_tracks = list(primary.tracks)
    shadow_tracks = list(shadow.tracks)
    primary_centers = [_track_center(track) for track in primary_tracks]
    shadow_centers = [_track_center(track) for track in shadow_tracks]
    matched_primary: set[int] = set()
    matched_shadow: set[int] = set()
    distances: list[float] = []

    pairs: list[tuple[float, int, int]] = []
    for pi, pc in enumerate(primary_centers):
        if pc is None:
            continue
        for si, sc in enumerate(shadow_centers):
            if sc is None:
                continue
            dist = math.hypot(pc[0] - sc[0], pc[1] - sc[1])
            if dist <= match_distance_px:
                pairs.append((dist, pi, si))
    for dist, pi, si in sorted(pairs):
        if pi in matched_primary or si in matched_shadow:
            continue
        matched_primary.add(pi)
        matched_shadow.add(si)
        distances.append(dist)

    avg_distance = round(sum(distances) / len(distances), 2) if distances else None
    return {
        "matched": len(distances),
        "primary_unmatched": max(0, len(primary_tracks) - len(matched_primary)),
        "shadow_unmatched": max(0, len(shadow_tracks) - len(matched_shadow)),
        "avg_center_distance_px": avg_distance,
    }


def _cosine_similarity(
    a: tuple[float, ...] | list[float] | None,
    b: tuple[float, ...] | list[float] | None,
) -> float | None:
    if a is None or b is None or len(a) != len(b) or not a:
        return None
    try:
        av = [float(v) for v in a]
        bv = [float(v) for v in b]
    except (TypeError, ValueError):
        return None
    dot = sum(x * y for x, y in zip(av, bv))
    na = sum(x * x for x in av)
    nb = sum(y * y for y in bv)
    if na <= 0.0 or nb <= 0.0:
        return None
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _track_distance_px(primary: Track, shadow: Track) -> float | None:
    if (
        primary.angle_rad is not None
        and shadow.angle_rad is not None
        and primary.radius_px is not None
        and shadow.radius_px is not None
    ):
        radius = max(1.0, (float(primary.radius_px) + float(shadow.radius_px)) / 2.0)
        arc = abs(
            (float(primary.angle_rad) - float(shadow.angle_rad) + math.pi)
            % (2.0 * math.pi)
            - math.pi
        ) * radius
        radial = abs(float(primary.radius_px) - float(shadow.radius_px))
        return math.hypot(arc, radial)
    pc = _track_center(primary)
    sc = _track_center(shadow)
    if pc is None or sc is None:
        return None
    return math.hypot(pc[0] - sc[0], pc[1] - sc[1])


def _enrich_tracks_with_shadow(
    primary: TrackBatch,
    shadow: TrackBatch | None,
    *,
    match_distance_px: float = 90.0,
) -> TrackBatch:
    """Copy ReID embeddings from the shadow tracker onto primary tracks."""

    if shadow is None or not shadow.tracks or not primary.tracks:
        return primary
    pairs: list[tuple[float, int, int]] = []
    for pi, primary_track in enumerate(primary.tracks):
        for si, shadow_track in enumerate(shadow.tracks):
            if shadow_track.appearance_embedding is None:
                continue
            distance = _track_distance_px(primary_track, shadow_track)
            if distance is None or distance > match_distance_px:
                continue
            pairs.append((distance, pi, si))

    matched_primary: set[int] = set()
    matched_shadow: set[int] = set()
    enriched = list(primary.tracks)
    for _distance, pi, si in sorted(pairs):
        if pi in matched_primary or si in matched_shadow:
            continue
        matched_primary.add(pi)
        matched_shadow.add(si)
        shadow_track = shadow.tracks[si]
        primary_track = enriched[pi]
        if (
            primary_track.appearance_embedding is not None
            and _cosine_similarity(
                primary_track.appearance_embedding,
                shadow_track.appearance_embedding,
            )
            is not None
        ):
            continue
        enriched[pi] = replace(
            primary_track,
            appearance_embedding=shadow_track.appearance_embedding,
        )

    if not matched_primary:
        return primary
    return TrackBatch(
        feed_id=primary.feed_id,
        frame_seq=primary.frame_seq,
        timestamp=primary.timestamp,
        tracks=tuple(enriched),
        lost_track_ids=primary.lost_track_ids,
    )


class PerceptionRunner:
    """Drives a PerceptionPipeline on its own daemon thread."""

    def __init__(
        self,
        pipeline: PerceptionPipeline,
        period_ms: int = 100,
        event_bus: EventBus | None = None,
        name: str | None = None,
        shadow_tracker: Tracker | None = None,
        shadow_tracker_key: str | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._period_s = max(0.0, float(period_ms) / 1000.0)
        self._bus = event_bus
        self._name = name or f"PerceptionRunner[{pipeline.feed.feed_id}]"
        self._tracker_key = str(getattr(pipeline.tracker, "key", None) or "unknown")
        self._tracker_epoch = new_tracker_epoch()
        self._shadow_tracker = shadow_tracker
        self._shadow_tracker_key = shadow_tracker_key or getattr(shadow_tracker, "key", None)
        self._stabilizer = TrackletStabilizer()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._latest_lock = threading.Lock()
        self._latest: TrackBatch | None = None
        self._latest_state: PerceptionFrameState | None = None
        self._latest_shadow: TrackBatch | None = None
        self._last_frame_seq: int | None = None
        self._consecutive_errors = 0
        self._running = False
        self._rotation_sub: Subscription | None = None

    # ---- Lifecycle ----------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._subscribe_rotation_windows()
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if not self._running:
            return
        self._running = False
        self._stop.set()
        self._unsubscribe_rotation_windows()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None

    # ---- Rotation-window subscription ---------------------------------

    def _subscribe_rotation_windows(self) -> None:
        if self._bus is None or self._rotation_sub is not None:
            return
        registrars = []
        for tracker in (getattr(self._pipeline, "tracker", None), self._shadow_tracker):
            register = getattr(tracker, "register_rotation_window", None)
            if callable(register):
                registrars.append(register)
        if not registrars:
            return
        feed_id = self._pipeline.feed.feed_id

        def _on_rotation(event: Event) -> None:
            payload = event.payload or {}
            if payload.get("feed_id") != feed_id:
                return
            try:
                start_ts = float(payload["start_ts"])
                end_ts = float(payload["end_ts"])
            except (KeyError, TypeError, ValueError):
                return
            for register in registrars:
                try:
                    register(start_ts, end_ts)
                except Exception:
                    _LOG.exception("rotation-window handler raised for feed=%s", feed_id)

        try:
            self._rotation_sub = self._bus.subscribe(PERCEPTION_ROTATION, _on_rotation)
        except Exception:
            _LOG.exception("rotation-window subscribe failed for feed=%s", feed_id)

    def _unsubscribe_rotation_windows(self) -> None:
        sub = self._rotation_sub
        self._rotation_sub = None
        if sub is None:
            return
        try:
            sub.unsubscribe()
        except Exception:
            _LOG.exception("rotation-window unsubscribe raised")

    # ---- Reader API ----------------------------------------------------

    @property
    def pipeline(self) -> PerceptionPipeline:
        """Public read-only view of the configured perception pipeline."""
        return self._pipeline

    def latest_tracks(self) -> TrackBatch | None:
        with self._latest_lock:
            return self._latest

    def latest_state(self) -> PerceptionFrameState | None:
        with self._latest_lock:
            return self._latest_state

    def latest_shadow_tracks(self) -> TrackBatch | None:
        with self._latest_lock:
            return self._latest_shadow

    def tracker_identity(self) -> dict[str, str]:
        return {
            "feed_id": str(getattr(self._pipeline.feed, "feed_id", "") or ""),
            "tracker_key": self._tracker_key,
            "tracker_epoch": self._tracker_epoch,
        }

    def start_detector_input_capture(
        self,
        *,
        max_frames: int = 300,
        sample_every_n: int = 1,
        label: str | None = None,
    ) -> dict[str, Any]:
        pipeline = self._pipeline
        current = getattr(pipeline, "detector_input_recorder", None)
        if current is not None and bool(getattr(current, "active", False)):
            raise RuntimeError("detector input capture is already active")
        recorder = DetectorInputRecorder(
            feed_id=str(getattr(pipeline.feed, "feed_id", "") or ""),
            detector_key=str(getattr(pipeline.detector, "key", "unknown")),
            tracker_key=self._tracker_key,
            zone=pipeline.zone,
            tracker=pipeline.tracker,
            max_frames=max_frames,
            sample_every_n=sample_every_n,
            label=label,
        )
        pipeline.detector_input_recorder = recorder
        return recorder.status()

    def stop_detector_input_capture(self) -> dict[str, Any] | None:
        recorder = getattr(self._pipeline, "detector_input_recorder", None)
        if recorder is None:
            return None
        status = recorder.stop()
        self._pipeline.detector_input_recorder = None
        return status

    def detector_input_capture_status(self) -> dict[str, Any] | None:
        recorder = getattr(self._pipeline, "detector_input_recorder", None)
        if recorder is None:
            return None
        status = recorder.status()
        if not bool(status.get("active")):
            self._pipeline.detector_input_recorder = None
        return status

    def status_snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        pipeline = self._pipeline
        feed = pipeline.feed
        zone = pipeline.zone
        detector = pipeline.detector
        tracker = pipeline.tracker

        zone_kind: str | None = None
        if zone is not None:
            zone_kind = type(zone).__name__.replace("Zone", "").lower() or None

        last_frame_age_ms: float | None = None
        try:
            frame = feed.latest()
        except Exception:
            frame = None
        if frame is not None:
            monotonic_ts = getattr(frame, "monotonic_ts", None)
            if isinstance(monotonic_ts, (int, float)):
                ts = time.monotonic() if now_mono is None else float(now_mono)
                last_frame_age_ms = max(0.0, (ts - float(monotonic_ts)) * 1000.0)

        with self._latest_lock:
            state = self._latest_state

        detection_count: int | None = None
        raw_track_count: int | None = None
        confirmed_track_count: int | None = None
        confirmed_real_track_count: int | None = None
        raw_track_preview: list[dict[str, Any]] = []
        confirmed_track_preview: list[dict[str, Any]] = []
        shadow_track_count: int | None = None
        shadow_confirmed_track_count: int | None = None
        shadow_track_preview: list[dict[str, Any]] = []
        shadow_compare: dict[str, Any] | None = None
        if state is not None:
            detections = getattr(state, "detections", None)
            detection_entries = (
                getattr(detections, "detections", None) if detections is not None else None
            )
            if isinstance(detection_entries, (list, tuple)):
                detection_count = len(detection_entries)
            raw_tracks = getattr(state, "raw_tracks", None)
            if raw_tracks is not None:
                raw_track_count = len(raw_tracks.tracks)
                raw_track_preview = _track_preview(raw_tracks)
            filtered_tracks = getattr(state, "filtered_tracks", None)
            if filtered_tracks is not None:
                confirmed_track_count = len(filtered_tracks.tracks)
                confirmed_real_track_count = sum(
                    1 for track in filtered_tracks.tracks
                    if bool(getattr(track, "confirmed_real", False))
                )
                confirmed_track_preview = _track_preview(filtered_tracks)
        with self._latest_lock:
            shadow_tracks = self._latest_shadow
        if shadow_tracks is not None:
            shadow_track_count = len(shadow_tracks.tracks)
            shadow_confirmed_track_count = sum(
                1 for track in shadow_tracks.tracks
                if bool(getattr(track, "confirmed_real", False))
            )
            shadow_track_preview = _track_preview(shadow_tracks)
            raw_tracks = getattr(state, "raw_tracks", None) if state is not None else None
            shadow_compare = _compare_track_batches(raw_tracks, shadow_tracks)

        # Instantaneous ring RPM from the tracker, if the pipeline has a
        # polar tracker with enough motion evidence to reason about it.
        observed_rpm: float | None = None
        tracker = getattr(self._pipeline, "tracker", None)
        rpm_fn = getattr(tracker, "observed_rpm", None) if tracker else None
        if callable(rpm_fn):
            try:
                observed_rpm = rpm_fn()
            except Exception:
                observed_rpm = None

        return {
            "feed_id": getattr(feed, "feed_id", None),
            "detector_slug": getattr(detector, "key", None),
            "tracker_slug": getattr(tracker, "key", None),
            "tracker_epoch": self._tracker_epoch,
            "zone_kind": zone_kind,
            "running": bool(self._running),
            "period_ms": int(round(self._period_s * 1000.0)),
            "last_frame_age_ms": last_frame_age_ms,
            "detection_count": detection_count,
            "raw_track_count": raw_track_count,
            "confirmed_track_count": confirmed_track_count,
            "confirmed_real_track_count": confirmed_real_track_count,
            "raw_track_preview": raw_track_preview,
            "confirmed_track_preview": confirmed_track_preview,
            "observed_rpm": observed_rpm,
            "shadow_tracker_slug": self._shadow_tracker_key,
            "shadow_track_count": shadow_track_count,
            "shadow_confirmed_track_count": shadow_confirmed_track_count,
            "shadow_track_preview": shadow_track_preview,
            "shadow_compare": shadow_compare,
            "track_stabilizer": self._stabilizer.snapshot(),
            "detector_input_capture": self.detector_input_capture_status(),
        }

    # ---- Internals -----------------------------------------------------

    def _run(self) -> None:
        feed = self._pipeline.feed
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                frame = feed.latest()
                if frame is not None and frame.frame_seq != self._last_frame_seq:
                    self._last_frame_seq = frame.frame_seq
                    state = self._pipeline.process_frame_state(frame)
                    shadow_batch = self._process_shadow_tracks(state, frame)
                    enriched_raw = _enrich_tracks_with_shadow(state.raw_tracks, shadow_batch)
                    enriched_filtered = _enrich_tracks_with_shadow(
                        state.filtered_tracks,
                        shadow_batch,
                    )
                    batch = self._stabilizer.update(enriched_filtered)
                    state = replace(
                        state,
                        raw_tracks=self._stabilizer.project(enriched_raw),
                        filtered_tracks=batch,
                    )
                    with self._latest_lock:
                        self._latest_state = state
                        self._latest = batch
                        self._latest_shadow = shadow_batch
                    self._publish_tracks(batch)
                    self._consecutive_errors = 0
            except Exception as exc:
                self._consecutive_errors += 1
                _LOG.exception(
                    "%s: pipeline tick raised (%d consecutive)",
                    self._name,
                    self._consecutive_errors,
                )
                if self._consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    self._emit_hardware_error(exc)
                    break

            elapsed = time.monotonic() - t0
            wait = self._period_s - elapsed
            if wait > 0:
                # Use stop.wait so stop() wakes us immediately.
                self._stop.wait(timeout=wait)

        self._running = False

    def _process_shadow_tracks(
        self,
        state: PerceptionFrameState,
        frame: Any,
    ) -> TrackBatch | None:
        tracker = self._shadow_tracker
        if tracker is None:
            return None
        try:
            return tracker.update(state.detections, frame)
        except Exception:
            _LOG.exception(
                "%s: shadow tracker tick raised (tracker=%s)",
                self._name,
                self._shadow_tracker_key,
            )
            return None

    def _publish_tracks(self, batch: TrackBatch) -> None:
        bus = self._bus
        if bus is None:
            return
        payload: dict[str, Any] = {
            "feed_id": batch.feed_id,
            "tracker_key": self._tracker_key,
            "tracker_epoch": self._tracker_epoch,
            "frame_seq": batch.frame_seq,
            "timestamp": batch.timestamp,
            "track_count": len(batch.tracks),
            "lost_track_ids": list(batch.lost_track_ids),
        }
        bus.publish(
            Event(
                topic=PERCEPTION_TRACKS,
                payload=payload,
                source=self._name,
                ts_mono=time.monotonic(),
            )
        )

    def _emit_hardware_error(self, exc: BaseException) -> None:
        bus = self._bus
        if bus is None:
            return
        bus.publish(
            Event(
                topic=HARDWARE_ERROR,
                payload={
                    "source": self._name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "consecutive_errors": self._consecutive_errors,
                },
                source=self._name,
                ts_mono=time.monotonic(),
            )
        )


__all__ = ["PerceptionRunner"]
