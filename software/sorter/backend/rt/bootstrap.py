"""RT runtime bootstrap — wiring for `RT_RUNTIME=1`.

Builds the full 5-runtime graph (C1 -> C2 -> C3 -> C4 -> Distributor) with
perception runners, capacity slots, classifier, rules engine, event bus,
and hardware-facing callables that bridge into the legacy ``irl.*`` stack.

This module is the **single** place that reaches into the legacy hardware
API from the rt/ tree; every other rt/ file stays bridge-free. Bridge
imports here are kept local to the builder functions and marked clearly.

Call :func:`build_rt_runtime` once after the legacy ``CameraService`` is
running to get an :class:`RtRuntimeHandle` with ``.start()``/``.stop()``
lifecycle. The caller may start it paused while hardware is still in
standby, then rebuild or resume it after homing.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import rt.perception  # noqa: F401 - register detectors/trackers/filters
import rt.rules  # noqa: F401 - register rules engines
from rt.classification.brickognize import BrickognizeClient
from rt.contracts.feed import FeedFrame, PolarZone, PolygonZone, RectZone, Zone
from rt.contracts.registry import (
    CLASSIFIERS,
    RULES_ENGINES,
)
from rt.contracts.tracking import Track
from rt.coupling.orchestrator import Orchestrator
from rt.coupling.slots import CapacitySlot
from rt.events.bus import InProcessEventBus
from rt.hardware.channel_callables import (
    build_c1_callables,
    build_c2_callables,
    build_c3_callables,
    build_c4_callables,
    build_chute_callables,
)
from rt.hardware.motion_profiles import MotionDiagnostics
from rt.perception.pipeline_runner import PerceptionRunner
from rt.perception.runner_builder import build_perception_runner_for_role
from rt.perception.teacher_samples import AuxiliaryTeacherSampleCollector
from rt.perception.track_policy import action_track
from rt.runtimes._strategies import (
    AlwaysAdmit,
    C4Admission,
    C4EjectionTiming,
    C4StartupPurgeStrategy,
    ConstantPulseEjection,
)
from rt.runtimes._zones import ZoneManager
from rt.runtimes.c1 import (
    DEFAULT_JAM_COOLDOWN_S,
    DEFAULT_JAM_MIN_PULSES,
    DEFAULT_JAM_TIMEOUT_S,
    DEFAULT_MAX_RECOVERY_CYCLES,
    DEFAULT_OBSERVATION_HOLD_S,
    DEFAULT_PULSE_COOLDOWN_S,
    DEFAULT_STARTUP_HOLD_S,
    DEFAULT_UNCONFIRMED_PULSE_LIMIT,
    RuntimeC1,
)
from rt.runtimes.c2 import RuntimeC2
from rt.runtimes.c3 import RuntimeC3
from rt.runtimes.c4 import RuntimeC4
from rt.runtimes.distributor import RuntimeDistributor
from rt.services.c1_pulse_observation import C1PulseObserver
from rt.services.maintenance_purge import C234PurgeCoordinator
from rt.services.sample_transport import C1234SampleTransportCoordinator
from rt.services.sector_carousel.wiring import install_sector_carousel_handler
from rt.services.track_transit import TrackTransitRegistry


@dataclass(frozen=True, slots=True)
class FeedAnnotationSnapshot:
    """Runtime-owned read model for camera overlays and live inspection."""

    feed_id: str
    zone: Zone | None
    tracker_key: str | None = None
    tracker_epoch: str | None = None
    tracks: tuple[Track, ...] = ()
    shadow_tracks: tuple[Track, ...] = ()


@dataclass(frozen=True, slots=True)
class SlotWedgeSnapshot:
    """One angular slot on a camera ring — a piece or reservation range."""

    start_angle_deg: float
    end_angle_deg: float
    label: str | None = None
    color: str | None = None


@dataclass(frozen=True, slots=True)
class FeedSlotSnapshot:
    """Ring geometry + slot wedges for a camera's live-overlay layer."""

    feed_id: str
    center_x: float
    center_y: float
    inner_radius: float
    outer_radius: float
    wedges: tuple[SlotWedgeSnapshot, ...] = ()


