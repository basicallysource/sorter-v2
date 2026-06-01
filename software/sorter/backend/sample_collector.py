from __future__ import annotations

import threading
import time
from typing import Any

import cv2

from blob_manager import BLOB_DIR, getSampleCollectionConfig, setSampleCollectionConfig
from global_config import GlobalConfig

SAMPLE_COLLECTION_ROOT = BLOB_DIR / "sample_collection"
DEFAULT_INTERVAL_S = 2.0
# Floor the interval so a bad rate value can't spin the loop into a busy save
# storm that fills the disk and pins a core.
MIN_INTERVAL_S = 0.1
# How often the loop wakes to notice an enable/disable flip while idle.
_IDLE_POLL_S = 0.25


class SampleCollector:
    """Standalone, mode-agnostic training-image grabber.

    A single background thread. When enabled it snapshots the latest raw
    frame from every live camera at a target cadence and writes JPEGs to
    disk. It is deliberately decoupled from the legacy gated teacher-capture
    pipeline (hive targets, detection scope, sample_collection_mode bypass):
    one toggle, one rate, runs no matter how the machine is otherwise
    configured.
    """

    def __init__(self, gc: GlobalConfig, camera_service: Any) -> None:
        self.gc = gc
        self._camera_service = camera_service
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

        self._enabled = False
        self._interval_s = DEFAULT_INTERVAL_S
        self._saved_count = 0
        self._last_saved_at: float | None = None
        self._last_error: str | None = None
        self._loadPersisted()

    def _loadPersisted(self) -> None:
        saved = getSampleCollectionConfig()
        if not isinstance(saved, dict):
            return
        self._enabled = bool(saved.get("enabled", False))
        interval = saved.get("interval_s")
        if isinstance(interval, (int, float)) and not isinstance(interval, bool) and interval > 0:
            self._interval_s = max(MIN_INTERVAL_S, float(interval))

    def _persist(self) -> None:
        setSampleCollectionConfig({"enabled": self._enabled, "interval_s": self._interval_s})

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="sample-collector"
            )
            self._thread.start()
        self.gc.logger.info(
            "SampleCollector started (enabled=%s interval=%.2fs)"
            % (self._enabled, self._interval_s)
        )

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None

    def setEnabled(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._enabled = bool(enabled)
            self._last_error = None
            self._persist()
        self._wake.set()
        self.gc.logger.info("SampleCollector enabled=%s" % self._enabled)
        return self.status()

    def setIntervalSeconds(self, interval_s: float) -> dict[str, Any]:
        with self._lock:
            self._interval_s = max(MIN_INTERVAL_S, float(interval_s))
            self._persist()
        self._wake.set()
        return self.status()

    def setRateHz(self, rate_hz: float) -> dict[str, Any]:
        if rate_hz <= 0:
            raise ValueError("rate_hz must be > 0")
        return self.setIntervalSeconds(1.0 / float(rate_hz))

    def status(self) -> dict[str, Any]:
        with self._lock:
            interval = self._interval_s
            last_saved_at = self._last_saved_at
            return {
                "ok": True,
                "enabled": self._enabled,
                "interval_s": interval,
                "rate_hz": (1.0 / interval) if interval > 0 else None,
                "saved_count": self._saved_count,
                "last_saved_at": last_saved_at,
                "last_saved_age_s": (time.time() - last_saved_at) if last_saved_at else None,
                "last_error": self._last_error,
                "output_dir": str(SAMPLE_COLLECTION_ROOT),
            }

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                enabled = self._enabled
                interval = self._interval_s
            if not enabled:
                self._wake.wait(timeout=_IDLE_POLL_S)
                self._wake.clear()
                continue
            try:
                self._captureOnce()
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                self.gc.logger.warning("SampleCollector capture failed: %s" % exc)
            self._wake.wait(timeout=max(MIN_INTERVAL_S, interval))
            self._wake.clear()

    def _captureOnce(self) -> None:
        if self._camera_service is None:
            return
        feeds = self._camera_service.feeds or {}
        now = time.time()
        local = time.localtime(now)
        day_dir = SAMPLE_COLLECTION_ROOT / time.strftime("%Y-%m-%d", local)
        stamp = "%s-%03d" % (time.strftime("%H-%M-%S", local), int((now % 1) * 1000))

        saved = 0
        for role in sorted(feeds.keys()):
            capture = self._camera_service.get_capture_thread_for_role(role)
            frame = getattr(capture, "latest_frame", None) if capture is not None else None
            raw = getattr(frame, "raw", None) if frame is not None else None
            if raw is None or getattr(raw, "size", 0) == 0:
                continue
            role_dir = day_dir / role
            role_dir.mkdir(parents=True, exist_ok=True)
            path = role_dir / ("%s.jpg" % stamp)
            if cv2.imwrite(str(path), raw):
                saved += 1

        with self._lock:
            self._saved_count += saved
            if saved > 0:
                self._last_saved_at = now
