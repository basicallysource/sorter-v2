from __future__ import annotations

import random
import threading
import time
from typing import Any

import hive_limits
import sample_store
from global_config import GlobalConfig
from local_state import get_sample_collection_state, set_sample_collection_state
from sample_ingest import buildSample

DEFAULT_INTERVAL_S = 10.0
# Floor the interval so a bad rate value can't spin the loop into a busy save
# storm that pins a core. Hive's burst limit is the real floor (see _limits).
MIN_INTERVAL_S = 0.1
# How often the loop wakes to notice an enable/disable flip while idle.
_IDLE_POLL_S = 0.25

# Decay: a run's first samples come fast (burst), then the interval grows
# geometrically to a slow floor over the ramp so the same rig stops re-uploading
# near-identical frames forever. Jitter breaks the periodicity so we still
# occasionally catch a drift in conditions. Reset re-arms the burst. The burst,
# floor and ramp come from Hive's limits unless set here, and the burst can
# never be faster than Hive allows.
DEFAULT_DECAY_ENABLED = True
DEFAULT_JITTER_FRAC = 0.3  # ±30% random wobble on each interval

# Values the previous version of this file saved for every machine whether or
# not anyone set them. Read as "not set", so those machines follow Hive.
_OLD_SAVED_DEFAULTS = {"burst_interval_s": 10.0, "floor_interval_s": 3600.0, "ramp_hours": 72.0}


