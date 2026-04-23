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
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import rt.perception  # noqa: F401 - register detectors/trackers/filters
import rt.rules  # noqa: F401 - register rules engines
from rt.classification.brickognize import BrickognizeClient
from rt.config.schema import PipelineConfig
from rt.contracts.feed import PolarZone, PolygonZone, RectZone, Zone
from rt.contracts.registry import (
    CLASSIFIERS,
    RULES_ENGINES,
)
from rt.contracts.tracking import Track
from rt.coupling.orchestrator import Orchestrator
from rt.coupling.slots import CapacitySlot
from rt.events.bus import InProcessEventBus
from rt.perception.detectors.hive_onnx import default_hive_detector_slug
from rt.perception.feeds import CameraFeed
from rt.perception.pipeline import build_pipeline_from_config
from rt.perception.pipeline_runner import PerceptionRunner
from rt.runtimes._strategies import (
    AlwaysAdmit,
    C4Admission,
    C4EjectionTiming,
    C4StartupPurgeStrategy,
    ConstantPulseEjection,
)
from rt.runtimes._zones import ZoneManager
from rt.services.maintenance_purge import C234PurgeCoordinator
from rt.runtimes.c1 import RuntimeC1
from rt.runtimes.c2 import RuntimeC2
from rt.runtimes.c3 import RuntimeC3
from rt.runtimes.c4 import RuntimeC4
from rt.runtimes.distributor import RuntimeDistributor
from utils.polygon_resolution import saved_polygon_resolution


# Mapping rt-side role slug -> legacy camera_service role name.
_ROLE_TO_LEGACY_CAMERA: dict[str, str] = {
    "c2": "c_channel_2",
    "c3": "c_channel_3",
    "c4": "carousel",
}


