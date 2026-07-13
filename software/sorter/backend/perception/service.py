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

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np

from .arcs import bboxInsideChannelMask
from .capture import CaptureWorker
from .channel import CHANNEL_REGISTRY, SECTION_DEG, ChannelDef, channelDefFromBlob
from .inference import InferenceWorker, OnExitEdge
from .overlay import renderFeedOverlay
from .runtime import InferenceRuntime, RknnYoloRuntime
from .state import ChannelState, EMPTY_STATE, LatestStateSlot


# How often the reconcile loop re-reads the saved zone/camera/algorithm state
# and late-binds channels whose camera was not ready at boot. UI edits poke
# ``request_reconcile()`` for sub-second pickup; this is the fallback cadence
# (and the only trigger for a camera that simply starts producing frames).
_RECONCILE_INTERVAL_S = 2.0


# The classification camera is registered under source id "carousel" while
# configs/UI may name the role "classification_channel" — treat them as one.
_PERCEPTION_ROLE_ALIASES = {
    "carousel": "classification_channel",
    "classification_channel": "carousel",
}


def is_perception_role(role: str) -> bool:
    """Whether a camera role belongs to the perception stack — a STATIC fact
    from ``CHANNEL_REGISTRY``, with NO dependency on a built service instance.
    The feed endpoint uses this so a perception role is routed to the perception
    renderer even on a fresh boot before ``PerceptionService`` exists (it shows
    raw video until perception is ready, never the legacy VisionManager
    overlay)."""
    registry_sources = {src for (src, _poly, _ang) in CHANNEL_REGISTRY.values()}
    for candidate in (role, _PERCEPTION_ROLE_ALIASES.get(role)):
        if candidate is not None and candidate in registry_sources:
            return True
    return False


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
        context: Optional["_ReconcileContext"] = None,
        fingerprints: Optional[Dict[int, "_ChannelFingerprint"]] = None,
    ) -> None:
        self._channels = channels
        self._captures = captures
        self._runtimes = runtimes
        self._slots = slots
        self._workers = workers
        self._started = False
        self._start_lock = threading.RLock()

        # Live-feed preview cache. The overlay is composited at most ONCE per
        # inference frame (keyed by frame timestamp + preview width) and shared
        # across every streaming client, instead of re-rendering on every poll.
        self._preview_lock = threading.Lock()
        self._preview_cache: Dict[int, tuple[float, int, np.ndarray]] = {}

        # Reconcile machinery. ``context`` carries everything needed to
        # (re)build a single channel stack from disk at runtime; ``None`` (test
        # construction) disables live reconcile entirely. ``_fingerprints``
        # records the input signature each wired channel was last built from so
        # the loop only rebuilds when something the operator changed actually
        # moved.
        self._context = context
        self._fingerprints: Dict[int, _ChannelFingerprint] = dict(fingerprints or {})
        self._reconcile_stop = threading.Event()
        self._reconcile_wake = threading.Event()
        self._reconcile_thread: Optional[threading.Thread] = None

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        with self._start_lock:
            # Idempotent: ``build()`` may already have started workers via its
            # initial reconcile. Start only threads that are not yet alive.
            for w in self._workers.values():
                if not w.is_alive:
                    w.start()
            self._started = True
            if self._context is not None and self._reconcile_thread is None:
                self._reconcile_stop.clear()
                self._reconcile_thread = threading.Thread(
                    target=self._reconcile_loop,
                    daemon=True,
                    name="perception-reconcile",
                )
                self._reconcile_thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._start_lock:
            if not self._started:
                return
            self._reconcile_stop.set()
            self._reconcile_wake.set()
            for w in self._workers.values():
                w.stop(timeout=timeout)
            self._started = False
        thread = self._reconcile_thread
        if thread is not None:
            thread.join(timeout=timeout)
            self._reconcile_thread = None

    @property
    def started(self) -> bool:
        return self._started

    # --- live reconcile -------------------------------------------------

    def request_reconcile(self) -> None:
        """Ask the reconcile loop to re-read disk state on its next wake — call
        this from the UI save endpoints (zone editor, camera assignment,
        detection-config) so edits are picked up within a fraction of a second
        instead of waiting the full poll interval. No-op if reconcile is
        disabled (test construction) or the loop has not started yet."""
        self._reconcile_wake.set()

    def _reconcile_loop(self) -> None:
        ctx = self._context
        logger = getattr(ctx.gc, "logger", None) if ctx is not None else None
        while not self._reconcile_stop.is_set():
            self._reconcile_wake.wait(timeout=_RECONCILE_INTERVAL_S)
            self._reconcile_wake.clear()
            if self._reconcile_stop.is_set():
                break
            try:
                self.reconcile()
            except Exception as exc:
                if logger is not None:
                    try:
                        logger.warning(f"[perception] reconcile pass failed: {exc}")
                    except Exception:
                        pass

    def reconcile(self) -> None:
        """Re-read the saved zones / camera assignment / algorithm config and
        bring every channel into line with it, rebuilding only what changed.

        - A channel whose camera was not ready at boot is wired the moment its
          first frame arrives (no restart, no fixed boot timeout).
        - A zone edit rebuilds just that channel's ``ChannelDef`` and reuses the
          already-loaded RKNN runtime — fast, no model reload, no NPU thrash.
        - An algorithm change rebuilds the runtime on the channel's fixed NPU
          core.

        The hot path stays immutable: workers are never mutated in place. New
        per-channel stacks are built, then the service's channel→worker dicts
        are atomically rebound under the start lock (the coordinator's
        ``read_states`` captures the old dict for the duration of its tick)."""
        ctx = self._context
        if ctx is None or self._reconcile_stop.is_set():
            return
        disk = _read_disk_inputs(ctx.gc)
        with self._start_lock:
            if self._reconcile_stop.is_set():
                return
            new_channels = dict(self._channels)
            new_captures = dict(self._captures)
            new_runtimes = dict(self._runtimes)
            new_slots = dict(self._slots)
            new_workers = dict(self._workers)
            retired_runtimes: list[InferenceRuntime] = []
            changed = False

            for channel_id in CHANNEL_REGISTRY:
                gathered = _gather_channel(ctx, channel_id, disk)
                if gathered is None:
                    # Missing polygon / no frame yet / no algorithm. Leave any
                    # existing worker running; do not tear a channel down just
                    # because its camera momentarily dropped a frame.
                    continue
                prev = self._fingerprints.get(channel_id)
                already_wired = channel_id in self._workers
                if already_wired and prev == gathered.fingerprint:
                    continue

                channel_def = channelDefFromBlob(
                    channel_id,
                    saved_polygons=disk.saved_polygons,
                    channel_angles=disk.channel_angles,
                    arc_params=disk.arc_params,
                    frame_shape=gathered.frame_shape,
                    secondary_zones=disk.secondary_zones,
                )
                if channel_def is None:
                    continue

                reuse_runtime = (
                    prev is not None
                    and prev.runtime == gathered.fingerprint.runtime
                    and self._runtimes.get(channel_id) is not None
                )
                runtime = self._runtimes.get(channel_id) if reuse_runtime else None
                if runtime is None:
                    try:
                        runtime = ctx.runtime_factory(
                            model_path=gathered.model_path,
                            imgsz=int(gathered.imgsz),
                            core_mask_name=gathered.core_name,
                            conf_threshold=gathered.conf,
                        )
                    except Exception as exc:
                        _log(ctx.gc, "warning",
                             f"[perception] channel {channel_id} ({gathered.role}) "
                             f"runtime rebuild failed on {gathered.core_name}: {exc}")
                        continue

                slot = self._slots.get(channel_id) or LatestStateSlot()
                capture = CaptureWorker(
                    source_id=gathered.role, capture_thread=gathered.capture_thread
                )
                worker = InferenceWorker(
                    capture=capture,
                    runtime=runtime,
                    channel_def=channel_def,
                    slot=slot,
                    conf_threshold=gathered.conf,
                    on_exit_edge=ctx.on_c3_exit_edge if channel_id == 3 else None,
                    runtime_stats=getattr(ctx.gc, "runtime_stats", None),
                    profiler=getattr(ctx.gc, "profiler", None),
                    logger=getattr(ctx.gc, "logger", None),
                    log_attribution=getattr(ctx.gc, "log_perception_attribution", False),
                )

                # Stop the outgoing worker BEFORE starting the new one: both
                # read the same camera and (when the runtime is reused) share
                # one RKNN context on one NPU core, which must not run two
                # threads at once.
                old_worker = self._workers.get(channel_id)
                if old_worker is not None:
                    old_worker.stop(timeout=2.0)
                worker.start()
                old_runtime = self._runtimes.get(channel_id)
                if not reuse_runtime and old_runtime is not None:
                    retired_runtimes.append(old_runtime)

                new_channels[channel_id] = channel_def
                new_captures[channel_id] = capture
                new_runtimes[channel_id] = runtime
                new_slots[channel_id] = slot
                new_workers[channel_id] = worker
                self._fingerprints[channel_id] = gathered.fingerprint
                changed = True
                _log(ctx.gc, "info",
                     f"[perception] channel {channel_id} ({gathered.role}) "
                     f"{'rewired' if already_wired else 'wired'} on {gathered.core_name} "
                     f"algorithm={gathered.algorithm_id} imgsz={gathered.imgsz} "
                     f"frame={gathered.frame_shape[1]}x{gathered.frame_shape[0]} "
                     f"runtime={'reused' if reuse_runtime else 'rebuilt'} "
                     f"center={channel_def.center} "
                     f"|drop|={len(channel_def.drop_sections)} "
                     f"|exit|={len(channel_def.exit_sections)} "
                     f"|precise|={len(channel_def.precise_sections)}")

            if changed:
                # Atomic rebind — a concurrent read_states() iterates whichever
                # dict it captured at the start of its tick; it never sees a
                # half-updated mapping.
                self._channels = new_channels
                self._captures = new_captures
                self._runtimes = new_runtimes
                self._slots = new_slots
                self._workers = new_workers

        # Release replaced RKNN runtimes outside the lock (best effort).
        for dead_runtime in retired_runtimes:
            _release_runtime(dead_runtime)

    # --- hot-path read --------------------------------------------------

    def read_states(self) -> Dict[int, ChannelState]:
        """One tuple/object deref per channel. No inference, no convert."""
        return {ch_id: slot.read() for ch_id, slot in self._slots.items()}

    def read_state(self, channel_id: int) -> ChannelState:
        slot = self._slots.get(channel_id)
        return slot.read() if slot is not None else EMPTY_STATE

    def read_bboxes_and_frame(self, channel_id: int):
        """Latest ``(on_channel_bboxes, PerceptionFrame)`` from the last
        inference cycle for this channel. Returns ``None`` if the worker hasn't
        completed a cycle yet.

        Bboxes are filtered to those whose center lies inside the channel's
        saved polygon mask — the same center-in-polygon membership test the
        legacy ``bboxesAndFrameOnChannel`` applied. Without this filter a large
        YOLO detection OUTSIDE the annotated channel region (e.g. the
        loose-brick hopper in the frame corner) can win ``primaryBbox`` and get
        cropped/recognized as if it were the carousel piece.

        The filter is a single mask index per bbox, so it stays cheap enough to
        run on the coordinator thread (see the perception perf rules).
        GIL-atomic read of ``latest_raw``; callers must not mutate the result."""
        worker = self._workers.get(channel_id)
        if worker is None:
            return None
        raw = worker.latest_raw
        if raw is None:
            return None
        bboxes, frame = raw
        channel = self._channels.get(channel_id)
        if channel is None:
            return raw
        on_channel = [b for b in bboxes if bboxInsideChannelMask(b, channel)]
        return on_channel, frame

    def read_pieces_and_frame(self, channel_id: int):
        """Latest ``(pieces, PerceptionFrame)`` for this channel — the per-piece
        PieceObservation tuple (bbox + com_forward_to_exit_deg + zone_code +
        sv_bt_track_id) with the exact frame it was computed against, written
        together in the worker's hot loop. Returns ``None`` if the worker hasn't
        completed a cycle yet. GIL-atomic read; callers must not mutate."""
        worker = self._workers.get(channel_id)
        if worker is None:
            return None
        return worker.latest_pieces_frame

    def read_detections(self, channel_id: int):
        """Latest in-crop ``Detection`` list for this channel, each tagged with
        ``in_primary`` and the secondary-zone ids it falls in. Display/tag only —
        the state machine still reads the primary-only slot / ``latest_raw``.
        Returns ``None`` if the channel isn't wired or hasn't produced a cycle."""
        worker = self._workers.get(channel_id)
        if worker is None:
            return None
        return worker.latest_detections

    def secondary_zone_occupied(
        self,
        channel_id: int,
        *,
        source_channel: Optional[int] = None,
        zone_type: Optional[str] = None,
    ) -> bool:
        """Does ``channel_id``'s camera currently see a piece inside a secondary
        (foreign) zone matching the filter? e.g. ``secondary_zone_occupied(4,
        source_channel=3)`` answers "does the classification camera see a piece in
        C3's annotated exit/precise zone." Returns ``False`` when the channel is
        unwired, has no matching secondary zone, or has produced no detection yet
        — so a consumer that gates on this is a no-op until a zone is drawn.
        Cheap: a handful of set lookups over the last cycle's tagged detections."""
        worker = self._workers.get(channel_id)
        channel = self._channels.get(channel_id)
        if worker is None or channel is None:
            return False
        matching_ids = {
            z.id
            for z in channel.secondary_zones
            if (source_channel is None or z.source_channel == source_channel)
            and (zone_type is None or z.zone_type == zone_type)
        }
        if not matching_ids:
            return False
        detections = worker.latest_detections
        if not detections:
            return False
        for d in detections:
            if any(sid in matching_ids for sid in d.secondary_zone_ids):
                return True
        return False

    def channel_center(self, channel_id: int):
        """Center pixel of the channel's rotation arc as ``(cx, cy)``, or
        ``None`` if the channel isn't wired in this service instance."""
        ch = self._channels.get(channel_id)
        return ch.center if ch is not None else None

    def precise_zone_len_deg(self, channel_id: int) -> float:
        """Angular length (output degrees) of this channel's precise sub-arc, or
        0.0 if the channel isn't wired / has no precise zone. Static per channel
        (sections are immutable on the ChannelDef). The fast-eject controller
        uses this as the default trigger distance when the tuning value is 0."""
        ch = self._channels.get(channel_id)
        if ch is None:
            return 0.0
        return float(len(ch.precise_sections)) * SECTION_DEG

    # --- introspection --------------------------------------------------

    def channels(self) -> Dict[int, ChannelDef]:
        return dict(self._channels)

    def workers(self) -> Dict[int, InferenceWorker]:
        return dict(self._workers)

    def captures(self) -> Dict[int, CaptureWorker]:
        return dict(self._captures)

    def runtimes(self) -> Dict[int, InferenceRuntime]:
        return dict(self._runtimes)

    def source_id_assertion_count(self) -> int:
        return sum(w.source_id_assertions for w in self._workers.values())

    def channel_id_for_source(self, camera_source_id: str) -> Optional[int]:
        for channel_id, channel in self._channels.items():
            if channel.camera_source_id == camera_source_id:
                return channel_id
        return None

    def owns_role(self, role: str) -> bool:
        """Whether this camera role belongs to the perception stack — a STATIC
        fact from ``CHANNEL_REGISTRY``, independent of whether the channel has
        finished building. The feed endpoint uses this to decide the stack ONCE:
        a perception role's annotations come only from perception, never the
        legacy VisionManager overlay, even while the channel is still warming up
        (in which case the feed shows raw video, not someone else's boxes)."""
        return is_perception_role(role)

    def channel_id_for_role(self, role: str) -> Optional[int]:
        """Built channel id for a role (with the carousel/classification alias),
        or ``None`` if the channel is not built yet. Stack ownership is
        ``owns_role``; this only answers "can perception render it right now"."""
        for candidate in (role, _PERCEPTION_ROLE_ALIASES.get(role)):
            if candidate is None:
                continue
            channel_id = self.channel_id_for_source(candidate)
            if channel_id is not None:
                return channel_id
        return None

    def preview_frame(self, channel_id: int, max_width: int = 0):
        """``(annotated_bgr, frame_timestamp)`` for the live feed — the clean
        operating overlay (zones + on-channel boxes the machine acts on) drawn
        on the exact frame the model inferred against, so boxes never drift off
        the pixels. Reuses the last inference cycle; runs NO new inference.

        Rendered at ``max_width`` (preview resolution) and cached per inference
        frame: no matter how many clients stream or how fast they poll, the
        overlay is composited at most once per inference cycle. ``None`` until
        the worker has completed a cycle."""
        worker = self._workers.get(channel_id)
        channel = self._channels.get(channel_id)
        if worker is None or channel is None:
            return None
        debug = worker.latest_debug
        if debug is None:
            return None
        frame = debug.get("frame")
        if frame is None:
            return None
        ts = float(frame.timestamp)
        with self._preview_lock:
            cached = self._preview_cache.get(channel_id)
            if cached is not None and cached[0] == ts and cached[1] == max_width:
                return cached[2], ts
        annotated = renderFeedOverlay(
            frame.bgr,
            channel,
            # Originals (what the model drew) in green; on C4 the merged boxes we
            # actually act on are overlaid distinctly via merged_bboxes.
            debug.get("pre_merge_bboxes") or debug.get("on_channel_bboxes") or [],
            detections=debug.get("detections"),
            max_width=max_width,
            merged_bboxes=debug.get("merged_bboxes"),
            merged_track_ids=debug.get("merged_track_ids"),
        )
        with self._preview_lock:
            self._preview_cache[channel_id] = (ts, max_width, annotated)
        return annotated, ts

    def request_full_frame_debug(self, channel_id: int, ttl_s: float = 10.0) -> bool:
        """Turn on the worker's on-demand full-frame (uncropped) inference for a
        few seconds. Returns False if the channel isn't wired. Self-expires so
        the extra inference stops once the debug page stops polling."""
        worker = self._workers.get(channel_id)
        if worker is None:
            return False
        worker.request_full_frame_debug(ttl_s=ttl_s)
        return True

    def channel_debug_info(self, channel_id: int) -> Optional[dict]:
        """Everything the perception-debug overlay needs for one channel: the
        last frame the worker inferred against, the RAW (pre-filter) bboxes and
        the on-channel subset, the crop rect, and the exact model + camera the
        detections came from. Returns ``None`` if the channel isn't wired or has
        not completed an inference cycle. Read-only — no inference triggered."""
        worker = self._workers.get(channel_id)
        channel = self._channels.get(channel_id)
        if worker is None or channel is None:
            return None
        debug = worker.latest_debug
        if debug is None:
            return None
        runtime = self._runtimes.get(channel_id)
        fp = self._fingerprints.get(channel_id)
        capture = self._captures.get(channel_id)
        camera_source = None
        if capture is not None:
            getter = getattr(getattr(capture, "capture_thread", None), "getCameraSource", None)
            if callable(getter):
                try:
                    camera_source = getter()
                except Exception:
                    camera_source = None
        model_path = getattr(runtime, "model_path", None)
        model_name = str(model_path).rsplit("/", 1)[-1] if model_path else None
        return {
            "channel_id": channel_id,
            "camera_source_id": channel.camera_source_id,
            "camera_source": camera_source,
            "algorithm_id": fp.runtime[0] if fp is not None else None,
            "model_path": str(model_path) if model_path is not None else None,
            "model_name": model_name,
            "imgsz": getattr(runtime, "imgsz", None),
            "conf_threshold": getattr(runtime, "conf_threshold", debug.get("conf_threshold")),
            "iou_threshold": getattr(runtime, "iou_threshold", None),
            "core_mask_name": getattr(runtime, "core_mask_name", None),
            "raw_bboxes": debug.get("raw_bboxes") or [],
            "on_channel_bboxes": debug.get("on_channel_bboxes") or [],
            # sv_bt_track_id per on-channel bbox, index-aligned to on_channel_bboxes.
            "on_channel_track_ids": debug.get("on_channel_track_ids") or [],
            # Persisted full-frame result (its OWN frame, so the overlay's boxes
            # line up). None until the on-demand full-frame pass has run once.
            "full_frame": worker.latest_full_frame,
            "crop_rect": debug.get("crop_rect"),
            "infer_ms": debug.get("infer_ms"),
            "frame": debug.get("frame"),
            "center": channel.center,
            "mask_shape": tuple(channel.mask.shape[:2]),
            "n_drop_sections": len(channel.drop_sections),
            "n_exit_sections": len(channel.exit_sections),
            "n_precise_sections": len(channel.precise_sections),
        }


