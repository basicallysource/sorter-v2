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
from rt.contracts.feed import PolarZone, PolygonZone, RectZone, Zone
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
from rt.perception.pipeline_runner import PerceptionRunner
from rt.perception.runner_builder import build_perception_runner_for_role
from rt.runtimes._strategies import (
    AlwaysAdmit,
    C4Admission,
    C4EjectionTiming,
    C4StartupPurgeStrategy,
    ConstantPulseEjection,
)
from rt.runtimes._zones import ZoneManager
from rt.runtimes.c1 import RuntimeC1
from rt.runtimes.c2 import RuntimeC2
from rt.runtimes.c3 import RuntimeC3
from rt.runtimes.c4 import RuntimeC4
from rt.runtimes.distributor import RuntimeDistributor
from rt.services.maintenance_purge import C234PurgeCoordinator


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

    c1_pulse, c1_recovery = build_c1_callables(irl, log)
    c2_pulse, c2_wiggle = build_c2_callables(irl, log)
    c3_pulse, c3_wiggle = build_c3_callables(irl, log)
    (
        c4_carousel_move,
        c4_startup_purge_move,
        c4_startup_purge_mode,
        c4_eject,
    ) = build_c4_callables(
        irl,
        log,
        startup_purge_speed_scale=float(
            getattr(classification_cfg, "startup_purge_speed_scale", 12.0)
            if classification_cfg
            else 12.0
        ),
    )
    chute_move, chute_position_query = build_chute_callables(irl, rules_engine, log)

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