@dataclass(frozen=True, slots=True)
class FeedAnnotationSnapshot:
    """Runtime-owned read model for camera overlays and live inspection."""

    feed_id: str
    zone: Zone | None
    tracks: tuple[Track, ...] = ()


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
    c2: RuntimeC2 | None = None
    c3: RuntimeC3 | None = None
    feed_zones: dict[str, Zone] = field(default_factory=dict)
    started: bool = False
    perception_started: bool = False
    paused: bool = False
    # (role, reason) entries populated at bootstrap when a perception runner
    # could not be built. Observable via /api/rt/status; never fatal.
    skipped_roles: list[dict[str, str]] = field(default_factory=list)
    # Back-reference needed for runner rebuilds after config changes.
    camera_service: Any | None = None
    _rebuild_lock: threading.Lock = field(default_factory=threading.Lock)
    _purge_coordinator: C234PurgeCoordinator = field(
        default_factory=C234PurgeCoordinator
    )

    def start_perception(self) -> None:
        if self.perception_started:
            return
        self.event_bus.start()
        for runner in self.perception_runners:
            runner.start()
        self.perception_started = True

    def start(self, *, paused: bool = False) -> None:
        if self.started:
            return
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
        if self.started:
            try:
                self.orchestrator.stop()
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: orchestrator stop raised"
                )
        for runner in self.perception_runners:
            try:
                runner.stop(timeout=1.0)
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: perception runner stop raised"
                )
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
        fn = getattr(self.orchestrator, "resume", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                logging.getLogger("rt.bootstrap").exception(
                    "RtRuntimeHandle: orchestrator.resume raised"
                )
        self.paused = False

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
        orchestrator_status = getattr(self.orchestrator, "status_snapshot", None)
        if callable(orchestrator_status):
            try:
                snapshot = dict(orchestrator_status() or {})
            except Exception:
                snapshot = {}
            runtime_health = dict(snapshot.get("runtime_health") or {})
            runtime_debug = dict(snapshot.get("runtime_debug") or {})
            slot_debug = dict(snapshot.get("slot_debug") or {})

        return {
            "perception_started": bool(self.perception_started),
            "started": bool(self.started),
            "paused": bool(self.paused),
            "runners": runners_out,
            "skipped_roles": list(self.skipped_roles),
            "runtime_health": runtime_health,
            "runtime_debug": runtime_debug,
            "slot_debug": slot_debug,
            "maintenance": {"c234_purge": self.c234_purge_status()},
        }

    def annotation_snapshot(self, feed_id: str) -> FeedAnnotationSnapshot:
        """Return a compact overlay/debug snapshot for one perception feed."""
        zone = self.feed_zones.get(feed_id)
        if not isinstance(zone, (RectZone, PolygonZone, PolarZone)):
            zone = None

        tracks: tuple[Track, ...] = ()
        runner = self.runner_for_feed(feed_id)
        if runner is not None:
            latest_state = getattr(runner, "latest_state", None)
            state = latest_state() if callable(latest_state) else None
            raw_tracks = getattr(state, "raw_tracks", None)
            raw_track_items = getattr(raw_tracks, "tracks", None)
            if isinstance(raw_track_items, tuple):
                tracks = raw_track_items
            else:
                latest_tracks = getattr(runner, "latest_tracks", None)
                batch = latest_tracks() if callable(latest_tracks) else None
                batch_tracks = getattr(batch, "tracks", None)
                if isinstance(batch_tracks, tuple):
                    tracks = batch_tracks

        return FeedAnnotationSnapshot(feed_id=feed_id, zone=zone, tracks=tracks)

    def c234_purge_status(self) -> dict[str, Any]:
        return self._purge_coordinator.status()

    def start_c234_purge(
        self,
        *,
        state_publisher: Callable[[str], None] | None = None,
        timeout_s: float = 120.0,
        clear_hold_s: float = 0.75,
        poll_s: float = 0.05,
    ) -> bool:
        if not self.started:
            raise RuntimeError("rt runtime is not started")
        return self._purge_coordinator.start(
            runtimes=(self.c2, self.c3, self.c4),
            control=self,
            state_publisher=state_publisher,
            timeout_s=timeout_s,
            clear_hold_s=clear_hold_s,
            poll_s=poll_s,
        )

    def cancel_c234_purge(self) -> bool:
        return self._purge_coordinator.cancel()

    def runner_for_feed(self, feed_id: str) -> PerceptionRunner | None:
        """Return the PerceptionRunner driving ``feed_id`` if registered."""
        for runner in self.perception_runners:
            pipeline = getattr(runner, "_pipeline", None)
            if pipeline is None:
                continue
            feed = getattr(pipeline, "feed", None)
            if feed is not None and getattr(feed, "feed_id", None) == feed_id:
                return runner
        return None

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
            runner, zone, reason = _build_perception_runner_for_role(
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
            return runner


# ----------------------------------------------------------------------
# Polygon / zone loading — self-contained. The legacy VisionManager helpers
# (``_channelPolygonKeyForRole`` / ``_loadSavedPolygon``) have been inlined
# here so rt/ no longer depends on the legacy vision runtime.

def _channel_polygon_key_for_role(role: str) -> str | None:
    if role == "c_channel_2":
        return "second_channel"
    if role == "c_channel_3":
        return "third_channel"
    if role == "carousel":
        return "classification_channel"
    return None


def _saved_resolution_for_channel(saved: dict, channel_key: str | None) -> list:
    """Return the capture resolution a polygon was saved at.

    Kept as a light wrapper so bootstrap code can stay simple while the
    resolution lookup logic lives in one shared place.
    """
    return list(saved_polygon_resolution(saved, channel_key=channel_key))


def _channel_angle_key_for_polygon_key(polygon_key: str) -> str | None:
    if polygon_key == "second_channel":
        return "second"
    if polygon_key == "third_channel":
        return "third"
    if polygon_key == "classification_channel":
        return "classification_channel"
    return None


def _arc_params_key_for_role(role: str) -> str | None:
    legacy_role = _ROLE_TO_LEGACY_CAMERA.get(role, role)
    if legacy_role == "c_channel_2":
        return "second"
    if legacy_role == "c_channel_3":
        return "third"
    if legacy_role in {"carousel", "classification_channel"}:
        return "classification_channel"
    return None


def _load_arc_tracker_params(
    role: str,
    *,
    target_w: int,
    target_h: int,
) -> dict[str, Any]:
    """Load scaled polar geometry for the tracker from channel arc params.

    Arc channels keep two distinct concerns:
    - polygon zone: mask/crop/overlay
    - polar geometry: center + radius range for angle-aware tracking

    The UI already stores both in the channel_polygons blob; bootstrap must
    carry both into the perception pipeline.
    """
    try:
        from blob_manager import getChannelPolygons
    except Exception:
        return {}
    saved = getChannelPolygons()
    if not isinstance(saved, dict):
        return {}
    arc_params = saved.get("arc_params")
    if not isinstance(arc_params, dict):
        return {}
    channel_key = _arc_params_key_for_role(role)
    if channel_key is None:
        return {}
    raw = arc_params.get(channel_key)
    if not isinstance(raw, dict):
        return {}
    center = raw.get("center")
    try:
        center_x = float(center[0])
        center_y = float(center[1])
        inner_radius = float(raw["inner_radius"])
        outer_radius = float(raw["outer_radius"])
    except Exception:
        return {}
    if inner_radius < 0.0 or outer_radius <= inner_radius:
        return {}
    saved_res = _saved_resolution_for_channel(saved, channel_key)
    try:
        src_w, src_h = int(saved_res[0]), int(saved_res[1])
    except (TypeError, ValueError):
        return {}
    if src_w <= 0 or src_h <= 0:
        return {}
    sx = float(target_w) / float(src_w)
    sy = float(target_h) / float(src_h)
    radius_scale = (abs(sx) + abs(sy)) / 2.0
    return {
        "polar_center": (center_x * sx, center_y * sy),
        "polar_radius_range": (
            inner_radius * radius_scale,
            outer_radius * radius_scale,
        ),
    }


def _load_saved_polygon(key: str, target_w: int, target_h: int) -> Any:
    """Read + scale a polygon from ``blob_manager.getChannelPolygons()``."""
    import numpy as np  # local — keeps module import fast

    try:
        from blob_manager import getChannelPolygons
    except Exception:
        return None
    saved = getChannelPolygons()
    if not isinstance(saved, dict):
        return None
    polygon_data = saved.get("polygons") or {}
    pts = polygon_data.get(key)
    if not isinstance(pts, list) or len(pts) < 3:
        return None
    channel_key_for_res = _channel_angle_key_for_polygon_key(key) or key
    saved_res = _saved_resolution_for_channel(saved, channel_key_for_res)
    try:
        src_w, src_h = int(saved_res[0]), int(saved_res[1])
    except (TypeError, ValueError):
        return None
    if src_w <= 0 or src_h <= 0:
        return None
    sx = float(target_w) / float(src_w)
    sy = float(target_h) / float(src_h)
    try:
        return np.array(
            [[float(p[0]) * sx, float(p[1]) * sy] for p in pts],
            dtype=np.int32,
        )
    except (TypeError, ValueError):
        return None


def _configured_resolution_for_role(
    camera_service: Any,
    legacy_role: str,
) -> tuple[int, int] | None:
    """Resolve ``(width, height)`` from the device config — no frame needed.

    Returns ``None`` only if the camera_service has no device for the role,
    or if the device has no configured capture resolution. Falls back to a
    live frame probe as a last resort for test harnesses that don't wire a
    real device graph.
    """
    w: int | None = None
    h: int | None = None

    get_device = getattr(camera_service, "get_device", None)
    if callable(get_device):
        try:
            device = get_device(legacy_role)
        except Exception:
            device = None
        config = getattr(device, "config", None) if device is not None else None
        cfg_w = getattr(config, "width", None)
        cfg_h = getattr(config, "height", None)
        if isinstance(cfg_w, int) and isinstance(cfg_h, int) and cfg_w > 0 and cfg_h > 0:
            w, h = cfg_w, cfg_h

    if w is None or h is None:
        # Fallback: probe the latest frame. Only exercised in tests or on
        # exotic setups where the device doesn't expose a config object.
        get_capture = getattr(camera_service, "get_capture_thread_for_role", None)
        if callable(get_capture):
            try:
                capture = get_capture(legacy_role)
            except Exception:
                capture = None
            frame = getattr(capture, "latest_frame", None) if capture is not None else None
            raw = getattr(frame, "raw", None)
            if raw is not None and hasattr(raw, "shape"):
                h, w = int(raw.shape[0]), int(raw.shape[1])

    if w is None or h is None:
        return None
    return int(w), int(h)


# ----------------------------------------------------------------------
# Role ↔ UI scope / feed-id / detector-config helpers.

# Each rt-role (c2/c3/c4) maps onto one of the Svelte settings scopes so the
# user-configured detector slug can be read from the right detection-config
# blob at bootstrap and on rebuild.
_ROLE_TO_UI_SCOPE: dict[str, str] = {
    "c2": "feeder",
    "c3": "feeder",
    "c4": "classification_channel",
}


# Names used by the Svelte feeder dropdown to key into
# ``getFeederDetectionConfig()["algorithm_by_role"]``. The two feeder
# channels and the classification C-channel all share the feeder config.
_ROLE_TO_FEEDER_ROLE_KEY: dict[str, str] = {
    "c2": "c_channel_2",
    "c3": "c_channel_3",
    "c4": "classification_channel",
}


def _detector_slug_for_role(role: str, logger: logging.Logger) -> str:
    """Return the detector slug the user has configured for ``role``.

    Falls back to the per-scope default (see
    ``default_detector_slug_for_ui_scope``) when no saved preference exists,
    and finally to the global Hive default when even that yields ``None``.
    """
    from rt.contracts.registry import (
        DETECTORS,
        default_detector_slug_for_ui_scope,
    )

    ui_scope = _ROLE_TO_UI_SCOPE.get(role, "feeder")
    feeder_role_key = _ROLE_TO_FEEDER_ROLE_KEY.get(role)
    saved_slug: str | None = None
    try:
        if ui_scope == "feeder" or feeder_role_key == "classification_channel":
            from blob_manager import getFeederDetectionConfig

            cfg = getFeederDetectionConfig()
            if isinstance(cfg, dict):
                by_role = cfg.get("algorithm_by_role")
                if isinstance(by_role, dict) and feeder_role_key:
                    candidate = by_role.get(feeder_role_key)
                    if isinstance(candidate, str) and candidate:
                        saved_slug = candidate
                if not saved_slug:
                    candidate = cfg.get("algorithm")
                    if isinstance(candidate, str) and candidate:
                        saved_slug = candidate
        elif ui_scope == "classification_channel":
            from blob_manager import getClassificationChannelDetectionConfig

            cfg = getClassificationChannelDetectionConfig()
            if isinstance(cfg, dict):
                candidate = cfg.get("algorithm")
                if isinstance(candidate, str) and candidate:
                    saved_slug = candidate
    except Exception:
        logger.debug(
            "rt.bootstrap[%s]: detector slug lookup raised — using default",
            role,
            exc_info=True,
        )
        saved_slug = None

    if saved_slug and saved_slug in DETECTORS.keys():
        return saved_slug

    preferred = default_detector_slug_for_ui_scope(ui_scope)
    if preferred:
        return preferred
    # Final fallback — keeps C2/C3 working even on first boot when the
    # dropdown has never been touched.
    return default_hive_detector_slug()


def _build_perception_runner_for_role(
    role: str,
    *,
    camera_service: Any,
    event_bus: InProcessEventBus,
    logger: logging.Logger,
) -> tuple[PerceptionRunner | None, Zone | None, str]:
    """Build the perception runner (+ zone) for ``role``.

    Returns ``(runner, zone, reason)``. ``runner`` is ``None`` on failure;
    ``reason`` is an empty string on success or a slug-style label when the
    runner could not be built. The returned runner has NOT been started.
    """
    zone, reason = _load_zone_for_role(role, camera_service, logger)
    if zone is None:
        return None, None, reason or "no_zone"

    feed_id = f"{role}_feed"
    camera_id = _ROLE_TO_LEGACY_CAMERA.get(role, role)
    purpose = {"c2": "c2_feed", "c3": "c3_feed", "c4": "c4_feed"}.get(role)
    if purpose is None:
        logger.error("rt.bootstrap[%s]: unknown role — cannot build perception", role)
        return None, zone, "unknown_role"
    try:
        feed = CameraFeed(
            feed_id=feed_id,
            purpose=purpose,  # type: ignore[arg-type]
            camera_id=camera_id,
            camera_service=camera_service,
            zone=zone,
            fps_target=10.0 if role != "c4" else 8.0,
        )
    except Exception:
        logger.exception("rt.bootstrap[%s]: CameraFeed build failed", role)
        return None, zone, "camera_feed_build_failed"

    detector_slug = _detector_slug_for_role(role, logger)
    tracker_params: dict[str, Any] = {}
    target_res = _configured_resolution_for_role(camera_service, camera_id)
    if target_res is not None:
        tracker_params = _load_arc_tracker_params(
            role,
            target_w=int(target_res[0]),
            target_h=int(target_res[1]),
        )
    pipeline_config = PipelineConfig(
        feed_id=feed_id,
        detector={
            "key": detector_slug,
            "params": {"conf_threshold": 0.25, "iou_threshold": 0.45},
        },
        tracker={"key": "polar", "params": tracker_params},
        filters=[],
    )
    try:
        pipeline = build_pipeline_from_config(pipeline_config, feed, zone)
    except Exception:
        logger.exception(
            "rt.bootstrap[%s]: pipeline build failed (detector=%s)",
            role, detector_slug,
        )
        return None, zone, "pipeline_build_failed"
    runner = PerceptionRunner(
        pipeline=pipeline,
        period_ms=200,
        event_bus=event_bus,
        name=f"RtPerception[{role}]",
    )
    logger.info(
        "rt.bootstrap[%s]: perception runner ready (feed=%s, detector=%s)",
        role, feed_id, detector_slug,
    )
    return runner, zone, ""


def _load_zone_for_role(
    role: str,
    camera_service: Any,
    logger: logging.Logger,
) -> tuple[Zone | None, str]:
    """Build the perception zone for ``role`` without waiting for a live frame.

    Returns ``(zone, reason)``. ``zone`` is ``None`` on failure; ``reason``
    is an empty string on success or a short slug describing the skip
    cause (``"no_camera_config"``, ``"no_polygon_and_no_resolution"``, ...).

    The polygon lookup uses the saved ``resolution`` metadata from the
    channel_polygons blob, and the target frame resolution is read from the
    camera device config. Both are available at bootstrap time independent
    of frame delivery, so C4 and every other channel load their zones as
    soon as the camera_service is built — no boot-race.
    """
    legacy_role = _ROLE_TO_LEGACY_CAMERA.get(role, role)

    # Target frame resolution — pulled from the camera device config, no frame.
    target_res = _configured_resolution_for_role(camera_service, legacy_role)
    target_w, target_h = target_res if target_res is not None else (None, None)

    polygon_key = _channel_polygon_key_for_role(legacy_role)
    polygon = None
    if polygon_key and target_w is not None and target_h is not None:
        try:
            polygon = _load_saved_polygon(polygon_key, target_w, target_h)
        except Exception:
            polygon = None

    if polygon is not None and len(polygon) >= 3:
        vertices = tuple((int(p[0]), int(p[1])) for p in polygon)
        return PolygonZone(vertices=vertices), ""

    if target_w is None or target_h is None:
        logger.warning(
            "rt.bootstrap[%s]: no camera config resolution for %r — cannot build zone",
            role, legacy_role,
        )
        return None, "no_camera_config"

    logger.warning(
        "rt.bootstrap[%s]: no saved polygon for %r — using full-frame %dx%d",
        role, polygon_key, target_w, target_h,
    )
    return RectZone(x=0, y=0, w=target_w, h=target_h), ""


# ----------------------------------------------------------------------
# Hardware-callable factories — the ONE place rt/ touches irl.*

def _build_c1_callables(
    irl: Any, logger: logging.Logger
) -> tuple[Callable[[], bool], Callable[[int], bool]]:
    """Return (pulse, recovery) closures for RuntimeC1.

    Bridge: irl.c_channel_1_rotor_stepper.move_degrees /
            irl.feeder_config.first_rotor for pulse sizing.
    """

    def pulse() -> bool:
        stepper = getattr(irl, "c_channel_1_rotor_stepper", None)
        if stepper is None:
            logger.error("TODO_PHASE5_WIRING: c1 pulse - c_channel_1_rotor_stepper missing")
            return False
        cfg = getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        )
        if cfg is None:
            logger.error("TODO_PHASE5_WIRING: c1 pulse - feeder_config missing")
            return False
        pulse_cfg = getattr(cfg, "first_rotor", None)
        if pulse_cfg is None:
            logger.error("TODO_PHASE5_WIRING: c1 pulse - feeder_config.first_rotor missing")
            return False
        try:
            deg = stepper.degrees_for_microsteps(pulse_cfg.steps_per_pulse)
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC1: pulse raised")
            return False

    def recovery(level: int) -> bool:
        logger.warning(
            "TODO_PHASE5_WIRING: c1 jam recovery level=%d — live verification needed "
            "(stepper.move_degrees_blocking shake sequence)",
            level,
        )
        return False

    return pulse, recovery


def _build_c2_callables(
    irl: Any, logger: logging.Logger
) -> tuple[Callable[[], bool], Callable[[], bool]]:
    def pulse() -> bool:
        stepper = getattr(irl, "c_channel_2_rotor_stepper", None)
        cfg = getattr(getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        ), "second_rotor_normal", None)
        if stepper is None or cfg is None:
            logger.error("TODO_PHASE5_WIRING: c2 pulse - stepper/cfg missing")
            return False
        try:
            deg = stepper.degrees_for_microsteps(cfg.steps_per_pulse)
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC2: pulse raised")
            return False

    def wiggle() -> bool:
        logger.warning(
            "TODO_PHASE5_WIRING: c2 wiggle — live verification needed"
        )
        return False

    return pulse, wiggle