# ---------------------------------------------------------------------------
# Boot-time builder
# ---------------------------------------------------------------------------


def _resolve_algorithm_id_per_channel(
    feeder_config: dict | None,
    carousel_config: dict | None,
) -> Dict[int, str]:
    """Return {channel_id: algorithm_id}, read 1:1 from each subsystem's own
    TOML slot — NO fallback. ch4 (the classification C4 / carousel station)
    reads ``detection.carousel.algorithm``; the C-channels read their own
    ``detection.feeder.algorithm_by_role`` entry. An unset slot leaves that
    channel unwired (no detector) rather than silently inheriting another
    subsystem's model — the operator picks a model per subsystem explicitly."""
    out: Dict[int, str] = {}
    feeder_by_role = (feeder_config or {}).get("algorithm_by_role") or {}
    for ch_id, (role, _polygon_key, _angle_key) in CHANNEL_REGISTRY.items():
        if ch_id == 4:
            algo = (carousel_config or {}).get("algorithm")
        else:
            algo = feeder_by_role.get(role)
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


# Channel-id order fixes the NPU-core assignment: the Nth registered channel
# always lands on core N, boot to boot and rewire to rewire. A channel that is
# late-bound by the reconcile loop therefore gets the same core it would have
# gotten at boot.
_CORE_ORDER: tuple[int, ...] = tuple(CHANNEL_REGISTRY.keys())