class SampleCollector:
    """Standalone, mode-agnostic training-image grabber.

    A single background thread. When enabled, and only while the machine is
    sorting, it takes the latest frame from every camera with a teacher zone at
    the schedule's cadence, builds a sample (sample_ingest) and hands it to
    sample_store, which keeps it on disk until the Hive sync worker uploads it.
    Independent of VisionManager: one toggle, one schedule, no matter how the
    machine is otherwise configured.
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
        self._annotate = True
        self._decay_enabled = DEFAULT_DECAY_ENABLED
        # Local settings; None follows Hive's limit.
        self._burst_interval_s: float | None = None
        self._floor_interval_s: float | None = None
        self._ramp_hours: float | None = None
        self._store_max_mb: float | None = None
        self._jitter_frac = DEFAULT_JITTER_FRAC
        # When the current decay started (persisted so decay spans restarts).
        # None until the first capture arms it; resetDecay() re-anchors to now.
        self._decay_anchor_ts: float | None = None
        self._saved_count = 0
        self._last_saved_at: float | None = None
        self._last_error: str | None = None
        self._loadPersisted()
        sample_store.configure(gc.logger, self._storeCapBytes())

    @staticmethod
    def _posFloat(value: Any) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
        return None

    def _storeCapBytes(self) -> int | None:
        return int(self._store_max_mb * 1024 * 1024) if self._store_max_mb else None

    @staticmethod
    def _limits() -> dict[str, float]:
        limits = hive_limits.machineLimits()
        return {
            "burst_interval_s": float(limits["sample_burst_interval_s"]),
            "floor_interval_s": float(limits["sample_floor_interval_s"]),
            "ramp_hours": float(limits["sample_ramp_hours"]),
        }

    def _scheduleLocked(self) -> dict[str, float]:
        """The schedule in force: local settings where set, Hive's limits
        otherwise, and never a burst faster than Hive's."""
        limits = self._limits()
        burst = max(self._burst_interval_s or limits["burst_interval_s"], limits["burst_interval_s"], MIN_INTERVAL_S)
        floor = max(self._floor_interval_s or limits["floor_interval_s"], burst)
        ramp = self._ramp_hours if self._ramp_hours is not None else limits["ramp_hours"]
        interval = max(self._interval_s, limits["burst_interval_s"], MIN_INTERVAL_S)
        return {"burst_interval_s": burst, "floor_interval_s": floor, "ramp_hours": ramp, "interval_s": interval}

    def _loadPersisted(self) -> None:
        saved = get_sample_collection_state()
        if not isinstance(saved, dict):
            return
        self._enabled = bool(saved.get("enabled", False))
        self._annotate = bool(saved.get("annotate", True))
        interval = saved.get("interval_s")
        if isinstance(interval, (int, float)) and not isinstance(interval, bool) and interval > 0:
            self._interval_s = max(MIN_INTERVAL_S, float(interval))
        self._decay_enabled = bool(saved.get("decay_enabled", DEFAULT_DECAY_ENABLED))
        for key in ("burst_interval_s", "floor_interval_s", "ramp_hours"):
            value = self._posFloat(saved.get(key))
            setattr(self, f"_{key}", None if value == _OLD_SAVED_DEFAULTS[key] else value)
        self._store_max_mb = self._posFloat(saved.get("store_max_mb"))
        jitter = saved.get("jitter_frac")
        if isinstance(jitter, (int, float)) and not isinstance(jitter, bool) and 0 <= jitter <= 1:
            self._jitter_frac = float(jitter)
        anchor = saved.get("decay_anchor_ts")
        if isinstance(anchor, (int, float)) and not isinstance(anchor, bool) and anchor > 0:
            self._decay_anchor_ts = float(anchor)

    def _persist(self) -> None:
        set_sample_collection_state(
            {
                "enabled": self._enabled,
                "interval_s": self._interval_s,
                "annotate": self._annotate,
                "decay_enabled": self._decay_enabled,
                "burst_interval_s": self._burst_interval_s,
                "floor_interval_s": self._floor_interval_s,
                "ramp_hours": self._ramp_hours,
                "store_max_mb": self._store_max_mb,
                "jitter_frac": self._jitter_frac,
                "decay_anchor_ts": self._decay_anchor_ts,
            }
        )

    def _baseIntervalLocked(self, now: float) -> float:
        # The interval BEFORE jitter, so status() can report a stable curve
        # value. Geometric growth from burst -> floor across the ramp.
        schedule = self._scheduleLocked()
        if not self._decay_enabled:
            return schedule["interval_s"]
        anchor = self._decay_anchor_ts if self._decay_anchor_ts is not None else now
        ramp_s = max(1.0, schedule["ramp_hours"] * 3600.0)
        frac = min(1.0, max(0.0, (now - anchor) / ramp_s))
        burst = schedule["burst_interval_s"]
        return burst * (schedule["floor_interval_s"] / burst) ** frac

    def _nextWaitLocked(self, now: float) -> float:
        base = self._baseIntervalLocked(now)
        if self._decay_enabled and self._jitter_frac > 0:
            base *= 1.0 + self._jitter_frac * (2.0 * random.random() - 1.0)
        return max(MIN_INTERVAL_S, base)

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
            "SampleCollector started (enabled=%s interval=%.2fs annotate=%s)"
            % (self._enabled, self._interval_s, self._annotate)
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

    def setAnnotate(self, annotate: bool) -> dict[str, Any]:
        with self._lock:
            self._annotate = bool(annotate)
            self._persist()
        self.gc.logger.info("SampleCollector annotate=%s" % self._annotate)
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

    _UNSET: Any = object()

    def setDecayConfig(
        self,
        *,
        decay_enabled: bool | None = None,
        burst_interval_s: Any = _UNSET,
        floor_interval_s: Any = _UNSET,
        ramp_hours: Any = _UNSET,
        jitter_frac: float | None = None,
    ) -> dict[str, Any]:
        """Each of burst, floor and ramp: a positive number sets it here; None
        (or 0) clears it so Hive's limit applies; left out, unchanged."""
        with self._lock:
            if decay_enabled is not None:
                self._decay_enabled = bool(decay_enabled)
            if burst_interval_s is not self._UNSET:
                self._burst_interval_s = self._posFloat(burst_interval_s)
            if floor_interval_s is not self._UNSET:
                self._floor_interval_s = self._posFloat(floor_interval_s)
            if ramp_hours is not self._UNSET:
                self._ramp_hours = self._posFloat(ramp_hours)
            if jitter_frac is not None:
                self._jitter_frac = min(1.0, max(0.0, float(jitter_frac)))
            self._persist()
        self._wake.set()
        return self.status()

    def setStoreMaxMb(self, store_max_mb: float | None) -> dict[str, Any]:
        """A local cap on the sample store under Hive's; None or 0 clears it."""
        with self._lock:
            self._store_max_mb = self._posFloat(store_max_mb)
            self._persist()
        sample_store.setLocalCapBytes(self._storeCapBytes())
        return self.status()

    def resetDecay(self) -> dict[str, Any]:
        # Re-arm the burst: capture fast again, then decay from now.
        with self._lock:
            self._decay_anchor_ts = time.time()
            self._persist()
        self._wake.set()
        self.gc.logger.info("SampleCollector decay reset")
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            schedule = self._scheduleLocked()
            interval = schedule["interval_s"]
            last_saved_at = self._last_saved_at
            base_interval = self._baseIntervalLocked(now)
            elapsed = (now - self._decay_anchor_ts) if self._decay_anchor_ts is not None else None
            return {
                "ok": True,
                "enabled": self._enabled,
                "annotate": self._annotate,
                "interval_s": interval,
                "rate_hz": (1.0 / interval) if interval > 0 else None,
                "decay_enabled": self._decay_enabled,
                # In force (local where set, else Hive), then what is set here
                # (None = following Hive) and Hive's limits themselves.
                "burst_interval_s": schedule["burst_interval_s"],
                "floor_interval_s": schedule["floor_interval_s"],
                "ramp_hours": schedule["ramp_hours"],
                "local_settings": {
                    "burst_interval_s": self._burst_interval_s,
                    "floor_interval_s": self._floor_interval_s,
                    "ramp_hours": self._ramp_hours,
                    "store_max_mb": self._store_max_mb,
                },
                "hive_limits": hive_limits.machineLimits(),
                "store": sample_store.stats(),
                "jitter_frac": self._jitter_frac,
                "decay_anchor_ts": self._decay_anchor_ts,
                "decay_elapsed_s": elapsed,
                # The current interval on the decay curve (pre-jitter) so the UI
                # can plot "you are here" and the effective rate right now.
                "current_interval_s": base_interval,
                "current_rate_per_min": (60.0 / base_interval) if base_interval > 0 else None,
                "saved_count": self._saved_count,
                "last_saved_at": last_saved_at,
                "last_saved_age_s": (now - last_saved_at) if last_saved_at else None,
                "last_error": self._last_error,
            }

    def _isSorting(self) -> bool:
        # Only collect while the machine is actively sorting (RUNNING). Paused,
        # ready, or standby means pieces aren't flowing, so capturing would just
        # save endless duplicate frames of an empty channel around the clock.
        try:
            from server import shared_state
            from defs.sorter_controller import SorterLifecycle

            controller = shared_state.controller_ref
            if controller is None:
                return False
            return controller.state == SorterLifecycle.RUNNING
        except Exception:
            return False

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                enabled = self._enabled
            if not enabled or not self._isSorting():
                self._wake.wait(timeout=_IDLE_POLL_S)
                self._wake.clear()
                continue
            with self._lock:
                # Arm the decay clock on the first capture so the burst starts
                # when sampling actually begins, not at boot.
                if self._decay_enabled and self._decay_anchor_ts is None:
                    self._decay_anchor_ts = time.time()
                    self._persist()
            try:
                self._captureOnce()
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                self.gc.logger.warning("SampleCollector capture failed: %s" % exc)
            with self._lock:
                wait_s = self._nextWaitLocked(time.time())
            self._wake.wait(timeout=wait_s)
            self._wake.clear()

    def _captureOnce(self) -> None:
        if self._camera_service is None:
            return
        feeds = self._camera_service.feeds or {}
        with self._lock:
            annotate = self._annotate
        now = time.time()
        saved = 0
        last_error: str | None = None
        for role in sorted(feeds.keys()):
            capture = self._camera_service.get_capture_thread_for_role(role)
            frame = getattr(capture, "latest_frame", None) if capture is not None else None
            if frame is None:
                continue
            try:
                sample = buildSample(self.gc, role, capture, frame, annotate=annotate)
                if sample is not None and sample_store.enqueue(*sample):
                    saved += 1
            except Exception as exc:
                last_error = str(exc)
                self.gc.logger.warning("SampleCollector capture failed for %s: %s" % (role, exc))

        with self._lock:
            self._saved_count += saved
            if saved > 0:
                self._last_saved_at = now
            if last_error is not None:
                self._last_error = last_error