def _build_c3_callables(
    irl: Any, logger: logging.Logger
) -> tuple[Callable[[Any, float], bool], Callable[[], bool]]:
    def pulse(mode: Any, _pulse_ms: float) -> bool:
        stepper = getattr(irl, "c_channel_3_rotor_stepper", None)
        feeder_cfg = getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        )
        if stepper is None or feeder_cfg is None:
            logger.error("TODO_PHASE5_WIRING: c3 pulse - stepper/cfg missing")
            return False
        mode_value = getattr(mode, "value", mode)
        cfg = (
            feeder_cfg.third_rotor_precision
            if str(mode_value) == "precise"
            else feeder_cfg.third_rotor_normal
        )
        try:
            deg = stepper.degrees_for_microsteps(cfg.steps_per_pulse)
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC3: pulse raised")
            return False

    def wiggle() -> bool:
        logger.warning(
            "TODO_PHASE5_WIRING: c3 wiggle — live verification needed"
        )
        return False

    return pulse, wiggle


def _build_c4_callables(
    irl: Any,
    logger: logging.Logger,
    *,
    startup_purge_speed_scale: float = 1.0,
) -> tuple[
    Callable[[float], bool],
    Callable[[float], bool],
    Callable[[bool], bool],
    Callable[[], bool],
]:
    def _default_speed_limit() -> int | None:
        cfg_root = getattr(irl, "irl_config", None) or irl
        cfg = getattr(cfg_root, "carousel_stepper", None)
        speed = getattr(cfg, "default_steps_per_second", None)
        return int(speed) if isinstance(speed, int) and speed > 0 else None

    def _move_with_speed_limit(deg: float, *, speed_limit: int | None) -> bool:
        stepper = getattr(irl, "carousel_stepper", None)
        if stepper is None:
            logger.error("TODO_PHASE5_WIRING: c4 carousel move - stepper missing")
            return False
        default_speed = _default_speed_limit()
        if (
            speed_limit is None
            or default_speed is None
            or speed_limit <= default_speed
        ):
            try:
                return bool(stepper.move_degrees(deg))
            except Exception:
                logger.exception("RuntimeC4: carousel_move raised")
                return False
        try:
            stepper.set_speed_limits(16, int(speed_limit))
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC4: fast carousel_move raised")
            return False

    def carousel_move(deg: float) -> bool:
        return _move_with_speed_limit(deg, speed_limit=None)

    purge_speed_limit = None
    default_speed = _default_speed_limit()
    if default_speed is not None and startup_purge_speed_scale > 1.0:
        purge_speed_limit = max(
            default_speed,
            int(round(float(default_speed) * float(startup_purge_speed_scale))),
        )

    def startup_purge_move(deg: float) -> bool:
        return carousel_move(deg)

    def startup_purge_mode(enabled: bool) -> bool:
        stepper = getattr(irl, "carousel_stepper", None)
        default_speed = _default_speed_limit()
        if stepper is None or default_speed is None:
            return True
        speed_limit = purge_speed_limit if enabled and purge_speed_limit is not None else default_speed
        try:
            stepper.set_speed_limits(16, int(speed_limit))
            return True
        except Exception:
            logger.exception("RuntimeC4: startup purge mode speed-limit change raised")
            return False

    def eject() -> bool:
        # Legacy ejection lives in the classification_channel_eject RotorPulseConfig
        # applied against the carousel stepper at high speed.
        stepper = getattr(irl, "carousel_stepper", None)
        feeder_cfg = getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        )
        cfg = (
            getattr(feeder_cfg, "classification_channel_eject", None)
            if feeder_cfg
            else None
        )
        if stepper is None or cfg is None:
            logger.error(
                "TODO_PHASE5_WIRING: c4 eject - stepper or classification_channel_eject cfg missing"
            )
            return False
        try:
            deg = stepper.degrees_for_microsteps(cfg.steps_per_pulse)
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC4: eject raised")
            return False

    return carousel_move, startup_purge_move, startup_purge_mode, eject