def _core_for_channel(channel_id: int) -> str:
    return _NPU_CORE_NAMES[_CORE_ORDER.index(channel_id) % len(_NPU_CORE_NAMES)]


@dataclass(frozen=True)
class _ReconcileContext:
    """Everything ``reconcile()`` needs to (re)build a single channel from disk
    at runtime. Built once in ``build()`` and handed to the service; immutable."""

    gc: Any
    camera_service: Any
    model_path_lookup: Any
    runtime_factory: Any
    resolved_conf: Dict[int, float]
    on_c3_exit_edge: Optional[OnExitEdge]


@dataclass(frozen=True)
class _ChannelFingerprint:
    """Signature of the inputs a wired channel was built from. ``runtime`` is
    compared on its own so a zone-only edit reuses the loaded RKNN runtime
    (no model reload); ``worker`` covers the rest (zones, camera, conf)."""

    runtime: tuple
    worker: tuple


@dataclass(frozen=True)
class _DiskInputs:
    saved_polygons: Dict[str, np.ndarray]
    channel_angles: dict
    arc_params: dict
    algo_by_channel: Dict[int, str]
    secondary_zones: dict


@dataclass(frozen=True)
class _GatheredChannel:
    role: str
    capture_thread: Any
    frame_shape: tuple[int, int]
    algorithm_id: str
    model_path: Any
    imgsz: int
    core_name: str
    conf: float
    fingerprint: _ChannelFingerprint


