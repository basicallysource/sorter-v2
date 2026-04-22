"""RT runtime bootstrap — wiring for `RT_RUNTIME=1`.

Builds the full 5-runtime graph (C1 -> C2 -> C3 -> C4 -> Distributor) with
perception runners, capacity slots, classifier, rules engine, event bus,
and hardware-facing callables that bridge into the legacy ``irl.*`` stack.

This module is the **single** place that reaches into the legacy hardware
API from the rt/ tree; every other rt/ file stays bridge-free. Bridge
imports here are kept local to the builder functions and marked clearly.

Call :func:`build_rt_runtime` once (after the legacy
``CameraService``/``VisionManager`` are running and hardware is homed) to
get an :class:`RtRuntimeHandle` with ``.start()``/``.stop()`` lifecycle.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import rt.perception  # noqa: F401 - register detectors/trackers/filters
import rt.rules  # noqa: F401 - register rules engines
from rt.classification.brickognize import BrickognizeClient
from rt.config.schema import FilterConfig, PipelineConfig
from rt.contracts.events import Event
from rt.contracts.feed import PolygonZone, RectZone, Zone
from rt.contracts.registry import (
    CLASSIFIERS,
    RULES_ENGINES,
)
from rt.coupling.orchestrator import Orchestrator
from rt.coupling.slots import CapacitySlot
from rt.events.bus import InProcessEventBus
from rt.events.topics import (
    PIECE_CLASSIFIED,
    PIECE_DISTRIBUTED,
    PIECE_REGISTERED,
)
from rt.perception.detectors.hive_onnx import default_hive_detector_slug
from rt.perception.feeds import CameraFeed
from rt.perception.pipeline import build_pipeline_from_config
from rt.perception.pipeline_runner import PerceptionRunner
from rt.runtimes._strategies import (
    AlwaysAdmit,
    C4Admission,
    C4EjectionTiming,
    ConstantPulseEjection,
)
from rt.runtimes._zones import ZoneManager
from rt.runtimes.c1 import RuntimeC1
from rt.runtimes.c2 import RuntimeC2
from rt.runtimes.c3 import RuntimeC3
from rt.runtimes.c4 import RuntimeC4
from rt.runtimes.distributor import RuntimeDistributor


# Mapping rt-side role slug -> legacy camera_service role name.
_ROLE_TO_LEGACY_CAMERA: dict[str, str] = {
    "c2": "c_channel_2",
    "c3": "c_channel_3",
    "c4": "carousel",
}


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
    feed_zones: dict[str, Zone] = field(default_factory=dict)
    started: bool = False
    paused: bool = False

    def start(self) -> None:
        if self.started:
            return
        self.event_bus.start()
        for runner in self.perception_runners:
            runner.start()
        self.orchestrator.start()
        self.started = True

    def stop(self) -> None:
        if not self.started:
            return
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

    Prefers per-channel metadata embedded by the zone editor; falls back to
    the blob's global ``resolution`` field, then to 1920x1080.
    """
    if isinstance(saved, dict):
        if channel_key:
            channels = saved.get("channels")
            if isinstance(channels, dict):
                entry = channels.get(channel_key)
                if isinstance(entry, dict):
                    res = entry.get("resolution")
                    if isinstance(res, (list, tuple)) and len(res) >= 2:
                        return list(res)
        res = saved.get("resolution")
        if isinstance(res, (list, tuple)) and len(res) >= 2:
            return list(res)
    return [1920, 1080]


def _channel_angle_key_for_polygon_key(polygon_key: str) -> str | None:
    if polygon_key == "second_channel":
        return "second"
    if polygon_key == "third_channel":
        return "third"
    if polygon_key == "classification_channel":
        return "classification_channel"
    return None


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