@dataclass
class RtRuntimeHandle:
    """Lifecycle handle returned by :func:`build_rt_runtime`.

    ``start()`` must be called after construction; ``stop()`` is idempotent
    and safe to call from a KeyboardInterrupt handler. ``pause()``/``resume()``
    are thin facades over the orchestrator so main.py + UI can drive the
    runtime without reaching into internals.
    """

    orchestrator: Orchestrator
    perception_runners: list[PerceptionRunner]
    event_bus: InProcessEventBus
    c4: RuntimeC4
    distributor: RuntimeDistributor
    c1: RuntimeC1 | None = None
    c2: RuntimeC2 | None = None
    c3: RuntimeC3 | None = None
    feed_zones: dict[str, Zone] = field(default_factory=dict)
    started: bool = False
    perception_started: bool = False
    paused: bool = False
    # (role, reason) entries populated at bootstrap when a perception runner
    # could not be built. Observable via /api/rt/status; never fatal.
    skipped_roles: list[dict[str, str]] = field(default_factory=list)
    sample_collector: AuxiliaryTeacherSampleCollector | None = None
    segment_recorder: Any | None = None
    irl: Any | None = None
    # Back-reference needed for runner rebuilds after config changes.
    camera_service: Any | None = None
    _rebuild_lock: threading.Lock = field(default_factory=threading.Lock)
    _purge_coordinator: C234PurgeCoordinator = field(
        default_factory=C234PurgeCoordinator
    )
    _sample_transport_coordinator: C1234SampleTransportCoordinator = field(
        default_factory=C1234SampleTransportCoordinator
    )
    motion_diagnostics: MotionDiagnostics | None = None

    def start_perception(self) -> None:
        if self.perception_started:
            return
        self.event_bus.start()
        for runner in self.perception_runners:
            runner.start()
        if self.sample_collector is not None:
            try:
                self.sample_collector.start()
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: sample collector start raised"
                )
        self.perception_started = True

    def start(self, *, paused: bool = False) -> None:
        if self.started:
            return
        try:
            from local_state import mark_active_piece_dossiers_stale

            marked = mark_active_piece_dossiers_stale(reason="rt_runtime_start")
            if marked:
                logging.getLogger("rt.bootstrap").info(
                    "RtRuntimeHandle: marked %d stale active piece dossier(s)",
                    marked,
                )
        except Exception:
            logging.getLogger("rt.bootstrap").exception(
                "RtRuntimeHandle: stale dossier cleanup raised"
            )
        c4 = getattr(self, "c4", None)
        arm_startup_purge = getattr(c4, "arm_startup_purge", None)
        if callable(arm_startup_purge):
            try:
                arm_startup_purge()
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: c4.arm_startup_purge raised"
                )
        self.start_perception()
        self.orchestrator.start(paused=paused)
        self.started = True
        self.paused = bool(paused)

    def stop(self) -> None:
        if not self.started and not self.perception_started:
            return
        self._purge_coordinator.request_cancel()
        self._sample_transport_coordinator.request_cancel()
        if self.started:
            try:
                self.orchestrator.stop()
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: orchestrator stop raised"
                )
        if self.sample_collector is not None:
            try:
                self.sample_collector.stop(timeout=1.0)
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: sample collector stop raised"
                )
        for runner in self.perception_runners:
            try:
                runner.stop(timeout=1.0)
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: perception runner stop raised"
                )
        close_recorder = getattr(self.segment_recorder, "close", None)
        if callable(close_recorder):
            try:
                close_recorder()
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: segment recorder close raised"
                )
            self.segment_recorder = None
        try:
            self.event_bus.stop()
        except Exception:
            logging.getLogger("rt.bootstrap").exception(
                "RtRuntimeHandle: event bus stop raised"
            )
        self.started = False
        self.perception_started = False
        self.paused = False

    def pause(self) -> None:
        """Halt tick propagation without stopping perception runners.

        Orchestrator exposes ``pause()`` if present; otherwise this just
        flips a flag that main.py / UI can read.
        """
        fn = getattr(self.orchestrator, "pause", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: orchestrator.pause raised"
                )
        self.paused = True

    def resume(self) -> None:
        c1 = getattr(self, "c1", None)
        arm_startup_hold = getattr(c1, "arm_startup_hold", None)
        if callable(arm_startup_hold):
            try:
                arm_startup_hold()
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: c1.arm_startup_hold raised"
                )
        fn = getattr(self.orchestrator, "resume", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: orchestrator.resume raised"
                )
        self.paused = False

    def step(self, n: int = 1) -> dict[str, Any]:
        """Step the runtime forward by ``n`` ticks while paused.

        Thin facade so the API layer can drive the orchestrator without
        reaching into ``self.orchestrator`` directly.
        """
        fn = getattr(self.orchestrator, "step", None)
        if not callable(fn):
            raise RuntimeError("orchestrator does not support step()")
        return dict(fn(n) or {})

    def inspect_snapshot(self) -> dict[str, Any]:
        fn = getattr(self.orchestrator, "inspect_snapshot", None)
        if not callable(fn):
            return self.status_snapshot()
        return dict(fn() or {})

    def status_snapshot(self) -> dict[str, Any]:
        runners_out: list[dict[str, Any]] = []
        for runner in self.perception_runners:
            try:
                runners_out.append(runner.status_snapshot())
            except Exception:
                runners_out.append({
                    "feed_id": None,
                    "detector_slug": None,
                    "zone_kind": None,
                    "running": False,
                    "last_frame_age_ms": None,
                    "detection_count": None,
                    "raw_track_count": None,
                    "confirmed_track_count": None,
                    "confirmed_real_track_count": None,
                    "raw_track_preview": [],
                    "confirmed_track_preview": [],
                })

        runtime_health: dict[str, Any] = {}
        runtime_debug: dict[str, Any] = {}
        slot_debug: dict[str, Any] = {}
        capacity_debug: dict[str, Any] = {}
        flow_gate_accounting: dict[str, Any] = {}
        c1_pulse_observer: dict[str, Any] | None = None
        sector_carousel_handler_snap: dict[str, Any] | None = None
        c4_mode: str = "runtime"
        orchestrator_status = getattr(self.orchestrator, "status_snapshot", None)
        if callable(orchestrator_status):
            try:
                snapshot = dict(orchestrator_status() or {})
            except Exception:
                snapshot = {}
            runtime_health = dict(snapshot.get("runtime_health") or {})
            runtime_debug = dict(snapshot.get("runtime_debug") or {})
            slot_debug = dict(snapshot.get("slot_debug") or {})
            capacity_debug = dict(snapshot.get("capacity_debug") or {})
            flow_gate_accounting = dict(snapshot.get("flow_gate_accounting") or {})
            obs = snapshot.get("c1_pulse_observer")
            if isinstance(obs, dict):
                c1_pulse_observer = dict(obs)
            sector_carousel = snapshot.get("sector_carousel_handler")
            if isinstance(sector_carousel, dict):
                sector_carousel_handler_snap = dict(sector_carousel)
            else:
                sector_carousel_handler_snap = None
            c4_mode_val = snapshot.get("c4_mode")
            c4_mode = c4_mode_val if isinstance(c4_mode_val, str) else "runtime"

        return {
            "perception_started": bool(self.perception_started),
            "started": bool(self.started),
            "paused": bool(self.paused),
            "runners": runners_out,
            "skipped_roles": list(self.skipped_roles),
            "sample_collection": (
                self.sample_collector.status_snapshot()
                if self.sample_collector is not None
                else {"installed": False}
            ),
            "runtime_health": runtime_health,
            "runtime_debug": runtime_debug,
            "slot_debug": slot_debug,
            "capacity_debug": capacity_debug,
            "flow_gate_accounting": flow_gate_accounting,
            "c1_pulse_observer": c1_pulse_observer,
            "c4_mode": c4_mode,
            "sector_carousel_handler": sector_carousel_handler_snap,
            "maintenance": {
                "c234_purge": self.c234_purge_status(),
                "sample_transport": self.sample_transport_status(),
            },
            "motion": (
                self.motion_diagnostics.status_snapshot()
                if self.motion_diagnostics is not None
                else {}
            ),
        }

    def runtime_tuning_status(self) -> dict[str, Any]:
        from rt.services.runtime_tuning import snapshot as tuning_snapshot

        return tuning_snapshot(self)

    def update_runtime_tuning(self, patch: dict[str, Any]) -> dict[str, Any]:
        from rt.services.runtime_tuning import apply_patch as apply_tuning_patch

        return apply_tuning_patch(self, patch)

    def annotation_snapshot(self, feed_id: str) -> FeedAnnotationSnapshot:
        """Return a compact overlay/debug snapshot for one perception feed."""
        zone = self.feed_zones.get(feed_id)
        if not isinstance(zone, (RectZone, PolygonZone, PolarZone)):
            zone = None

        tracks: tuple[Track, ...] = ()
        shadow_tracks: tuple[Track, ...] = ()
        tracker_key: str | None = None
        tracker_epoch: str | None = None
        runner = self.runner_for_feed(feed_id)
        if runner is not None:
            identity_fn = getattr(runner, "tracker_identity", None)
            identity = identity_fn() if callable(identity_fn) else {}
            tracker_key = identity.get("tracker_key")
            tracker_epoch = identity.get("tracker_epoch")
            latest_tracks = getattr(runner, "latest_tracks", None)
            batch = latest_tracks() if callable(latest_tracks) else None
            batch_tracks = getattr(batch, "tracks", None)
            if isinstance(batch_tracks, tuple):
                tracks = batch_tracks
            latest_state = getattr(runner, "latest_state", None)
            state = latest_state() if callable(latest_state) else None
            raw_tracks = getattr(state, "raw_tracks", None)
            raw_track_items = getattr(raw_tracks, "tracks", None)
            if not tracks and isinstance(raw_track_items, tuple):
                tracks = raw_track_items
            latest_shadow_tracks = getattr(runner, "latest_shadow_tracks", None)
            shadow_batch = (
                latest_shadow_tracks() if callable(latest_shadow_tracks) else None
            )
            batch_shadow_tracks = getattr(shadow_batch, "tracks", None)
            if isinstance(batch_shadow_tracks, tuple):
                shadow_tracks = batch_shadow_tracks

        return FeedAnnotationSnapshot(
            feed_id=feed_id,
            zone=zone,
            tracker_key=tracker_key,
            tracker_epoch=tracker_epoch,
            tracks=tracks,
            shadow_tracks=shadow_tracks,
        )

    def slot_snapshot(self, feed_id: str) -> FeedSlotSnapshot | None:
        """Return ring geometry + occupied slot wedges for this feed.

        Used by the per-camera "slots" overlay layer: the dashboard draws
        wedges on top of the live stream so operators can see which
        angular sectors are reserved by the runtime.

        Returns ``None`` for feeds that don't live on an arc channel or
        whose tracker has no configured polar geometry.
        """
        runner = self.runner_for_feed(feed_id)
        if runner is None:
            return None
        tracker = getattr(getattr(runner, "_pipeline", None), "tracker", None)
        ring_fn = getattr(tracker, "ring_geometry", None) if tracker else None
        geom = ring_fn() if callable(ring_fn) else None
        if not geom:
            return None

        wedges: list[SlotWedgeSnapshot] = []
        if feed_id == "c4_feed":
            # C4: one wedge per occupied dossier zone on the carousel.
            c4 = getattr(self, "c4", None)
            zone_mgr = getattr(c4, "_zone_manager", None) if c4 else None
            zones_fn = getattr(zone_mgr, "zones", None) if zone_mgr else None
            zones = zones_fn() if callable(zones_fn) else ()
            for zone in zones:
                center = float(getattr(zone, "center_deg", 0.0))
                half = float(getattr(zone, "half_width_deg", 0.0))
                wedges.append(
                    SlotWedgeSnapshot(
                        start_angle_deg=center - half,
                        end_angle_deg=center + half,
                        label=getattr(zone, "piece_uuid", None),
                    )
                )
        else:
            # C2 / C3: synthesize a wedge around every actionable track.
            latest_tracks_fn = getattr(runner, "latest_tracks", None)
            batch = latest_tracks_fn() if callable(latest_tracks_fn) else None
            tracks = getattr(batch, "tracks", ()) if batch is not None else ()
            for track in tracks:
                if not action_track(track, min_hits=2):
                    continue
                angle_rad = getattr(track, "angle_rad", None)
                if not isinstance(angle_rad, (int, float)):
                    continue
                center_deg = math.degrees(float(angle_rad))
                half = 10.0  # fixed visual half-width for point-like pieces
                wedges.append(
                    SlotWedgeSnapshot(
                        start_angle_deg=center_deg - half,
                        end_angle_deg=center_deg + half,
                    )
                )

        return FeedSlotSnapshot(
            feed_id=feed_id,
            center_x=float(geom["center_x"]),
            center_y=float(geom["center_y"]),
            inner_radius=float(geom["inner_radius"]),
            outer_radius=float(geom["outer_radius"]),
            wedges=tuple(wedges),
        )

    def c234_purge_status(self) -> dict[str, Any]:
        return self._purge_coordinator.status()

    def start_c234_purge(
        self,
        *,
        state_publisher: Callable[[str], None] | None = None,
        channels: list[str] | None = None,
        timeout_s: float = 120.0,
        clear_hold_s: float = 0.75,
        poll_s: float = 0.05,
    ) -> bool:
        if not self.started:
            raise RuntimeError("rt runtime is not started")
        return self._purge_coordinator.start(
            runtimes=(self.c2, self.c3, self.c4),
            control=self,
            maintenance_pauses=(self.c1,),
            state_publisher=state_publisher,
            channels=channels,
            timeout_s=timeout_s,
            clear_hold_s=clear_hold_s,
            poll_s=poll_s,
        )

    def cancel_c234_purge(self) -> bool:
        return self._purge_coordinator.cancel()

    def sample_transport_status(self) -> dict[str, Any]:
        return self._sample_transport_coordinator.status()

    def start_sample_transport(
        self,
        *,
        state_publisher: Callable[[str], None] | None = None,
        base_interval_s: float = 2.0,
        ratio: float = 2.0,
        channel_rpm: dict[str, float] | None = None,
        channels: list[str] | None = None,
        direct_max_speed_usteps_per_s: int | None = None,
        direct_acceleration_usteps_per_s2: int | None = None,
        duration_s: float | None = 600.0,
        poll_s: float = 0.02,
    ) -> bool:
        if not self.started:
            raise RuntimeError("rt runtime is not started")
        return self._sample_transport_coordinator.start(
            runtimes=(self.c1, self.c2, self.c3, self.c4),
            control=self,
            state_publisher=state_publisher,
            base_interval_s=base_interval_s,
            ratio=ratio,
            channel_rpm=channel_rpm,
            channels=channels,
            direct_max_speed_usteps_per_s=direct_max_speed_usteps_per_s,
            direct_acceleration_usteps_per_s2=direct_acceleration_usteps_per_s2,
            duration_s=duration_s,
            poll_s=poll_s,
        )

    def cancel_sample_transport(self) -> bool:
        return self._sample_transport_coordinator.cancel()

    def update_sample_transport(
        self,
        *,
        base_interval_s: float | None = None,
        ratio: float | None = None,
        channel_rpm: dict[str, float] | None = None,
        direct_max_speed_usteps_per_s: int | None = None,
        direct_acceleration_usteps_per_s2: int | None = None,
        poll_s: float | None = None,
    ) -> bool:
        return self._sample_transport_coordinator.update_config(
            base_interval_s=base_interval_s,
            ratio=ratio,
            channel_rpm=channel_rpm,
            direct_max_speed_usteps_per_s=direct_max_speed_usteps_per_s,
            direct_acceleration_usteps_per_s2=direct_acceleration_usteps_per_s2,
            poll_s=poll_s,
        )

    def clear_c1_pause(self) -> dict[str, Any]:
        c1 = self.c1
        if c1 is None:
            raise RuntimeError("c1 runtime is not available")
        is_paused_fn = getattr(c1, "is_paused", None)
        was_paused = bool(is_paused_fn()) if callable(is_paused_fn) else False
        clear_fn = getattr(c1, "clear_pause", None)
        if not callable(clear_fn):
            raise NotImplementedError("c1 pause clearing is not supported")
        clear_fn()
        return {"cleared": was_paused, "was_paused": was_paused}

    def runner_for_feed(self, feed_id: str) -> PerceptionRunner | None:
        """Return the PerceptionRunner driving ``feed_id`` if registered."""
        for runner in self.perception_runners:
            pipeline = getattr(runner, "_pipeline", None)
            if pipeline is None:
                pipeline = getattr(runner, "pipeline", None)
            if pipeline is None:
                continue
            feed = getattr(pipeline, "feed", None)
            if feed is not None and getattr(feed, "feed_id", None) == feed_id:
                return runner
        return None

    def latest_frame_for_feed(self, feed_id: str) -> FeedFrame | None:
        """Return the latest raw feed frame without exposing runner internals."""
        runner = self.runner_for_feed(feed_id)
        if runner is None:
            return None
        latest_frame = getattr(runner, "latest_frame", None)
        if callable(latest_frame):
            return latest_frame()
        pipeline = getattr(runner, "pipeline", None)
        feed = getattr(pipeline, "feed", None) if pipeline is not None else None
        latest = getattr(feed, "latest", None)
        return latest() if callable(latest) else None

    def sector_carousel_handler(self) -> Any | None:
        """Return the C4 sector-carousel handler through the orchestration boundary."""
        accessor = getattr(self.orchestrator, "sector_carousel_handler", None)
        return accessor() if callable(accessor) else None

    def rebuild_runner_for_role(
        self,
        role: str,
        *,
        logger: logging.Logger | None = None,
    ) -> PerceptionRunner | None:
        """Rebuild (or build-if-missing) the perception runner for ``role``.

        Used when the user changes the detector dropdown for a channel: the
        runner is torn down and replaced in-place so the freshly-configured
        detector starts running continuously, not just on API requests.

        Returns the new runner on success, ``None`` if the zone or camera
        is still unavailable. Orchestrator state is preserved.
        """
        log = logger or logging.getLogger("rt.bootstrap")
        if self.camera_service is None:
            log.warning(
                "rt.bootstrap.rebuild[%s]: no camera_service on handle",
                role,
            )
            return None
        with self._rebuild_lock:
            feed_id = f"{role}_feed"
            # Stop + drop any existing runner for this role.
            existing = self.runner_for_feed(feed_id)
            if existing is not None:
                try:
                    existing.stop(timeout=1.0)
                except Exception:
                    log.exception(
                        "rt.bootstrap.rebuild[%s]: stop existing runner raised",
                        role,
                    )
                self.perception_runners = [
                    r for r in self.perception_runners if r is not existing
                ]
            # Remove any prior "skipped" entry; we're retrying now.
            self.skipped_roles = [
                entry for entry in self.skipped_roles if entry.get("role") != role
            ]
            # Build fresh.
            runner, zone, reason = build_perception_runner_for_role(
                role,
                camera_service=self.camera_service,
                event_bus=self.event_bus,
                logger=log,
            )
            if runner is None:
                self.skipped_roles.append({"role": role, "reason": reason or "build_failed"})
                # Ensure any lingering zone entry is cleared.
                self.feed_zones.pop(feed_id, None)
                return None
            if role == "c4":
                old_recorder = self.segment_recorder
                close_recorder = getattr(old_recorder, "close", None)
                if callable(close_recorder):
                    try:
                        close_recorder()
                    except Exception:
                        log.exception(
                            "rt.bootstrap.rebuild[%s]: segment_recorder.close raised",
                            role,
                        )
                try:
                    from rt.perception.segment_recorder import install as install_segment_recording

                    self.segment_recorder = install_segment_recording(self.event_bus, runner)
                except Exception:
                    self.segment_recorder = None
                    log.exception(
                        "rt.bootstrap.rebuild[%s]: segment recorder install failed",
                        role,
                    )
            # Install and (if the runtime is live) start it so perception is
            # continuous, not on-demand.
            self.perception_runners.append(runner)
            if zone is not None:
                self.feed_zones[feed_id] = zone
            if self.perception_started:
                try:
                    runner.start()
                except Exception:
                    log.exception(
                        "rt.bootstrap.rebuild[%s]: runner.start raised",
                        role,
                    )
            # Re-register as a perception source on the orchestrator so
            # downstream consumers see the new tracks.
            try:
                self.orchestrator.register_perception_source(feed_id, runner)
            except Exception:
                # Non-fatal: some orchestrator implementations ignore live
                # re-registration (tests use stubs without this method).
                log.debug(
                    "rt.bootstrap.rebuild[%s]: orchestrator.register_perception_source unavailable",
                    role,
                    exc_info=True,
                )
            if role == "c4":
                identity_fn = getattr(runner, "tracker_identity", None)
                identity = identity_fn() if callable(identity_fn) else {}
                set_identity = getattr(self.c4, "set_tracker_identity", None)
                if callable(set_identity):
                    try:
                        set_identity(
                            tracker_key=identity.get("tracker_key"),
                            tracker_epoch=identity.get("tracker_epoch"),
                        )
                    except Exception:
                        log.exception(
                            "rt.bootstrap.rebuild[%s]: c4.set_tracker_identity raised",
                            role,
                        )
            return runner