def _read_disk_inputs(gc: Any) -> _DiskInputs:
    """Read the saved zone blob + detection config that perception is driven
    by. Cheap (small JSON via blob_manager) — safe to call every reconcile
    pass and on every UI-save poke.

    Saved blob shape: { "polygons": {"second_channel": [...], ...},
                        "channel_angles": {"second": ..., ...},
                        "arc_params": {"second": {drop_zone, exit_zone, ...}, ...} }
    """
    from blob_manager import (
        getChannelPolygons,
        getFeederDetectionConfig,
        getCarouselDetectionConfig,
    )

    raw_polygons = getChannelPolygons() or {}
    channel_angles = raw_polygons.get("channel_angles") or {}
    arc_params = raw_polygons.get("arc_params") or {}
    secondary_zones = raw_polygons.get("secondary_zones") or {}
    polygon_blob = raw_polygons.get("polygons") or {}
    saved_polygons: Dict[str, np.ndarray] = {}
    for key in ("second_channel", "third_channel", "classification_channel"):
        poly = polygon_blob.get(key)
        if poly is None:
            continue
        try:
            saved_polygons[key] = np.asarray(poly)
        except Exception:
            continue
    algo_by_channel = _resolve_algorithm_id_per_channel(
        getFeederDetectionConfig(), getCarouselDetectionConfig()
    )
    return _DiskInputs(
        saved_polygons=saved_polygons,
        channel_angles=channel_angles,
        arc_params=arc_params,
        algo_by_channel=algo_by_channel,
        secondary_zones=secondary_zones if isinstance(secondary_zones, dict) else {},
    )