def _load_zone_for_role(
    role: str,
    camera_service: Any,
    logger: logging.Logger,
) -> Zone | None:
    legacy_role = _ROLE_TO_LEGACY_CAMERA.get(role, role)
    h: int | None = None
    w: int | None = None

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

    if h is None or w is None:
        get_feed = getattr(camera_service, "get_feed", None)
        if callable(get_feed):
            try:
                feed = get_feed(legacy_role)
            except Exception:
                feed = None
            get_frame = getattr(feed, "get_frame", None) if feed is not None else None
            if callable(get_frame):
                try:
                    cframe = get_frame(annotated=False)
                except TypeError:
                    cframe = get_frame()
                except Exception:
                    cframe = None
                raw = getattr(cframe, "raw", None) if cframe is not None else None
                if raw is not None and hasattr(raw, "shape"):
                    h, w = int(raw.shape[0]), int(raw.shape[1])

    if h is None or w is None:
        logger.warning(
            "rt.bootstrap[%s]: no live frame yet on %r — zone unavailable",
            role, legacy_role,
        )
        return None

    polygon_key = _channel_polygon_key_for_role(legacy_role)
    polygon = None
    if polygon_key:
        try:
            polygon = _load_saved_polygon(polygon_key, w, h)
        except Exception:
            polygon = None

    if polygon is not None and len(polygon) >= 3:
        vertices = tuple((int(p[0]), int(p[1])) for p in polygon)
        return PolygonZone(vertices=vertices)

    logger.warning(
        "rt.bootstrap[%s]: no polygon for %r — falling back to full-frame %dx%d",
        role, polygon_key, w, h,
    )
    return RectZone(x=0, y=0, w=w, h=h)


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
    irl: Any, logger: logging.Logger
) -> tuple[Callable[[float], bool], Callable[[], bool]]:
    def carousel_move(deg: float) -> bool:
        stepper = getattr(irl, "carousel_stepper", None)
        if stepper is None:
            logger.error("TODO_PHASE5_WIRING: c4 carousel move - stepper missing")
            return False
        try:
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC4: carousel_move raised")
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

    return carousel_move, eject


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
    # Persistent piece-dossier + Hive upload side-effect bridge.
    # Uses the existing local_state helper so pieces still land in the
    # SQLite dossier table the UI / SetProgressSync worker reads from.

    try:
        from local_state import remember_piece_dossier

        def _on_piece_event(event: Event) -> None:
            try:
                remember_piece_dossier(dict(event.payload))
            except Exception:
                log.debug("rt.bootstrap: remember_piece_dossier raised", exc_info=True)

        for topic in (PIECE_REGISTERED, PIECE_CLASSIFIED, PIECE_DISTRIBUTED):
            bus.subscribe(topic, _on_piece_event)
    except Exception:
        log.warning(
            "rt.bootstrap: could not wire remember_piece_dossier sink (non-fatal)"
        )

    # ------------------------------------------------------------------
    # Perception runners (c2, c3, c4). C1 + Distributor are blind.

    perception_runners: list[PerceptionRunner] = []
    feed_zones: dict[str, Zone] = {}
    perception_sources: dict[str, PerceptionRunner] = {}

    detector_slug = default_hive_detector_slug()

    for role in ("c2", "c3", "c4"):
        zone = _load_zone_for_role(role, camera_service, log)
        if zone is None:
            log.warning(
                "rt.bootstrap[%s]: no zone available — skipping perception runner",
                role,
            )
            continue
        feed_id = f"{role}_feed"
        camera_id = _ROLE_TO_LEGACY_CAMERA.get(role, role)
        purpose = {"c2": "c2_feed", "c3": "c3_feed", "c4": "c4_feed"}[role]
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
            log.exception("rt.bootstrap[%s]: CameraFeed build failed", role)
            continue
        pipeline_config = PipelineConfig(
            feed_id=feed_id,
            detector={
                "key": detector_slug,
                "params": {"conf_threshold": 0.25, "iou_threshold": 0.45},
            },
            tracker={"key": "polar", "params": {}},
            filters=[
                FilterConfig(key="size", params={"min_area_px": 400}),
                FilterConfig(key="ghost", params={"confirmed_real_only": True}),
            ],
        )
        try:
            pipeline = build_pipeline_from_config(pipeline_config, feed, zone)
        except Exception:
            log.exception(
                "rt.bootstrap[%s]: pipeline build failed (detector=%s)",
                role, detector_slug,
            )
            continue
        runner = PerceptionRunner(
            pipeline=pipeline,
            period_ms=200,
            event_bus=bus,
            name=f"RtPerception[{role}]",
        )
        perception_runners.append(runner)
        feed_zones[feed_id] = zone
        perception_sources[feed_id] = runner
        log.info(
            "rt.bootstrap[%s]: perception runner ready (feed=%s, detector=%s)",
            role, feed_id, detector_slug,
        )

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

    zone_manager = ZoneManager(
        max_zones=max(1, max_zones),
        intake_angle_deg=intake_angle,
        guard_angle_deg=guard_angle,
        default_half_width_deg=intake_half_width,
    )

    # ------------------------------------------------------------------
    # Hardware callables

    c1_pulse, c1_recovery = _build_c1_callables(irl, log)
    c2_pulse, c2_wiggle = _build_c2_callables(irl, log)
    c3_pulse, c3_wiggle = _build_c3_callables(irl, log)
    c4_carousel_move, c4_eject = _build_c4_callables(irl, log)
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

    c4 = RuntimeC4(
        upstream_slot=slots[("c3", "c4")],
        downstream_slot=slots[("c4", "distributor")],
        zone_manager=zone_manager,
        classifier=classifier,
        admission=c4_admission,
        ejection=c4_ejection,
        carousel_move_command=c4_carousel_move,
        eject_command=c4_eject,
        crop_provider=_crop_provider,
        logger=log,
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
        feed_zones=feed_zones,
    )


__all__ = ["RtRuntimeHandle", "build_rt_runtime"]
