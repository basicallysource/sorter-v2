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
import threading
import time
from typing import Any

from rt.contracts.events import Event, EventBus
from rt.contracts.tracking import TrackBatch
from rt.events.topics import HARDWARE_ERROR, PERCEPTION_TRACKS

from .pipeline import PerceptionPipeline


_LOG = logging.getLogger(__name__)
_MAX_CONSECUTIVE_ERRORS = 10


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
        self._last_frame_seq: int | None = None
        self._consecutive_errors = 0
        self._running = False

    # ---- Lifecycle ----------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if not self._running:
            return
        self._running = False
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None

    # ---- Reader API ----------------------------------------------------

    def latest_tracks(self) -> TrackBatch | None:
        with self._latest_lock:
            return self._latest

    # ---- Internals -----------------------------------------------------

    def _run(self) -> None:
        feed = self._pipeline.feed
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                frame = feed.latest()
                if frame is not None and frame.frame_seq != self._last_frame_seq:
                    self._last_frame_seq = frame.frame_seq
                    batch = self._pipeline.process_frame(frame)
                    with self._latest_lock:
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