def _gather_channel(
    ctx: _ReconcileContext, channel_id: int, disk: _DiskInputs
) -> Optional[_GatheredChannel]:
    """Resolve everything one channel needs right now — polygon, live camera +
    frame shape, algorithm → model — plus the input fingerprint. Returns
    ``None`` when any piece is missing (no polygon, camera not producing frames
    yet, no algorithm/model) so the channel is simply left unwired this pass."""
    role, polygon_key, angle_key = CHANNEL_REGISTRY[channel_id]
    polygon = disk.saved_polygons.get(polygon_key)
    if polygon is None or len(polygon) < 3:
        return None
    capture_thread = ctx.camera_service.get_capture_thread_for_role(role)
    if capture_thread is None:
        return None
    frame_shape = _frame_shape_for_capture(capture_thread)
    if frame_shape is None:
        return None
    algorithm_id = disk.algo_by_channel.get(channel_id)
    if not algorithm_id:
        return None
    model_info = ctx.model_path_lookup(algorithm_id)
    if model_info is None:
        return None
    model_path, imgsz = model_info
    core_name = _core_for_channel(channel_id)
    conf = float(ctx.resolved_conf.get(channel_id, 0.25))
    arc_entry = disk.arc_params.get(polygon_key) or disk.arc_params.get(angle_key)
    secondary_entry = disk.secondary_zones.get(polygon_key)
    poly_arr = np.asarray(polygon)
    cd_hash = hashlib.md5(
        poly_arr.tobytes()
        + repr(arc_entry).encode("utf-8", "replace")
        + repr(secondary_entry).encode("utf-8", "replace")
        + repr(float(disk.channel_angles.get(angle_key, 0.0))).encode()
        + repr(tuple(frame_shape)).encode()
    ).hexdigest()
    fingerprint = _ChannelFingerprint(
        runtime=(algorithm_id, str(model_path), int(imgsz), core_name, conf),
        worker=(cd_hash, id(capture_thread), conf),
    )
    return _GatheredChannel(
        role=role,
        capture_thread=capture_thread,
        frame_shape=frame_shape,
        algorithm_id=algorithm_id,
        model_path=model_path,
        imgsz=int(imgsz),
        core_name=core_name,
        conf=conf,
        fingerprint=fingerprint,
    )


