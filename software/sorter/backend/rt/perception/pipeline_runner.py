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
from typing import Any

from rt.contracts.events import Event, EventBus, Subscription
from rt.contracts.tracking import TrackBatch
from rt.events.topics import HARDWARE_ERROR, PERCEPTION_ROTATION, PERCEPTION_TRACKS

from .pipeline import PerceptionFrameState, PerceptionPipeline


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
            "confirmed_real": bool(getattr(track, "confirmed_real", False)),
            "hit_count": getattr(track, "hit_count", None),
            "score": getattr(track, "score", None),
            "age_s": age_s,
            "angle_deg": angle_deg,
        })
    return out


class PerceptionRunner:
    """Drives a PerceptionPipeline on its own daemon thread."""

    def __init__(
        self,
        pipeline: PerceptionPipeline,
        period_ms: int = 100,
        event_bus: EventBus | None = None,
        name: str | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._period_s = max(0.0, float(period_ms) / 1000.0)
        self._bus = event_bus
        self._name = name or f"PerceptionRunner[{pipeline.feed.feed_id}]"
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._latest_lock = threading.Lock()
        self._latest: TrackBatch | None = None
        self._latest_state: PerceptionFrameState | None = None
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
        tracker = getattr(self._pipeline, "tracker", None)
        register = getattr(tracker, "register_rotation_window", None)
        if not callable(register):
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

    def latest_tracks(self) -> TrackBatch | None:
        with self._latest_lock:
            return self._latest

    def latest_state(self) -> PerceptionFrameState | None:
        with self._latest_lock:
            return self._latest_state

    def status_snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        pipeline = self._pipeline
        feed = pipeline.feed
        zone = pipeline.zone
        detector = pipeline.detector

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
        if state is not None:
            detections = getattr(state, "detections", None)
            detection_entries = getattr(detections, "detections", None) if detections is not None else None
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
                    batch = state.filtered_tracks
                    with self._latest_lock:
                        self._latest_state = state
                        self._latest = batch
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

    def _publish_tracks(self, batch: TrackBatch) -> None:
        bus = self._bus
        if bus is None:
            return
        payload: dict[str, Any] = {
            "feed_id": batch.feed_id,
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
