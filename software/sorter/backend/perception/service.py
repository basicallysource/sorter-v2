"""Boot-time wiring for the perception package.

This is the only place where the immutable construction-time wiring
happens:
  ChannelDef ↔ CaptureWorker ↔ InferenceRuntime ↔ InferenceWorker

After ``PerceptionService.build()`` returns, every inference worker owns
direct references to its capture, its runtime, and its channel def. There
is no further role-string dispatch on the hot path. The
"wrong-camera-on-wrong-NPU-core is impossible" claim rests on this file
and on ``inference.InferenceWorker.__init__``'s source_id check.

This module is the one place perception depends on the rest of the
backend (camera_service, detection_registry, toml_config, blob_manager).
That dependency is read-only at boot — no method here is called on the
hot path.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import numpy as np

from .capture import CaptureWorker
from .channel import CHANNEL_REGISTRY, ChannelDef, loadChannelDefs
from .inference import InferenceWorker, OnExitEdge
from .runtime import InferenceRuntime, RknnYoloRuntime
from .state import ChannelState, EMPTY_STATE, LatestStateSlot


# RK3588 has three NPU cores. We pin each perception channel to a fixed
# core; the order matches CHANNEL_REGISTRY insertion order so C2/C3/C4
# always land on the same cores boot to boot.
_NPU_CORE_NAMES: tuple[str, ...] = ("NPU_CORE_0", "NPU_CORE_1", "NPU_CORE_2")


# Default per-role confidence thresholds. Carousel uses a lower threshold
# because its YOLO model is the looser "any piece" detector; the C-channel
# models are tuned tighter. These match the legacy
# HIVE_CAROUSEL_CONF_THRESHOLD constant. Both are overridable via the
# build() ``conf_thresholds`` argument for tuning runs.
_DEFAULT_CONF_THRESHOLDS: dict[int, float] = {
    2: 0.25,
    3: 0.25,
    4: 0.10,
}


class PerceptionService:
    """Owns the perception workers, slots, and channel defs.

    ``read_states()`` is what the coordinator calls every tick. Three dict
    lookups and three attribute reads — no inference, no convert.
    """

    def __init__(
        self,
        *,
        channels: Dict[int, ChannelDef],
        captures: Dict[int, CaptureWorker],
        runtimes: Dict[int, InferenceRuntime],
        slots: Dict[int, LatestStateSlot],
        workers: Dict[int, InferenceWorker],
    ) -> None:
        self._channels = channels
        self._captures = captures
        self._runtimes = runtimes
        self._slots = slots
        self._workers = workers
        self._started = False
        self._start_lock = threading.Lock()

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                return
            for w in self._workers.values():
                w.start()
            self._started = True

    def stop(self, timeout: float = 2.0) -> None:
        with self._start_lock:
            if not self._started:
                return
            for w in self._workers.values():
                w.stop(timeout=timeout)
            self._started = False

    @property
    def started(self) -> bool:
        return self._started

    # --- hot-path read --------------------------------------------------

    def read_states(self) -> Dict[int, ChannelState]:
        """One tuple/object deref per channel. No inference, no convert."""
        return {ch_id: slot.read() for ch_id, slot in self._slots.items()}

    def read_state(self, channel_id: int) -> ChannelState:
        slot = self._slots.get(channel_id)
        return slot.read() if slot is not None else EMPTY_STATE

    # --- introspection --------------------------------------------------

    def channels(self) -> Dict[int, ChannelDef]:
        return dict(self._channels)

    def workers(self) -> Dict[int, InferenceWorker]:
        return dict(self._workers)

    def source_id_assertion_count(self) -> int:
        return sum(w.source_id_assertions for w in self._workers.values())


# ---------------------------------------------------------------------------
# Boot-time builder
# ---------------------------------------------------------------------------


def _resolve_algorithm_id_per_channel(
    feeder_config: dict | None,
    carousel_config: dict | None,
) -> Dict[int, str]:
    """Return {channel_id: algorithm_id} as configured on disk."""
    out: Dict[int, str] = {}
    feeder_default = (feeder_config or {}).get("algorithm")
    feeder_by_role = (feeder_config or {}).get("algorithm_by_role") or {}
    for ch_id, (role, _polygon_key, _angle_key) in CHANNEL_REGISTRY.items():
        if ch_id == 4:
            algo = (carousel_config or {}).get("algorithm") or feeder_by_role.get(role) or feeder_default
        else:
            algo = feeder_by_role.get(role) or feeder_default
        if isinstance(algo, str) and algo:
            out[ch_id] = algo
    return out


def _wait_for_frame_shapes(
    camera_service: Any, *, timeout_s: float, gc: Any
) -> dict[str, tuple[int, int]]:
    """Poll each registered camera until a frame arrives or the timeout
    elapses. Returns the (H, W) per camera_source_id that have produced
    at least one frame. Missing cameras are left out — the build step
    skips those channels."""
    out: dict[str, tuple[int, int]] = {}
    roles_needed = {role for _, (role, _, _) in CHANNEL_REGISTRY.items()}
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and len(out) < len(roles_needed):
        for ch_id, (role, _polygon_key, _angle_key) in CHANNEL_REGISTRY.items():
            if role in out:
                continue
            cap = camera_service.get_capture_thread_for_role(role)
            if cap is None:
                continue
            shape = _frame_shape_for_capture(cap)
            if shape is not None:
                out[role] = shape
                _log(gc, "info",
                     f"[perception] camera frame for role={role} ready "
                     f"shape={shape} after {time.monotonic() - (deadline - timeout_s):.2f}s")
        if len(out) < len(roles_needed):
            time.sleep(0.1)
    missing = sorted(roles_needed - set(out.keys()))
    if missing:
        _log(gc, "warning",
             f"[perception] camera frames not arriving after {timeout_s:.1f}s "
             f"for roles={missing}; those channels will be skipped at boot")
    return out


def _frame_shape_for_capture(capture_thread: Any) -> Optional[tuple[int, int]]:
    """Best-effort (H, W) from whichever CaptureThread frame is available.

    Polygon masks are sized to the camera's actual frame resolution, not
    a model input size. The first frame may not have arrived yet at boot,
    so this returns None when unavailable; ``loadChannelDefs`` then skips
    that channel. The service caller retries once frames are flowing.
    """
    frame = getattr(capture_thread, "latest_frame", None)
    raw = getattr(frame, "raw", None) if frame is not None else None
    if raw is None:
        return None
    shape = getattr(raw, "shape", None)
    if shape is None or len(shape) < 2:
        return None
    return int(shape[0]), int(shape[1])


def build(
    *,
    gc: Any,
    irl_config: Any,
    camera_service: Any,
    model_path_lookup,                  # callable: algorithm_id -> (model_path, imgsz) or None
    runtime_factory=RknnYoloRuntime,    # injectable for tests
    conf_thresholds: Optional[Dict[int, float]] = None,
    on_c3_exit_edge: Optional[OnExitEdge] = None,
) -> PerceptionService:
    """Construct the full perception service for the new mode pair.

    Reads saved polygons + arcs + per-role algorithm IDs from disk and
    resolves them via ``model_path_lookup`` (a callable provided by the
    caller — typically a thin wrapper around
    ``vision.detection_registry.detection_algorithm_definition`` — so
    perception does not itself import the legacy registry on the hot
    path).

    Channels for which a polygon, an algorithm, or a frame shape is
    unavailable are skipped at boot. The service still starts; the
    cascade treats missing channels as always-empty (``EMPTY_STATE``).
    This is intentional — a fresh boot before homing should not crash
    perception.
    """
    # 1. Saved arc data from disk.
    from blob_manager import (
        getChannelPolygons,
        getFeederDetectionConfig,
        getCarouselDetectionConfig,
    )

    raw_polygons = getChannelPolygons() or {}
    channel_angles = raw_polygons.get("channel_angles") or {}
    arc_params = raw_polygons.get("arc_params") or {}
    # Saved blob shape: { "polygons": {"second_channel": [...], "third_channel": [...],
    #                                  "classification_channel": [...]},
    #                     "channel_angles": {"second": ..., "third": ...,
    #                                        "classification_channel": ...},
    #                     "arc_params": {"second": {drop_zone, exit_zone}, ...} }
    polygon_blob = raw_polygons.get("polygons") or {}
    saved_polygons: dict[str, np.ndarray] = {}
    for key in ("second_channel", "third_channel", "classification_channel"):
        poly = polygon_blob.get(key)
        if poly is None:
            continue
        try:
            saved_polygons[key] = np.asarray(poly)
        except Exception:
            continue

    # 2. Camera frame shapes (need at least one frame in to size the mask).
    # The capture threads start asynchronously; the first frame can be
    # several seconds behind camera_service.start() (V4L2 + gstreamer
    # pipeline negotiation, especially on /dev/video0 with MJPEG). Wait
    # generously, then proceed with whatever has frames — a missing
    # camera does not break the others.
    frame_shape_by_role = _wait_for_frame_shapes(camera_service, timeout_s=15.0, gc=gc)

    channels = loadChannelDefs(
        saved_polygons=saved_polygons,
        channel_angles=channel_angles,
        arc_params=arc_params,
        frame_shape_by_role=frame_shape_by_role,
    )

    # 3. Per-channel algorithm IDs from config → (model_path, imgsz).
    feeder_config = getFeederDetectionConfig()
    carousel_config = getCarouselDetectionConfig()
    algo_by_channel = _resolve_algorithm_id_per_channel(feeder_config, carousel_config)

    # 4. Build the four parallel stacks. NPU core assigned by channel-id
    # order; first channel gets NPU_CORE_0, etc. Channels missing any
    # piece (polygon, algorithm, capture) are skipped here — perception
    # still starts; their slot stays at EMPTY_STATE.
    captures: Dict[int, CaptureWorker] = {}
    runtimes: Dict[int, InferenceRuntime] = {}
    slots: Dict[int, LatestStateSlot] = {}
    workers: Dict[int, InferenceWorker] = {}
    resolved_conf: Dict[int, float] = dict(_DEFAULT_CONF_THRESHOLDS)
    if conf_thresholds:
        resolved_conf.update(conf_thresholds)

    core_order = list(CHANNEL_REGISTRY.keys())
    for idx, ch_id in enumerate(core_order):
        role, _, _ = CHANNEL_REGISTRY[ch_id]
        if ch_id not in channels:
            _log(gc, "warning",
                 f"[perception] channel {ch_id} ({role}) missing polygon/frame_shape; skipping")
            continue
        algo_id = algo_by_channel.get(ch_id)
        if algo_id is None:
            _log(gc, "warning",
                 f"[perception] channel {ch_id} ({role}) has no algorithm configured; skipping")
            continue
        model_info = model_path_lookup(algo_id)
        if model_info is None:
            _log(gc, "warning",
                 f"[perception] channel {ch_id} ({role}) algorithm={algo_id} has no model path; skipping")
            continue
        model_path, imgsz = model_info
        capture_thread = camera_service.get_capture_thread_for_role(role)
        if capture_thread is None:
            _log(gc, "warning",
                 f"[perception] channel {ch_id} ({role}) capture unavailable; skipping")
            continue

        core_name = _NPU_CORE_NAMES[idx % len(_NPU_CORE_NAMES)]
        runtime: InferenceRuntime
        try:
            runtime = runtime_factory(
                model_path=model_path,
                imgsz=int(imgsz),
                core_mask_name=core_name,
                conf_threshold=resolved_conf.get(ch_id, 0.25),
            )
        except Exception as exc:
            _log(gc, "warning",
                 f"[perception] channel {ch_id} ({role}) runtime build failed on {core_name}: {exc}")
            continue
        capture = CaptureWorker(source_id=role, capture_thread=capture_thread)
        slot = LatestStateSlot()
        worker = InferenceWorker(
            capture=capture,
            runtime=runtime,
            channel_def=channels[ch_id],
            slot=slot,
            conf_threshold=resolved_conf.get(ch_id),
            on_exit_edge=on_c3_exit_edge if ch_id == 3 else None,
            runtime_stats=getattr(gc, "runtime_stats", None),
            profiler=getattr(gc, "profiler", None),
            logger=getattr(gc, "logger", None),
        )
        captures[ch_id] = capture
        runtimes[ch_id] = runtime
        slots[ch_id] = slot
        workers[ch_id] = worker
        _log(gc, "info",
             f"[perception] channel {ch_id} ({role}) wired on {core_name} "
             f"with algorithm={algo_id} imgsz={imgsz}")

    return PerceptionService(
        channels=channels,
        captures=captures,
        runtimes=runtimes,
        slots=slots,
        workers=workers,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log(gc: Any, level: str, msg: str) -> None:
    logger = getattr(gc, "logger", None)
    if logger is None:
        return
    fn = getattr(logger, level, None) or getattr(logger, "info", None)
    if fn is None:
        return
    try:
        fn(msg)
    except Exception:
        pass
