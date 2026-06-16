"""Per-channel inference worker — one thread per camera.

The worker is constructed with direct, immutable references to:
- its ``CaptureWorker`` (one camera, one source_id),
- its ``InferenceRuntime`` (one RKNN runtime pinned to one NPU core),
- its ``ChannelDef`` (one set of arcs, one polygon mask),
- its ``LatestStateSlot`` (its write target).

Nothing on the hot path looks anything up by role string. Cross-camera or
cross-core mixups require explicitly swapping a worker's attributes,
which the code never does — and the source_id assertion in the loop
catches that anyway.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Optional

import numpy as np

from .arcs import (
    attributeBboxes,
    bboxArea,
    bboxInsideChannelMask,
    bboxInsideMask,
    bboxWithinAreaFraction,
    bboxWithinMaskExtent,
    comForwardToPreciseEntryDeg,
    comInPreciseZone,
    exitComForwardDeg,
    exitComForwardToCenterDeg,
    forwardClearanceToExitDeg,
    orderedPieceObservations,
)
from .capture import CaptureWorker, PerceptionFrame
from .channel import ChannelDef
from .detection import Detection
from .runtime import InferenceRuntime
from .state import ChannelState, LatestStateSlot, PieceObservation
from .tracking import TrackerManager


# Callable signature for the optional KnownObject emit hook (rising edge of
# C3 → C4 hand-off). The PerceptionService wires this when the C3 worker
# is constructed; other workers leave it as ``None``.
OnExitEdge = Callable[[float], None]


# Default loop pacing constants. The capture thread runs at the camera's
# native fps (~30 Hz); these just keep us from spinning when frames are
# stale or the capture has none yet.
_IDLE_SLEEP_S = 0.005
_NO_FRAME_SLEEP_S = 0.010


# Gray-fill (value 230) the pixels outside the channel polygon before inference,
# so the model only sees pixels inside the channel region (matching
# VisionManager's crop-mask path). Gated on SORTER_POLYGON_CROP_MASK.
_POLYGON_CROP_MASK = os.environ.get("SORTER_POLYGON_CROP_MASK", "0") == "1"


# Drop detections whose bbox covers more than this fraction of the channel mask
# area — implausibly massive hits (a hand, a shadow, the model latching onto the
# whole channel). Override via env for tuning.
_MAX_BBOX_MASK_AREA_FRACTION = float(
    os.environ.get("SORTER_MAX_BBOX_MASK_AREA_FRACTION", "0.6")
)
# Drop detections whose bbox width OR height exceeds this fraction of the channel
# mask's bounding extent. Catches long, skinny boxes (e.g. 80% wide / 20% tall)
# that slip under the area limit. Override via env for tuning.
_MAX_BBOX_MASK_DIM_FRACTION = float(
    os.environ.get("SORTER_MAX_BBOX_MASK_DIM_FRACTION", "0.6")
)
# Throttle (seconds) for the average-bbox-size readout used to tune the filter.
_BBOX_SIZE_LOG_THROTTLE_S = 5.0


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _observe(
    runtime_stats: Optional[Any], key: str, ms: float
) -> None:
    if runtime_stats is None:
        return
    fn = getattr(runtime_stats, "observePerfMs", None)
    if fn is None:
        return
    try:
        fn(key, ms)
    except Exception:
        pass


def _hit(counter: Optional[Any], key: str) -> None:
    if counter is None:
        return
    fn = getattr(counter, "hit", None)
    if fn is None:
        return
    try:
        fn(key)
    except Exception:
        pass


class InferenceWorker:
    """One thread per channel. Capture → infer → attribute → slot.write."""

    def __init__(
        self,
        *,
        capture: CaptureWorker,
        runtime: InferenceRuntime,
        channel_def: ChannelDef,
        slot: LatestStateSlot,
        conf_threshold: Optional[float] = None,
        on_exit_edge: Optional[OnExitEdge] = None,
        runtime_stats: Optional[Any] = None,
        profiler: Optional[Any] = None,
        logger: Optional[Any] = None,
        log_attribution: bool = False,
    ) -> None:
        # Construction-time invariant: the capture's source_id must match
        # the channel's. After this point the worker holds direct refs;
        # nobody mutates these.
        if capture.source_id != channel_def.camera_source_id:
            raise ValueError(
                f"capture.source_id={capture.source_id!r} does not match "
                f"channel_def.camera_source_id={channel_def.camera_source_id!r} "
                f"(channel_id={channel_def.channel_id})"
            )
        self._capture = capture
        self._runtime = runtime
        self._channel_def = channel_def
        self._slot = slot
        # Crop the full frame to the channel polygon's bounding rect before
        # inference, then offset bboxes back to full-frame coords. Mirrors the
        # VisionManager detection path (_cropFrameToPolygonRegion). Critical for
        # the 4K carousel: letterboxing a full 3840×2160 frame to the 320 model
        # input shrinks an on-channel piece below detectability while large
        # off-channel background junk survives — so the worker would detect only
        # junk and report n_pieces=0. Computed once here (mask is immutable); the
        # hot path does a zero-copy slice, and the model resizes a smaller region
        # so inference preprocessing is cheaper, not more expensive.
        self._crop_rect = self._compute_crop_rect(channel_def.mask)
        # When this channel has secondary (foreign) zones defined, infer on the
        # FULL frame instead of the primary-polygon crop, so pieces sitting in
        # those zones (outside the primary crop) are actually detected and we can
        # verify the secondary-zone filtering/tagging end to end. This is a
        # verification aid, not the production crop: on the 4K carousel a
        # full-frame → model-input resize shrinks small on-channel pieces toward
        # the detectability floor (see the crop rationale above), so primary
        # detection may degrade while foreign zones are present.
        if channel_def.secondary_zones:
            self._crop_rect = None
        self._conf_threshold = conf_threshold
        self._on_exit_edge = on_exit_edge
        self._runtime_stats = runtime_stats
        self._profiler = profiler
        self._logger = logger
        self._log_attribution = log_attribution

        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name=f"perception-{channel_def.camera_source_id}",
        )
        self._last_frame_ts: float = -1.0
        self._was_in_exit: bool = False
        self._last_summary_log_ts: float = 0.0
        self._last_size_log_ts: float = 0.0
        # Channel mask area + bounding extent in pixels, precomputed once (mask
        # is immutable). Used by the oversize-bbox filters and the size readout.
        self._mask_area_px: float = float(int(np.count_nonzero(channel_def.mask)))
        _ys, _xs = np.nonzero(channel_def.mask)
        if _ys.size:
            self._mask_w_extent: float = float(int(_xs.max() - _xs.min() + 1))
            self._mask_h_extent: float = float(int(_ys.max() - _ys.min() + 1))
        else:
            self._mask_w_extent = 0.0
            self._mask_h_extent = 0.0

        # Latest raw inference result — GIL-atomic tuple ref, same pattern as
        # LatestStateSlot. Written after every successful inference so the
        # classification channel state machine can read bboxes + the exact
        # frame they were computed against without triggering a new inference.
        self._latest_raw: Optional[tuple] = None

        # Richer record for the perception-debug overlay only: raw (pre-filter)
        # bboxes, the on-channel subset, the crop rect, the frame, and timing.
        # GIL-atomic dict ref; never read on the hot path.
        self._latest_debug: Optional[dict] = None

        # Latest in-crop detections tagged with zone provenance (primary +
        # secondary). GIL-atomic list ref. Display/tag only — the slot and
        # ``latest_raw`` stay primary-only, so the state machine is unaffected.
        self._latest_detections: Optional[list[Detection]] = None

        # Per-channel cross-frame identity. Holds the operator-selected tracker
        # (ByteTrack or the angular tracker) and hot-swaps it when the Settings
        # page changes. Fed the final on-channel bboxes every cycle; assigns each
        # a stable ``sv_bt_track_id`` that survives brief detector dropouts.
        # Advisory — the slot/state machine read positions and zones, not
        # identity; the id rides along on pieces/detections/overlay.
        self._tracker = TrackerManager()

        # On-demand full-frame debug inference. When a request bumps this
        # timestamp, the loop ALSO runs the model on the WHOLE frame (no crop)
        # for the next few seconds, so the debug page can compare cropped
        # (production) vs full-frame detections — two inferences per cycle while
        # someone is watching, zero extra cost otherwise. Run on the worker
        # thread because the RKNN runtime is single-owner (one NPU context).
        self._full_frame_debug_until: float = 0.0
        # Last full-frame result, PERSISTED (not reset per cycle) so the debug
        # endpoint doesn't flap to "warming up" on cycles that didn't run it.
        # {"bboxes", "infer_ms", "frame", "frame_ts"} or None until the first run.
        self._latest_full_frame: Optional[dict] = None

        # Public counters — read by the smoke test.
        self.iterations: int = 0
        self.inferences: int = 0
        self.source_id_assertions: int = 0   # hard fails; must stay 0
        self.errors: int = 0

    # --- lifecycle -------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def channel_id(self) -> int:
        return self._channel_def.channel_id

    @property
    def source_id(self) -> str:
        return self._channel_def.camera_source_id

    @property
    def latest_raw(self) -> Optional[tuple]:
        """Latest ``(bboxes, PerceptionFrame)`` pair from the last successful
        inference. GIL-atomic read — no lock required."""
        return self._latest_raw

    @property
    def latest_debug(self) -> Optional[dict]:
        """Latest debug record (raw + on-channel bboxes, crop rect, frame,
        timing) for the perception-debug overlay. GIL-atomic read."""
        return self._latest_debug

    @property
    def latest_full_frame(self) -> Optional[dict]:
        """Last full-frame (uncropped) debug result — persisted across cycles.
        GIL-atomic read."""
        return self._latest_full_frame

    @property
    def latest_detections(self) -> Optional[list[Detection]]:
        """Latest in-crop detections tagged with primary/secondary zone
        membership. GIL-atomic read — display/tag only."""
        return self._latest_detections

    def _tag_detections(
        self, all_bboxes: list, track_id_by_bbox: Optional[dict] = None
    ) -> list[Detection]:
        """Wrap each in-crop bbox with its zone provenance: ``in_primary`` (inside
        the channel polygon mask) and the ids of any secondary zones whose mask
        contains the bbox center. A few mask indices per bbox — cheap.

        ``track_id_by_bbox`` maps the on-channel (tracked) bboxes to their
        ``sv_bt_track_id``; off-channel detections aren't tracked, so they fall
        through to ``None``."""
        ch = self._channel_def
        zones = ch.secondary_zones
        tids = track_id_by_bbox or {}
        out: list[Detection] = []
        for b in all_bboxes:
            bbox = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
            in_primary = bboxInsideChannelMask(bbox, ch)
            sids = (
                tuple(z.id for z in zones if bboxInsideMask(bbox, z.mask))
                if zones
                else ()
            )
            out.append(
                Detection(
                    bbox=bbox,
                    in_primary=in_primary,
                    secondary_zone_ids=sids,
                    sv_bt_track_id=tids.get(bbox),
                )
            )
        return out

    def request_full_frame_debug(self, ttl_s: float = 10.0) -> None:
        """Ask the loop to ALSO run a full-frame (uncropped) inference for the
        next ``ttl_s`` seconds. Self-expiring so the extra inference stops as
        soon as the debug page is closed. GIL-atomic float write — no lock."""
        self._full_frame_debug_until = time.time() + ttl_s

    def start(self) -> None:
        self._stop.clear()
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    # --- hot loop --------------------------------------------------------

    @staticmethod
    def _compute_crop_rect(mask) -> Optional[tuple[int, int, int, int]]:
        """Bounding rect (x1, y1, x2, y2) of the channel polygon mask, or None
        when the mask is empty/absent (then the worker infers on the full frame).
        """
        if mask is None:
            return None
        ys, xs = np.nonzero(mask)
        if xs.size == 0 or ys.size == 0:
            return None
        return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

    def _check_source_id(self, frame: PerceptionFrame) -> bool:
        if (
            frame.source_id == self._capture.source_id
            and frame.source_id == self._channel_def.camera_source_id
        ):
            return True
        self.source_id_assertions += 1
        _hit(self._profiler, f"perception.{self.source_id}.source_id_assertion")
        if self._logger is not None:
            try:
                self._logger.error(
                    f"[perception] source_id assertion failed: "
                    f"frame={frame.source_id!r} "
                    f"capture={self._capture.source_id!r} "
                    f"channel={self._channel_def.camera_source_id!r}"
                )
            except Exception:
                pass
        return False

    def _maybe_emit_exit_edge(self, ts: float, in_exit_now: bool) -> None:
        if self._on_exit_edge is None:
            return
        if in_exit_now and not self._was_in_exit:
            try:
                self._on_exit_edge(ts)
            except Exception:
                pass
        self._was_in_exit = in_exit_now

    def _maybe_log_attribution(
        self,
        in_exit: bool,
        in_precise: bool,
        in_exit_majority: bool,
        per_bbox_counts: list,
    ) -> None:
        """Log every frame where the piece is anywhere in the exit-union (so
        we capture both the "should jitter" and "should NOT jitter" cases).
        Each on-channel bbox is reported with n_drop / n_exit_only / n_precise
        / n_in_mask grid-point counts — these are the actual area-overlap
        numbers driving the in_exit_majority trigger. Channel section set
        sizes are appended so it's obvious if precise_sections is empty
        (which would silently degrade exit_only → full exit union).
        """
        if self._logger is None or not self._log_attribution:
            return
        if not in_exit and not in_exit_majority:
            return
        ch = self._channel_def
        exit_only_size = len(ch.exit_sections - ch.precise_sections)
        bbox_strs = []
        for nd, ne, np_, nm, bbox in per_bbox_counts:
            x1, y1, x2, y2 = bbox
            total_grid = nd + ne + np_
            pct_e = (100.0 * ne / total_grid) if total_grid else 0.0
            pct_p = (100.0 * np_ / total_grid) if total_grid else 0.0
            bbox_strs.append(
                f"bbox=({x1},{y1},{x2},{y2}) n_drop={nd} n_exit_only={ne} "
                f"n_precise={np_} n_in_mask={nm} "
                f"({pct_e:.0f}%E/{pct_p:.0f}%P of regions)"
            )
        bbox_summary = " | ".join(bbox_strs) if bbox_strs else "(no on-channel bboxes)"
        try:
            self._logger.info(
                f"[perception ch={ch.channel_id} src={ch.camera_source_id}] "
                f"in_exit={in_exit} in_precise={in_precise} "
                f"in_exit_majority={in_exit_majority} | "
                f"section_sizes drop={len(ch.drop_sections)} "
                f"exit_union={len(ch.exit_sections)} "
                f"precise={len(ch.precise_sections)} "
                f"exit_only={exit_only_size} | "
                f"{bbox_summary}"
            )
        except Exception:
            pass

    def _maybe_log_summary(
        self,
        bboxes: list,
        in_drop: bool,
        in_exit: bool,
        n_pieces: int,
        now_s: float,
    ) -> None:
        """Throttled once-per-second summary: total detections, how many are
        on-channel, and which zones are active. Enough to debug a stalled feeder
        without spamming every frame."""
        if self._logger is None:
            return
        # Empty frames are the bulk of the volume and carry no debug value once
        # you know the channel is clear — log them at 10s, real detections at 1s.
        idle_frame = len(bboxes) == 0 and n_pieces == 0
        throttle_s = 10.0 if idle_frame else 1.0
        if now_s - self._last_summary_log_ts < throttle_s:
            return
        self._last_summary_log_ts = now_s
        ch = self._channel_def
        n_total = len(bboxes)
        # Sizes in pixels for rough scale feedback
        sizes = []
        for b in bboxes:
            w = int(b[2]) - int(b[0])
            h = int(b[3]) - int(b[1])
            cx = (int(b[0]) + int(b[2])) // 2
            cy = (int(b[1]) + int(b[3])) // 2
            sizes.append(f"{w}×{h}@({cx},{cy})")
        sizes_str = "[" + ", ".join(sizes) + "]" if sizes else "[]"
        mh, mw = ch.mask.shape[:2]
        sizes_str += f" mask={mw}×{mh}"
        zones = []
        if in_drop:
            zones.append("DROP")
        if in_exit:
            zones.append("EXIT")
        zone_str = "+".join(zones) if zones else "none"
        try:
            self._logger.info(
                f"[perception summary ch={ch.channel_id} src={ch.camera_source_id}] "
                f"detections={n_total} on_channel={n_pieces} zones={zone_str} "
                f"sizes={sizes_str}"
            )
        except Exception:
            pass

    def _maybe_log_bbox_sizes(self, bboxes: list, now_s: float) -> None:
        """Throttled (~5s) average-bbox-size readout per channel, for tuning the
        oversize filter. Reports sizes against the on-mask set BEFORE the area
        filter so the full distribution (including the big hits being dropped) is
        visible. Only fires when there are detections, so idle channels don't
        flood the logs."""
        if self._logger is None or not bboxes:
            return
        if now_s - self._last_size_log_ts < _BBOX_SIZE_LOG_THROTTLE_S:
            return
        self._last_size_log_ts = now_s
        ch = self._channel_def
        mask_area = self._mask_area_px or 1.0
        mask_w = self._mask_w_extent or 1.0
        mask_h = self._mask_h_extent or 1.0
        areas = [bboxArea(b) for b in bboxes]
        w_fracs = [(b[2] - b[0]) / mask_w for b in bboxes]
        h_fracs = [(b[3] - b[1]) / mask_h for b in bboxes]
        avg_area = sum(areas) / len(areas)
        n_dropped = sum(
            1
            for b, a in zip(bboxes, areas)
            if a > _MAX_BBOX_MASK_AREA_FRACTION * mask_area
            or (b[2] - b[0]) > _MAX_BBOX_MASK_DIM_FRACTION * mask_w
            or (b[3] - b[1]) > _MAX_BBOX_MASK_DIM_FRACTION * mask_h
        )
        try:
            self._logger.info(
                f"[perception sizes ch={ch.channel_id} src={ch.camera_source_id}] "
                f"n={len(bboxes)} avg_area_px={avg_area:.0f} "
                f"avg_frac_area={avg_area / mask_area:.2f} "
                f"max_frac_area={max(areas) / mask_area:.2f} "
                f"max_frac_w={max(w_fracs):.2f} max_frac_h={max(h_fracs):.2f} "
                f"limits(area={_MAX_BBOX_MASK_AREA_FRACTION:.2f},"
                f"dim={_MAX_BBOX_MASK_DIM_FRACTION:.2f}) oversized_dropped={n_dropped}"
            )
        except Exception:
            pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.iterations += 1
            _hit(self._profiler, f"perception.{self.source_id}.iterations")
            try:
                frame = self._capture.latest_frame()
                if frame is None:
                    self._stop.wait(_NO_FRAME_SLEEP_S)
                    continue
                if frame.timestamp == self._last_frame_ts:
                    self._stop.wait(_IDLE_SLEEP_S)
                    continue
                if not self._check_source_id(frame):
                    # Hard fail to a safe state — write a neutral slot and
                    # keep retrying. A future change that flips the
                    # source_id will land us here loudly; correct system
                    # state stays "nothing detected" rather than "wrong
                    # detections."
                    self._slot.write(
                        ChannelState(
                            ts=frame.timestamp, in_drop=False, in_exit=False, n_pieces=0
                        )
                    )
                    self._last_frame_ts = frame.timestamp
                    self._stop.wait(_IDLE_SLEEP_S)
                    continue

                cycle_t0 = _now_ms()
                infer_t0 = cycle_t0
                if self._crop_rect is not None:
                    cx1, cy1, cx2, cy2 = self._crop_rect
                    crop = frame.bgr[cy1:cy2, cx1:cx2]
                    if _POLYGON_CROP_MASK:
                        mask_crop = self._channel_def.mask[cy1:cy2, cx1:cx2]
                        crop = np.where(
                            mask_crop[:, :, None] > 0, crop, np.uint8(230)
                        )
                    scored = self._runtime.inferWithScores(
                        crop, conf_threshold=self._conf_threshold
                    )
                    bboxes = []
                    score_by_bbox: dict = {}
                    for b, s in scored:
                        bb = (
                            int(b[0]) + cx1, int(b[1]) + cy1,
                            int(b[2]) + cx1, int(b[3]) + cy1,
                        )
                        bboxes.append(bb)
                        score_by_bbox[bb] = s
                else:
                    full = frame.bgr
                    if _POLYGON_CROP_MASK:
                        m = self._channel_def.mask
                        full = np.where(m[:, :, None] > 0, full, np.uint8(230))
                    bboxes = []
                    score_by_bbox = {}
                    for b, s in self._runtime.inferWithScores(
                        full, conf_threshold=self._conf_threshold
                    ):
                        bb = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
                        bboxes.append(bb)
                        score_by_bbox[bb] = s
                infer_ms = _now_ms() - infer_t0

                # Every model detection in full-frame coords, BEFORE the
                # on-channel mask filter. Kept only for the perception-debug
                # overlay so we can show what the model produced vs. what the
                # mask filter kept — never read on the hot path.
                raw_bboxes_full = list(bboxes)

                # The crop is the polygon's bounding RECT, so its corners can
                # still admit detections that fall OUTSIDE the polygon (e.g. the
                # chute/exit area beside the carousel). Drop them here using the
                # same mask membership test attributeBboxes applies, so nothing
                # downstream — n_pieces, the classification crop, latest_raw, the
                # debug overlay — ever sees an off-channel detection.
                on_mask = [
                    b for b in bboxes if bboxInsideChannelMask(b, self._channel_def)
                ]
                # Then drop implausibly massive detections: anything covering more
                # than _MAX_BBOX_MASK_AREA_FRACTION of the channel mask area, OR
                # whose width/height exceeds _MAX_BBOX_MASK_DIM_FRACTION of the
                # mask's extent (catches long, skinny boxes the area test misses).
                # Logged (throttled) below against the pre-filter on-mask set so
                # the thresholds can be tuned against real footage.
                bboxes = [
                    b
                    for b in on_mask
                    if bboxWithinAreaFraction(
                        b, self._mask_area_px, _MAX_BBOX_MASK_AREA_FRACTION
                    )
                    and bboxWithinMaskExtent(
                        b,
                        self._mask_w_extent,
                        self._mask_h_extent,
                        _MAX_BBOX_MASK_DIM_FRACTION,
                    )
                ]

                # Assign each final on-channel piece a stable ``sv_bt_track_id``.
                # Called every cycle — including empty ones — so the tracker ages
                # coasting tracks on the right cadence. Cheap for 1–2 boxes. Real
                # detection scores drive ByteTrack's confidence-based association.
                scores = [score_by_bbox.get(b, 1.0) for b in bboxes]
                track_id_by_bbox = self._tracker.update(
                    bboxes,
                    scores,
                    frame_bgr=frame.bgr,
                    channel=self._channel_def,
                    timestamp=frame.timestamp,
                )

                attribute_t0 = _now_ms()
                in_drop, in_exit, in_precise, in_exit_majority, n_pieces, per_bbox_counts = attributeBboxes(
                    bboxes, self._channel_def
                )
                advance_clearance_deg = forwardClearanceToExitDeg(
                    bboxes, self._channel_def
                )
                exit_com_forward_deg = exitComForwardDeg(bboxes, self._channel_def)
                exit_com_forward_to_center_deg = exitComForwardToCenterDeg(
                    bboxes, self._channel_def
                )
                exit_com_forward_to_precise_deg = comForwardToPreciseEntryDeg(
                    bboxes, self._channel_def
                )
                exit_com_in_precise = comInPreciseZone(bboxes, self._channel_def)
                pieces = tuple(
                    PieceObservation(
                        com_forward_to_exit_deg=gap,
                        com_section=sec,
                        zone_code=zone_code,
                        bbox=bbox,
                        sv_bt_track_id=track_id_by_bbox.get(bbox),
                    )
                    for gap, sec, zone_code, bbox in orderedPieceObservations(
                        bboxes, self._channel_def
                    )
                )
                attribute_ms = _now_ms() - attribute_t0

                state = ChannelState(
                    ts=frame.timestamp,
                    in_drop=in_drop,
                    in_exit=in_exit,
                    n_pieces=n_pieces,
                    in_precise=in_precise,
                    in_exit_majority=in_exit_majority,
                    advance_clearance_deg=advance_clearance_deg,
                    exit_com_forward_deg=exit_com_forward_deg,
                    exit_com_forward_to_center_deg=exit_com_forward_to_center_deg,
                    exit_com_forward_to_precise_deg=exit_com_forward_to_precise_deg,
                    exit_com_in_precise=exit_com_in_precise,
                    pieces=pieces,
                )
                self._slot.write(state)
                self._latest_raw = (list(bboxes), frame)
                # Tag ALL in-crop detections (not just on-channel) with zone
                # provenance so the overlay can show foreign-zone hits and future
                # consumers can ask which zone a piece is in. Off the hot read
                # path — the slot above stays primary-only.
                detections = self._tag_detections(raw_bboxes_full, track_id_by_bbox)
                self._latest_detections = detections
                self._latest_debug = {
                    "raw_bboxes": raw_bboxes_full,
                    "on_channel_bboxes": list(bboxes),
                    # sv_bt_track_id per on-channel bbox, index-aligned to
                    # ``on_channel_bboxes`` (None for any not-yet-confirmed track),
                    # so the debug page can label boxes without a tuple-keyed map.
                    "on_channel_track_ids": [track_id_by_bbox.get(b) for b in bboxes],
                    "detections": detections,
                    "crop_rect": self._crop_rect,
                    "frame": frame,
                    "infer_ms": infer_ms,
                    "conf_threshold": self._conf_threshold,
                }
                # On-demand: also infer on the WHOLE frame so the debug page can
                # show what the model produces without the polygon crop. Persist
                # the result (don't null it on cycles that skip it) so the debug
                # endpoint stays available instead of flapping. If there's no
                # crop, production already used the full frame — reuse it.
                if self._crop_rect is None:
                    self._latest_full_frame = {
                        "bboxes": list(raw_bboxes_full),
                        "infer_ms": infer_ms,
                        "frame": frame,
                        "frame_ts": frame.timestamp,
                    }
                elif time.time() < self._full_frame_debug_until:
                    try:
                        ff_t0 = _now_ms()
                        ff = self._runtime.infer(
                            frame.bgr, conf_threshold=self._conf_threshold
                        )
                        self._latest_full_frame = {
                            "bboxes": [
                                (int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in ff
                            ],
                            "infer_ms": _now_ms() - ff_t0,
                            "frame": frame,
                            "frame_ts": frame.timestamp,
                        }
                    except Exception as exc:
                        if self._logger is not None:
                            try:
                                self._logger.warning(
                                    f"[perception] {self.source_id} full-frame debug "
                                    f"inference failed: {exc}"
                                )
                            except Exception:
                                pass
                self._maybe_emit_exit_edge(frame.timestamp, in_exit)
                self._maybe_log_attribution(
                    in_exit, in_precise, in_exit_majority, per_bbox_counts
                )
                self._maybe_log_summary(bboxes, in_drop, in_exit, n_pieces, time.time())
                self._maybe_log_bbox_sizes(on_mask, time.time())
                self._last_frame_ts = frame.timestamp
                self.inferences += 1

                cycle_ms = _now_ms() - cycle_t0
                _observe(self._runtime_stats, f"perception.{self.source_id}.cycle_ms", cycle_ms)
                _observe(self._runtime_stats, f"perception.{self.source_id}.infer_ms", infer_ms)
                _observe(
                    self._runtime_stats,
                    f"perception.{self.source_id}.attribute_ms",
                    attribute_ms,
                )
                _observe(
                    self._runtime_stats,
                    f"perception.{self.source_id}.frame_age_ms",
                    max(0.0, (time.time() - frame.timestamp) * 1000.0),
                )
                _hit(self._profiler, f"perception.{self.source_id}.inferred")

            except Exception as exc:
                self.errors += 1
                _hit(self._profiler, f"perception.{self.source_id}.errors")
                if self._logger is not None:
                    try:
                        self._logger.warning(
                            f"[perception] {self.source_id} loop error: {exc}"
                        )
                    except Exception:
                        pass
                self._stop.wait(0.1)