def _build_chute_callables(
    irl: Any,
    rules_engine: Any,
    logger: logging.Logger,
) -> tuple[Callable[[str], bool], Callable[[], str | None]]:
    """Chute move + position-query bridging legacy Chute.moveToBin.

    Bin id format: ``L{layer}-S{section}-B{bin}`` (see LegoRulesEngine).
    """
    from irl.bin_layout import BinSize  # noqa: F401 — bridge type

    def _parse(bin_id: str) -> tuple[int, int, int] | None:
        try:
            parts = bin_id.split("-")
            if len(parts) != 3:
                return None
            return (
                int(parts[0][1:]),
                int(parts[1][1:]),
                int(parts[2][1:]),
            )
        except ValueError:
            return None

    def move(bin_id: str) -> bool:
        chute = getattr(irl, "chute", None)
        if chute is None:
            logger.error(
                "TODO_PHASE5_WIRING: distributor chute move - irl.chute missing (bin=%s)",
                bin_id,
            )
            return False
        if bin_id == getattr(rules_engine, "reject_bin_id", lambda: "reject")() or bin_id == "reject":
            try:
                passthrough = float(getattr(chute, "first_bin_center", 0.0) or 0.0)
                chute.moveToAngle(passthrough)
                return True
            except Exception:
                logger.exception("distributor: reject-bin move raised")
                return False
        parsed = _parse(bin_id)
        if parsed is None:
            logger.error("distributor: unparseable bin_id=%s", bin_id)
            return False
        layer, section, bin_idx = parsed
        try:
            from irl.chute import BinAddress

            addr = BinAddress(
                layer_index=layer, section_index=section, bin_index=bin_idx
            )
            chute.moveToBin(addr)
            return True
        except Exception:
            logger.exception("distributor: chute.moveToBin raised (bin=%s)", bin_id)
            return False

    _last_target: dict[str, str | None] = {"v": None}

    def position_query() -> str | None:
        chute = getattr(irl, "chute", None)
        if chute is None:
            return None
        # Heuristic: if the chute stepper is "stopped" we report the last
        # commanded bin. Otherwise None = "still moving". This is good enough
        # for the settle window; real angle->bin mapping is chute-specific.
        stepper = getattr(chute, "stepper", None)
        if stepper is None:
            return None
        if bool(getattr(stepper, "stopped", True)):
            return _last_target.get("v")
        return None

    # Wrap move to record the last commanded target so position_query can
    # return it after the stepper settles.
    def _move_and_record(bin_id: str) -> bool:
        _last_target["v"] = bin_id
        return move(bin_id)

    return _move_and_record, position_query


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
    # Cross-cutting subscribers (persistence / projections). Each module
    # owns its own wiring end-to-end.

    from rt.projections.piece_dossier import install as install_piece_dossier

    install_piece_dossier(bus)

    # ------------------------------------------------------------------
    # Perception runners (c2, c3, c4). C1 + Distributor are blind.

    perception_runners: list[PerceptionRunner] = []
    feed_zones: dict[str, Zone] = {}
    perception_sources: dict[str, PerceptionRunner] = {}
    skipped_roles: list[dict[str, str]] = []

    for role in ("c2", "c3", "c4"):
        runner, zone, reason = _build_perception_runner_for_role(
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

            install_segment_recording(bus, runner)

    # ------------------------------------------------------------------
    # Capacity slots

    classification_cfg = getattr(
        getattr(irl, "irl_config", None), "classification_channel_config", None
    ) or getattr(irl, "classification_channel_config", None)
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

    c1_pulse, c1_recovery = _build_c1_callables(irl, log)
    c2_pulse, c2_wiggle = _build_c2_callables(irl, log)
    c3_pulse, c3_wiggle = _build_c3_callables(irl, log)
    (
        c4_carousel_move,
        c4_startup_purge_move,
        c4_startup_purge_mode,
        c4_eject,
    ) = _build_c4_callables(
        irl,
        log,
        startup_purge_speed_scale=float(
            getattr(classification_cfg, "startup_purge_speed_scale", 12.0)
            if classification_cfg
            else 12.0
        ),
    )
    chute_move, chute_position_query = _build_chute_callables(irl, rules_engine, log)

    # ------------------------------------------------------------------
    # Runtime instances

    c1 = RuntimeC1(
        downstream_slot=slots[("c1", "c2")],
        pulse_command=c1_pulse,
        recovery_command=c1_recovery,
        logger=log,
    )
    c2 = RuntimeC2(
        upstream_slot=slots[("c1", "c2")],
        downstream_slot=slots[("c2", "c3")],
        pulse_command=c2_pulse,
        wiggle_command=c2_wiggle,
        admission=AlwaysAdmit(),
        ejection_timing=ConstantPulseEjection(),
        logger=log,
    )
    c3 = RuntimeC3(
        upstream_slot=slots[("c2", "c3")],
        downstream_slot=slots[("c3", "c4")],
        pulse_command=c3_pulse,
        wiggle_command=c3_wiggle,
        admission=AlwaysAdmit(),
        ejection_timing=ConstantPulseEjection(),
        logger=log,
    )
    c4_admission = C4Admission(
        max_zones=max(1, max_zones),
        max_raw_detections=3,
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
            detections = getattr(state, "detections", None) if state is not None else None
            entries = getattr(detections, "detections", None) if detections is not None else None
            if isinstance(entries, (list, tuple)):
                return len(entries)
            raw_tracks = getattr(state, "raw_tracks", None) if state is not None else None
            tracks = getattr(raw_tracks, "tracks", None) if raw_tracks is not None else None
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
        startup_purge_move_command=c4_startup_purge_move,
        startup_purge_mode_command=c4_startup_purge_mode,
        eject_command=c4_eject,
        crop_provider=_crop_provider,
        logger=log,
        event_bus=bus,
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
            c4.on_piece_delivered(piece_uuid, now_mono=0.0)
        except Exception:
            log.exception("rt.bootstrap: c4.on_piece_delivered raised")

    def _on_ack(piece_uuid: str, accepted: bool, reason: str) -> None:
        if accepted:
            _on_delivered(piece_uuid)
        else:
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
    )
    distributor_ref["ref"] = distributor

    # Wire C4 -> Distributor handoff_request.
    # RuntimeC4 does not yet expose a handoff_request_callback attribute
    # (Phase 4 left this as a stub). We attach it dynamically; live wiring
    # on the machine will validate this path. Until C4 calls it, the
    # distributor simply stays IDLE (no damage — chute and C4 just don't
    # exchange pieces).
    if hasattr(c4, "set_handoff_request_callback"):
        try:
            c4.set_handoff_request_callback(distributor.handoff_request)  # type: ignore[attr-defined]
        except Exception:
            log.exception("rt.bootstrap: set_handoff_request_callback failed")
    else:
        # Dynamic attach — C4 poll loop must read `_distributor_handoff`
        # when ready. The attribute is here as an informational hook that
        # live-debug can inspect; it is NOT automatically triggered.
        c4._distributor_handoff = distributor.handoff_request  # type: ignore[attr-defined]
        log.warning(
            "TODO_PHASE5_WIRING: RuntimeC4 has no set_handoff_request_callback; "
            "distributor.handoff_request attached as c4._distributor_handoff — "
            "live wiring must poll this."
        )

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
    log.info(
        "rt.bootstrap: orchestrator ready "
        "(runtimes=c1,c2,c3,c4,distributor; perception_feeds=%s; slots=%s)",
        list(perception_sources.keys()), [f"{u}->{d}" for u, d in slots.keys()],
    )

    return RtRuntimeHandle(
        orchestrator=orch,
        perception_runners=perception_runners,
        event_bus=bus,
        c4=c4,
        distributor=distributor,
        c2=c2,
        c3=c3,
        feed_zones=feed_zones,
        skipped_roles=skipped_roles,
        camera_service=camera_service,
    )


__all__ = ["RtRuntimeHandle", "build_rt_runtime"]