def _release_runtime(runtime: Optional[InferenceRuntime]) -> None:
    if runtime is None:
        return
    for name in ("close", "release", "shutdown"):
        fn = getattr(runtime, name, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
            return


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
    """Construct the perception service for the new mode pair and wire whatever
    channels are ready.

    Reads saved polygons + arcs + per-role algorithm IDs from disk and resolves
    them via ``model_path_lookup`` (typically a thin wrapper around
    ``vision.detection_registry.detection_algorithm_definition`` so perception
    does not import the legacy registry on the hot path).

    Wiring is delegated to ``PerceptionService.reconcile()``: this builder waits
    briefly for cameras to start, then runs one synchronous reconcile pass. A
    channel whose polygon, algorithm, or camera frame is not yet available is
    simply left unwired — the reconcile loop (started by ``start()``) wires it
    the instant its inputs appear, and rewires any channel whose zones, camera
    assignment, or algorithm later change in the UI. No fixed boot deadline
    permanently strands a slow camera anymore.
    """
    resolved_conf: Dict[int, float] = dict(_DEFAULT_CONF_THRESHOLDS)
    if conf_thresholds:
        resolved_conf.update(conf_thresholds)
    ctx = _ReconcileContext(
        gc=gc,
        camera_service=camera_service,
        model_path_lookup=model_path_lookup,
        runtime_factory=runtime_factory,
        resolved_conf=resolved_conf,
        on_c3_exit_edge=on_c3_exit_edge,
    )

    # Give the capture threads a chance to produce their first frame so the
    # initial pass wires as many channels as possible. Unlike before, a camera
    # that misses this window is NOT stranded — the reconcile loop late-binds
    # it the moment a frame arrives.
    _wait_for_frame_shapes(camera_service, timeout_s=15.0, gc=gc)

    service = PerceptionService(
        channels={}, captures={}, runtimes={}, slots={}, workers={},
        context=ctx, fingerprints={},
    )
    service.reconcile()
    _log_channel_diagnostics(gc, service, _read_disk_inputs(gc))
    return service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_channel_diagnostics(gc: Any, service: PerceptionService, disk: _DiskInputs) -> None:
    """Per-channel section + arc_center sanity dump. Hard-errors when a wired
    channel has no saved ``arc_center`` — without it the section→pixel mapping
    silently rotates away from the UI overlay (the classic footgun here)."""
    try:
        for ch_id, ch_def in service.channels().items():
            polygon_key = CHANNEL_REGISTRY[ch_id][1]
            angle_key = CHANNEL_REGISTRY[ch_id][2]
            arc_entry = disk.arc_params.get(polygon_key) or disk.arc_params.get(angle_key)
            arc_keys = list(arc_entry.keys()) if isinstance(arc_entry, dict) else None
            arc_center_raw = arc_entry.get("center") if isinstance(arc_entry, dict) else None
            saved_res = arc_entry.get("resolution") if isinstance(arc_entry, dict) else None
            exit_only = ch_def.exit_sections - ch_def.precise_sections
            gc.logger.info(
                f"[perception loadChannelDefs] ch={ch_id} src={ch_def.camera_source_id} "
                f"section_zero_angle={ch_def.radius1_angle_image:.2f} | "
                f"|drop|={len(ch_def.drop_sections)} "
                f"|exit_union|={len(ch_def.exit_sections)} "
                f"|precise|={len(ch_def.precise_sections)} "
                f"|exit_only|={len(exit_only)} | "
                f"used_center={ch_def.center} "
                f"saved_arc_center={arc_center_raw} saved_resolution={saved_res} "
                f"mask={ch_def.mask.shape[1]}x{ch_def.mask.shape[0]} | "
                f"arc_entry_keys={arc_keys}"
            )
            if arc_center_raw is None:
                gc.logger.error(
                    f"[perception loadChannelDefs] ch={ch_id}: arc_params has NO 'center' key. "
                    f"Falling back to polygon centroid — section→pixel mapping WILL be wrong "
                    f"(rotated) and will not match the UI overlay. Fix the saved arc_params blob "
                    f"in local_state and reload."
                )
        gc.logger.info(
            f"[perception loadChannelDefs] top-level arc_params keys={list(disk.arc_params.keys())}"
        )
    except Exception as exc:
        _log(gc, "warning", f"[perception loadChannelDefs] diagnostic log failed: {exc}")


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