# ----------------------------------------------------------------------
# Build entry point

def build_rt_runtime(
    *,
    camera_service: Any,
    gc: Any,
    irl: Any,
    logger: logging.Logger | None = None,
) -> RtRuntimeHandle:
    """Assemble and return the full rt runtime graph.

    Crashes fast on config / hardware bootstrap failure. The caller is
    responsible for calling :meth:`RtRuntimeHandle.start` after construction.
    """
    log = logger or gc.logger
    log.info("rt.bootstrap: building runtime graph (RT_RUNTIME=1)")

    # ------------------------------------------------------------------
    # Event bus

    bus = InProcessEventBus()

    # ------------------------------------------------------------------
    # Perception runners (c2, c3, c4). C1 + Distributor are blind.

    perception_runners: list[PerceptionRunner] = []
    feed_zones: dict[str, Zone] = {}
    perception_sources: dict[str, PerceptionRunner] = {}
    skipped_roles: list[dict[str, str]] = []
    segment_recorder: Any | None = None

    for role in ("c2", "c3", "c4"):
        runner, zone, reason = build_perception_runner_for_role(
            role,
            camera_service=camera_service,
            event_bus=bus,
            logger=log,
        )
        if runner is None:
            log.warning(
                "rt.bootstrap[%s]: perception runner skipped (reason=%s)",
                role, reason or "unknown",
            )
            skipped_roles.append({"role": role, "reason": reason or "unknown"})
            continue
        feed_id = f"{role}_feed"
        perception_runners.append(runner)
        if zone is not None:
            feed_zones[feed_id] = zone
        perception_sources[feed_id] = runner
        if role == "c4":
            from rt.perception.segment_recorder import install as install_segment_recording

            segment_recorder = install_segment_recording(bus, runner)

    # ------------------------------------------------------------------
    # Cross-cutting subscribers (persistence / projections). Install after
    # the C4 segment recorder so classified/distributed events first flush
    # crop metadata, then the dossier projection can mirror the latest crop
    # preview into Recent Pieces.

    from rt.projections.piece_dossier import install as install_piece_dossier

    install_piece_dossier(bus)
    # ------------------------------------------------------------------
    # Capacity slots

    classification_cfg = getattr(
        getattr(irl, "irl_config", None), "classification_channel_config", None
    ) or getattr(irl, "classification_channel_config", None)
    feeder_cfg = getattr(
        getattr(irl, "irl_config", None), "feeder_config", None
    ) or getattr(irl, "feeder_config", None)
    max_zones = int(
        getattr(classification_cfg, "max_zones", 4) if classification_cfg else 4
    )

    slots: dict[tuple[str, str], CapacitySlot] = {
        ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
        ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
        ("c3", "c4"): CapacitySlot("c3_to_c4", max(1, max_zones)),
        ("c4", "distributor"): CapacitySlot("c4_to_dist", 1),
    }

    # ------------------------------------------------------------------
    # RulesEngine + Classifier

    sorting_profile_path = Path(getattr(gc, "sorting_profile_path", ""))
    if not sorting_profile_path.is_absolute():
        sorting_profile_path = Path(os.getcwd()) / sorting_profile_path

    # Bin layout is optional; if the operator has never edited one we let
    # the rules engine fall back to its default-bin route.
    bin_layout_path_str = os.environ.get("RT_BIN_LAYOUT_PATH", "")
    bin_layout_path = Path(bin_layout_path_str) if bin_layout_path_str else None

    rules_engine = RULES_ENGINES.create(
        "lego_default",
        sorting_profile_path=sorting_profile_path,
        bin_layout_path=bin_layout_path,
        default_bin_id="reject",
        logger=log,
    )
    log.info(
        "rt.bootstrap: rules_engine=lego_default profile=%s layout=%s",
        sorting_profile_path, bin_layout_path,
    )

    brickognize_url = os.environ.get("BRICKOGNIZE_API_URL") or None
    classifier = CLASSIFIERS.create(
        "brickognize",
        max_concurrent=4,
        timeout_s=12.0,
        api_url=brickognize_url,
        client=BrickognizeClient(api_url=brickognize_url, logger=log),
        logger=log,
    )

    # ------------------------------------------------------------------
    # Zone manager for C4 (ports ClassificationChannelConfig)

    intake_angle = float(
        getattr(classification_cfg, "intake_angle_deg", 305.0)
        if classification_cfg else 305.0
    )
    intake_half_width = float(
        getattr(classification_cfg, "intake_body_half_width_deg", 10.0)
        if classification_cfg else 10.0
    )
    guard_angle = float(
        getattr(classification_cfg, "intake_guard_deg", 28.0)
        if classification_cfg else 28.0
    )
    drop_angle = float(
        getattr(classification_cfg, "drop_angle_deg", 30.0)
        if classification_cfg else 30.0
    )
    drop_tolerance = float(
        getattr(classification_cfg, "drop_tolerance_deg", 14.0)
        if classification_cfg else 14.0
    )
    classify_angle = float(
        getattr(classification_cfg, "point_of_no_return_deg", drop_angle)
        if classification_cfg else drop_angle
    )
    stale_timeout = float(
        getattr(classification_cfg, "stale_zone_timeout_s", 1.5)
        if classification_cfg else 1.5
    )

    zone_manager = ZoneManager(
        max_zones=max(1, max_zones),
        intake_angle_deg=intake_angle,
        guard_angle_deg=guard_angle,
        default_half_width_deg=intake_half_width,
        drop_angle_deg=drop_angle,
        drop_tolerance_deg=drop_tolerance,
        stale_timeout_s=stale_timeout,
    )

    # ------------------------------------------------------------------
    # Hardware callables

    motion_diagnostics = MotionDiagnostics()
    c1_pulse, c1_recovery, c1_direct_move = build_c1_callables(
        irl,
        log,
        motion_diagnostics=motion_diagnostics,
    )
    c2_pulse, c2_direct_move = build_c2_callables(
        irl,
        log,
        motion_diagnostics=motion_diagnostics,
    )
    c3_pulse, c3_direct_move = build_c3_callables(
        irl,
        log,
        motion_diagnostics=motion_diagnostics,
    )
    (
        c4_carousel_move,
        c4_transport_move,
        c4_continuous_move,
        c4_startup_purge_move,
        c4_startup_purge_mode,
        c4_eject,
        c4_wiggle_move,
        c4_unjam_move,
        c4_direct_move,
    ) = build_c4_callables(
        irl,
        log,
        startup_purge_speed_scale=float(
            getattr(classification_cfg, "startup_purge_speed_scale", 1.0)
            if classification_cfg
            else 1.0
        ),
        transport_speed_scale=float(
            getattr(classification_cfg, "transport_speed_scale", 1.0)
            if classification_cfg
            else 1.0
        ),
        carousel_acceleration=(
            getattr(
                classification_cfg,
                "exit_release_shimmy_acceleration_microsteps_per_second_sq",
                1800,
            )
            if classification_cfg
            else 1800
        ),
        transport_acceleration=(
            getattr(
                classification_cfg,
                "transport_acceleration_microsteps_per_second_sq",
                1800,
            )
            if classification_cfg
            else 1800
        ),
        continuous_acceleration=getattr(
            classification_cfg,
            "continuous_acceleration_microsteps_per_second_sq",
            None,
        )
        if classification_cfg
        else None,
        startup_purge_acceleration=(
            getattr(
                classification_cfg,
                "startup_purge_acceleration_microsteps_per_second_sq",
                1800,
            )
            if classification_cfg
            else 1800
        ),
        motion_diagnostics=motion_diagnostics,
    )
    chute_move, chute_position_query = build_chute_callables(irl, rules_engine, log)

    # ------------------------------------------------------------------
    # Runtime instances

    track_transit = TrackTransitRegistry()

    # Bridge rt FSM transitions into RuntimeStatsCollector so the runtime
    # widget can show state_machines. RuntimeStatsCollector tolerates the
    # collector being absent (e.g. in tests) — guard with a callable so
    # we only pay the lookup when a transition actually fires.
    def _state_observer(runtime_id: str, from_state: str, to_state: str) -> None:
        runtime_stats = getattr(gc, "runtime_stats", None)
        if runtime_stats is None:
            return
        try:
            runtime_stats.observeStateTransition(
                machine=runtime_id,
                from_state=from_state,
                to_state=to_state,
            )
        except Exception:
            log.exception(
                "rt.bootstrap: observeStateTransition raised for %s %s->%s",
                runtime_id, from_state, to_state,
            )

    # Pulse-response observer wires C1 dispatch events to a deferred
    # cross-runtime snapshot taken from the orchestrator. The orchestrator
    # is constructed below, so the snapshot provider closes over a
    # one-element list and resolves at call time. This avoids a circular
    # construction: C1 -> observer -> orchestrator -> C1.
    _orchestrator_ref: list[Orchestrator] = []

    def _pulse_snapshot_provider() -> dict[str, Any]:
        if not _orchestrator_ref:
            return {}
        return _orchestrator_ref[0].cross_runtime_snapshot()

    # Repo root convention: software/sorter/backend/rt/bootstrap.py is 4
    # parents below the repo root. Keep pulse observations with runtime logs.
    c1_pulse_log_path = (
        Path(__file__).resolve().parents[4] / "logs" / "c1_pulse_observations.jsonl"
    )
    c1_pulse_observer = C1PulseObserver(
        snapshot_provider=_pulse_snapshot_provider,
        log_path=c1_pulse_log_path,
        logger=log,
    )

    def _record_c1_dispatch(action_id: str) -> None:
        try:
            c1_pulse_observer.record_dispatch(action_id)
        except Exception:
            log.exception("rt.bootstrap: c1 pulse_observer.record_dispatch raised")

    def _c1_recovery_admission_check(level: int) -> tuple[bool, dict[str, Any]]:
        if not _orchestrator_ref:
            return True, {"reason": "orchestrator_not_ready"}
        try:
            return _orchestrator_ref[0].c1_recovery_admission_decision(int(level))
        except Exception:
            log.exception(
                "rt.bootstrap: c1_recovery_admission_decision raised"
            )
            return True, {"reason": "admission_check_failed"}

    c1 = RuntimeC1(
        downstream_slot=slots[("c1", "c2")],
        pulse_command=c1_pulse,
        recovery_command=c1_recovery,
        sample_transport_command=c1_direct_move,
        logger=log,
        jam_timeout_s=float(
            getattr(feeder_cfg, "first_rotor_jam_timeout_s", DEFAULT_JAM_TIMEOUT_S)
        ),
        jam_min_pulses=int(
            getattr(feeder_cfg, "first_rotor_jam_min_pulses", DEFAULT_JAM_MIN_PULSES)
        ),
        jam_cooldown_s=float(
            getattr(
                feeder_cfg,
                "first_rotor_jam_retry_cooldown_s",
                DEFAULT_JAM_COOLDOWN_S,
            )
        ),
        max_recovery_cycles=int(
            getattr(feeder_cfg, "first_rotor_jam_max_cycles", DEFAULT_MAX_RECOVERY_CYCLES)
        ),
        pulse_cooldown_s=float(
            getattr(feeder_cfg, "first_rotor_pulse_cooldown_s", DEFAULT_PULSE_COOLDOWN_S)
        ),
        startup_hold_s=float(
            getattr(feeder_cfg, "first_rotor_startup_hold_s", DEFAULT_STARTUP_HOLD_S)
        ),
        unconfirmed_pulse_limit=int(
            getattr(
                feeder_cfg,
                "first_rotor_unconfirmed_pulse_limit",
                DEFAULT_UNCONFIRMED_PULSE_LIMIT,
            )
        ),
        observation_hold_s=float(
            getattr(
                feeder_cfg,
                "first_rotor_observation_hold_s",
                DEFAULT_OBSERVATION_HOLD_S,
            )
        ),
        state_observer=_state_observer,
        pulse_observer=_record_c1_dispatch,
        recovery_admission_check=_c1_recovery_admission_check,
    )
    c2 = RuntimeC2(
        upstream_slot=slots[("c1", "c2")],
        downstream_slot=slots[("c2", "c3")],
        pulse_command=c2_pulse,
        sample_transport_command=c2_direct_move,
        upstream_progress_callback=c1.notify_downstream_progress,
        admission=AlwaysAdmit(),
        ejection_timing=ConstantPulseEjection(),
        logger=log,
        event_bus=bus,
        state_observer=_state_observer,
    )
    c3 = RuntimeC3(
        upstream_slot=slots[("c2", "c3")],
        downstream_slot=slots[("c3", "c4")],
        pulse_command=c3_pulse,
        sample_transport_command=c3_direct_move,
        admission=AlwaysAdmit(),
        ejection_timing=ConstantPulseEjection(),
        logger=log,
        event_bus=bus,
        track_transit=track_transit,
        state_observer=_state_observer,
    )
    c4_admission = C4Admission(
        max_zones=max(1, max_zones),
        max_raw_detections=getattr(
            classification_cfg,
            "max_raw_detections",
            None,
        )
        if classification_cfg
        else None,
        require_dropzone_clear=bool(
            getattr(classification_cfg, "require_dropzone_clear_for_admission", True)
            if classification_cfg
            else True
        ),
    )
    c4_ejection = C4EjectionTiming(
        pulse_ms=150.0,
        settle_ms=500.0,
        fall_time_ms=1500.0,
    )
    c4_startup_purge = C4StartupPurgeStrategy(
        enabled=bool(
            getattr(classification_cfg, "startup_purge_enabled", True)
            if classification_cfg
            else True
        ),
        prime_step_deg=float(
            getattr(classification_cfg, "startup_purge_prime_step_deg", 10.0)
            if classification_cfg
            else 10.0
        ),
        prime_cooldown_ms=float(
            getattr(classification_cfg, "startup_purge_prime_cooldown_ms", 120)
            if classification_cfg
            else 120
        ),
        max_prime_moves=int(
            getattr(classification_cfg, "startup_purge_max_prime_moves", 3)
            if classification_cfg
            else 3
        ),
        clear_hold_ms=float(
            getattr(classification_cfg, "startup_purge_clear_hold_ms", 600)
            if classification_cfg
            else 600
        ),
    )

    def _crop_provider(frame: Any, track: Any) -> Any:
        raw = getattr(frame, "raw", None)
        bbox = getattr(track, "bbox_xyxy", None)
        if raw is None or bbox is None:
            return None
        try:
            x1, y1, x2, y2 = (int(v) for v in bbox)
            h, w = raw.shape[:2]
            x1 = max(0, min(w - 1, x1))
            x2 = max(0, min(w, x2))
            y1 = max(0, min(h - 1, y1))
            y2 = max(0, min(h, y2))
            if x2 <= x1 or y2 <= y1:
                return None
            return raw[y1:y2, x1:x2]
        except Exception:
            log.exception("rt.bootstrap: crop_provider raised")
            return None

    def _c4_startup_purge_detection_count() -> int:
        # Count only what the runtime would actually process — i.e. the
        # post-filter track batch. Using raw YOLO detections here makes the
        # purge strategy spin forever on stationary ghosts that the ghost
        # filter has already decided are phantoms.
        runner = perception_sources.get("c4_feed")
        if runner is None:
            return 0
        latest_state = getattr(runner, "latest_state", None)
        if callable(latest_state):
            try:
                state = latest_state()
            except Exception:
                log.debug(
                    "rt.bootstrap: c4 latest_state() raised during startup purge probe",
                    exc_info=True,
                )
                state = None
            filtered = getattr(state, "filtered_tracks", None) if state is not None else None
            tracks = getattr(filtered, "tracks", None) if filtered is not None else None
            if isinstance(tracks, (list, tuple)):
                return len(tracks)
        latest_tracks = getattr(runner, "latest_tracks", None)
        if callable(latest_tracks):
            try:
                batch = latest_tracks()
            except Exception:
                log.debug(
                    "rt.bootstrap: c4 latest_tracks() raised during startup purge probe",
                    exc_info=True,
                )
                batch = None
            tracks = getattr(batch, "tracks", None) if batch is not None else None
            if isinstance(tracks, (list, tuple)):
                return len(tracks)
        return 0

    c4_runner = perception_sources.get("c4_feed")
    c4_tracker_identity_fn = (
        getattr(c4_runner, "tracker_identity", None) if c4_runner is not None else None
    )
    c4_tracker_identity = (
        c4_tracker_identity_fn() if callable(c4_tracker_identity_fn) else {}
    )

    c4 = RuntimeC4(
        upstream_slot=slots[("c3", "c4")],
        downstream_slot=slots[("c4", "distributor")],
        zone_manager=zone_manager,
        classifier=classifier,
        admission=c4_admission,
        ejection=c4_ejection,
        startup_purge=c4_startup_purge,
        startup_purge_detection_count_provider=_c4_startup_purge_detection_count,
        carousel_move_command=c4_carousel_move,
        transport_move_command=c4_transport_move,
        sample_transport_move_command=c4_direct_move,
        startup_purge_move_command=c4_startup_purge_move,
        wiggle_move_command=c4_wiggle_move,
        unjam_move_command=c4_unjam_move,
        startup_purge_mode_command=c4_startup_purge_mode,
        eject_command=c4_eject,
        crop_provider=_crop_provider,
        logger=log,
        event_bus=bus,
        track_transit=track_transit,
        tracker_key=c4_tracker_identity.get("tracker_key"),
        tracker_epoch=c4_tracker_identity.get("tracker_epoch"),
        state_observer=_state_observer,
        classify_angle_deg=classify_angle,
        exit_angle_deg=drop_angle,
        angle_tolerance_deg=drop_tolerance,
        shimmy_step_deg=float(
            getattr(classification_cfg, "exit_release_shimmy_amplitude_deg", 4.0)
            if classification_cfg
            else 4.0
        ),
        exit_approach_angle_deg=float(
            getattr(classification_cfg, "positioning_window_deg", 36.0)
            if classification_cfg
            else 36.0
        ),
        exit_bbox_overlap_ratio=float(
            getattr(classification_cfg, "exit_release_overlap_ratio", 0.5)
            if classification_cfg
            else 0.5
        ),
    )

    run_recorder = getattr(gc, "run_recorder", None)
    # Forward declare distributor; we'll wire callbacks after creation.
    distributor_ref: dict[str, Any] = {}

    def _on_ready(piece_uuid: str) -> None:
        """Distributor -> C4 ReadySignal: C4 should eject now."""
        try:
            c4.on_distributor_ready(piece_uuid)  # type: ignore[attr-defined]
        except AttributeError:
            # Legacy-style wiring: fall back to a direct handoff_commit once
            # C4's eject completes.  This is re-probed on the live machine.
            log.warning(
                "TODO_PHASE5_WIRING: RuntimeC4 lacks on_distributor_ready — "
                "add method or use handoff_commit loop. Piece %s stalled.",
                piece_uuid,
            )

    def _on_delivered(piece_uuid: str) -> None:
        try:
            c4.on_piece_delivered(piece_uuid, now_mono=time.monotonic())
        except Exception:
            log.exception("rt.bootstrap: c4.on_piece_delivered raised")

    def _on_ack(piece_uuid: str, accepted: bool, reason: str) -> None:
        if not accepted:
            try:
                c4.on_piece_rejected(piece_uuid, reason)
            except Exception:
                log.exception("rt.bootstrap: c4.on_piece_rejected raised")

    distributor = RuntimeDistributor(
        upstream_slot=slots[("c4", "distributor")],
        rules_engine=rules_engine,
        ejection_timing=c4_ejection,
        chute_move_command=chute_move,
        chute_position_query=chute_position_query,
        on_ready_callback=_on_ready,
        on_piece_delivered_callback=_on_delivered,
        on_ack_callback=_on_ack,
        logger=log,
        event_bus=bus,
        run_recorder=run_recorder,
        state_observer=_state_observer,
    )
    distributor_ref["ref"] = distributor

    # Wire C4 -> Distributor handshake via the HandoffPort. C4 asks the
    # distributor to position once a piece is classified, waits for
    # on_distributor_ready(), ejects, then commits so the distributor can
    # publish delivery.
    try:
        c4.set_handoff_port(distributor)
    except Exception:
        log.exception("rt.bootstrap: distributor handshake wiring failed")

    # Same software escapement on the C2 -> C3 transfer. Operator
    # observation 2026-04-25 confirmed C2 was pushing pieces onto C3
    # even when C3's drop zone was already occupied; this gates each
    # C2 exit pulse on C3 reporting a clear drop arc.
    try:
        c2.set_landing_lease_port(c3.landing_lease_port())
    except Exception:
        log.exception("rt.bootstrap: c2 landing-lease wiring failed")

    # ------------------------------------------------------------------
    # Orchestrator

    orch = Orchestrator(
        runtimes=[c1, c2, c3, c4, distributor],
        slots=slots,
        perception_sources=perception_sources,  # type: ignore[arg-type]
        event_bus=bus,
        logger=log,
        tick_period_s=0.020,
    )
    _orchestrator_ref.append(orch)
    orch.attach_c1_pulse_observer(c1_pulse_observer)

    # SectorCarouselHandler owns C4 transport/eject sequencing in production.
    # RuntimeC4 stays alive underneath for BoxMot tracking, classification,
    # crop/dossier updates, and software encoder updates.
    install_sector_carousel_handler(
        orchestrator=orch,
        c3=c3,
        c4=c4,
        distributor=distributor,
        perception_sources=perception_sources,
        classifier=classifier,
        crop_provider=_crop_provider,
        irl=irl,
        event_bus=bus,
        c4_eject=c4_eject,
        logger=log,
    )
    log.info(
        "rt.bootstrap: orchestrator ready "
        "(runtimes=c1,c2,c3,c4,distributor; perception_feeds=%s; slots=%s)",
        list(perception_sources.keys()), [f"{u}->{d}" for u, d in slots.keys()],
    )

    handle = RtRuntimeHandle(
        orchestrator=orch,
        perception_runners=perception_runners,
        event_bus=bus,
        c4=c4,
        distributor=distributor,
        c1=c1,
        c2=c2,
        c3=c3,
        feed_zones=feed_zones,
        skipped_roles=skipped_roles,
        camera_service=camera_service,
        irl=irl,
        motion_diagnostics=motion_diagnostics,
        segment_recorder=segment_recorder,
    )
    handle.sample_collector = AuxiliaryTeacherSampleCollector(
        runner_provider=lambda: list(handle.perception_runners),
        event_bus=bus,
        logger=log,
    )
    return handle


__all__ = ["RtRuntimeHandle", "build_rt_runtime"]
