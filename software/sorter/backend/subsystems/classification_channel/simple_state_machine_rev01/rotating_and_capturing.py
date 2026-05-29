import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from defs.known_object import ClassificationStatus, KnownObject, PieceStage
from subsystems.classification_channel.states import ClassificationChannelState
from vision.types import CameraFrame

from .base import Rev01BaseState
from .constants import LOG_TAG


_SKEW_DUMP_MAX_PER_SWEEP = 8


class RotatingAndCapturing(Rev01BaseState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rotation_started = False
        self._empty_streak = 0
        self._exit_seen = False
        self._skew_dump_count = 0

    def step(self) -> Optional[ClassificationChannelState]:
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is not None:
            return self._step_perception(perception_service)
        return self._step_legacy()

    # ---- Rev04 perception path ----

    def _step_perception(self, perception_service) -> Optional[ClassificationChannelState]:
        """Hot path for GO_TO_ANGLE_REV01 + SIMPLE_STATE_MACHINE_REV01.

        Reads bboxes and the frame they were inferred from directly out of the
        perception worker's cached latest_raw slot — no new RKNN inference, no
        VisionManager call. The worker already ran inference on the carousel
        camera; we just consume the result.
        """
        now = time.monotonic()
        self.setClassificationReady(False, "rotating_and_capturing")

        t0 = time.perf_counter()
        raw = perception_service.read_bboxes_and_frame(4)
        self.gc.runtime_stats.observePerfMs(
            "classification.rev01.rotate.bboxes_on_channel_ms",
            (time.perf_counter() - t0) * 1000.0,
        )

        if raw is None:
            bboxes: list = []
            frame_bgr = None
            frame_ts = 0.0
        else:
            raw_bboxes, perc_frame = raw
            bboxes = [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in raw_bboxes]
            frame_bgr = perc_frame.bgr
            frame_ts = float(perc_frame.timestamp)

        self.gc.profiler.observeValue(
            "classification.rev01.rotate.bbox_count",
            float(len(bboxes)),
        )

        if not self._rotation_started and not bboxes:
            self._empty_streak += 1
            if self._empty_streak >= self.ctx.config.empty_streak_to_abort:
                self.stopStepper()
                self.logger.info(
                    f"{LOG_TAG} ROTATING_AND_CAPTURING -> IDLE "
                    f"(channel clear for {self._empty_streak} checks; nothing to rotate)"
                )
                return ClassificationChannelState.IDLE
            return None
        self._empty_streak = 0

        if not self._rotation_started:
            self.ctx.rotating_started_at = now
            self.ctx.last_capture_frame_ts = 0.0
            self._skew_dump_count = 0
            self.ctx.known_object = KnownObject(
                stage=PieceStage.created,
                classification_status=ClassificationStatus.pending,
                first_carousel_seen_ts=time.time(),
            )
            self.emitKnownObject()
            cfg = self.ctx.config
            if not self.startCaptureSweepMove(
                cfg.capture_sweep_output_deg,
                cfg.rotate_speed_usteps_per_s,
            ):
                self.logger.error(f"{LOG_TAG} could not start rotation — abort to IDLE")
                return ClassificationChannelState.IDLE
            self._rotation_started = True
            self.logger.info(
                f"{LOG_TAG} ROTATING_AND_CAPTURING started fixed sweep "
                f"(speed={cfg.rotate_speed_usteps_per_s} µsteps/s, "
                f"sweep={cfg.capture_sweep_output_deg:.1f} output°, "
                f"drop_angle={self.cc_config.drop_angle_deg:.1f}°)"
            )

        if now - self.ctx.rotating_started_at > self.ctx.config.rotate_timeout_s:
            self.logger.error(
                f"{LOG_TAG} rotation timeout after {self.ctx.config.rotate_timeout_s}s "
                f"(captures={len(self.ctx.captured_crops)}) — abort to DISCHARGING"
            )
            self.stopStepper()
            return ClassificationChannelState.REV01_DISCHARGING

        primary_bbox_started = time.perf_counter()
        primary_bbox = self.cv.primaryBbox(bboxes)
        self.gc.runtime_stats.observePerfMs(
            "classification.rev01.rotate.primary_bbox_ms",
            (time.perf_counter() - primary_bbox_started) * 1000.0,
        )
        # Crop from the SAME frame the bboxes were inferred against — the
        # perception worker caches (bboxes, frame) as a pair so there is no
        # frame-skew between bbox coords and pixel data.
        if frame_bgr is not None and primary_bbox is not None:
            if frame_ts > self.ctx.last_capture_frame_ts:
                crop_started = time.perf_counter()
                crop = self.cv.cropBbox(frame_bgr, primary_bbox, self.ctx.config.crop_padding_px)
                self.gc.runtime_stats.observePerfMs(
                    "classification.rev01.rotate.crop_bbox_ms",
                    (time.perf_counter() - crop_started) * 1000.0,
                )
                if crop is not None:
                    self.ctx.captured_crops.append(crop)
                    self.ctx.captured_crop_timestamps.append(frame_ts)
                    self.ctx.last_capture_frame_ts = frame_ts
                    elapsed = now - self.ctx.rotating_started_at
                    self.logger.info(
                        f"{LOG_TAG} capture #{len(self.ctx.captured_crops)} "
                        f"(t+{elapsed:.2f}s, ts={frame_ts:.3f}, "
                        f"bbox={primary_bbox}, shape={crop.shape})"
                    )
                    if self.ctx.known_object is not None:
                        encode_started = time.perf_counter()
                        encoded = self.encodeFrame(crop)
                        self.gc.runtime_stats.observePerfMs(
                            "classification.rev01.rotate.encode_crop_ms",
                            (time.perf_counter() - encode_started) * 1000.0,
                        )
                        if encoded is not None:
                            self.ctx.known_object.latest_captured_crop = encoded
                            self.ctx.known_object.latest_captured_crop_ts = frame_ts
                            self.ctx.known_object.recognition_images.append(encoded)
                        self.emitKnownObject()

        # Use the slot's aggregated in_exit rather than re-running VisionManager.
        exit_zone_started = time.perf_counter()
        in_exit = perception_service.read_state(4).in_exit
        self.gc.runtime_stats.observePerfMs(
            "classification.rev01.rotate.any_bbox_in_exit_ms",
            (time.perf_counter() - exit_zone_started) * 1000.0,
        )
        if in_exit and not self._exit_seen:
            self._exit_seen = True
            self.logger.info(f"{LOG_TAG} observed exit-zone overlap during capture sweep")

        stepper = getattr(self.irl, "carousel_stepper", None)
        if self._rotation_started and stepper is not None and bool(stepper.stopped):
            self.logger.info(
                f"{LOG_TAG} ROTATING_AND_CAPTURING -> CLASSIFYING "
                f"(sweep complete; captures={len(self.ctx.captured_crops)}, "
                f"exit_seen={self._exit_seen})"
            )
            return ClassificationChannelState.REV01_CLASSIFYING

        return None

    # ---- Legacy path (non-perception) ----

    def _step_legacy(self) -> Optional[ClassificationChannelState]:
        now = time.monotonic()
        self.setClassificationReady(False, "rotating_and_capturing")

        bboxes_started = time.perf_counter()
        bboxes, bbox_frame = self.cv.bboxesAndFrameOnChannel()
        self.gc.runtime_stats.observePerfMs(
            "classification.rev01.rotate.bboxes_on_channel_ms",
            (time.perf_counter() - bboxes_started) * 1000.0,
        )
        self.gc.profiler.observeValue(
            "classification.rev01.rotate.bbox_count",
            float(len(bboxes)),
        )
        if not self._rotation_started and not bboxes:
            self._empty_streak += 1
            if self._empty_streak >= self.ctx.config.empty_streak_to_abort:
                self.stopStepper()
                self.logger.info(
                    f"{LOG_TAG} ROTATING_AND_CAPTURING -> IDLE "
                    f"(channel clear for {self._empty_streak} checks; nothing to rotate)"
                )
                return ClassificationChannelState.IDLE
            return None
        self._empty_streak = 0

        if not self._rotation_started:
            self.ctx.rotating_started_at = now
            self.ctx.last_capture_frame_ts = 0.0
            self._skew_dump_count = 0
            self.ctx.known_object = KnownObject(
                stage=PieceStage.created,
                classification_status=ClassificationStatus.pending,
                first_carousel_seen_ts=time.time(),
            )
            self.emitKnownObject()
            cfg = self.ctx.config
            if not self.startCaptureSweepMove(
                cfg.capture_sweep_output_deg,
                cfg.rotate_speed_usteps_per_s,
            ):
                self.logger.error(f"{LOG_TAG} could not start rotation — abort to IDLE")
                return ClassificationChannelState.IDLE
            self._rotation_started = True
            self.logger.info(
                f"{LOG_TAG} ROTATING_AND_CAPTURING started fixed sweep "
                f"(speed={cfg.rotate_speed_usteps_per_s} µsteps/s, "
                f"sweep={cfg.capture_sweep_output_deg:.1f} output°, "
                f"drop_angle={self.cc_config.drop_angle_deg:.1f}°)"
            )

        if now - self.ctx.rotating_started_at > self.ctx.config.rotate_timeout_s:
            self.logger.error(
                f"{LOG_TAG} rotation timeout after {self.ctx.config.rotate_timeout_s}s "
                f"(captures={len(self.ctx.captured_crops)}) — abort to DISCHARGING"
            )
            self.stopStepper()
            return ClassificationChannelState.REV01_DISCHARGING

        primary_bbox_started = time.perf_counter()
        primary_bbox = self.cv.primaryBbox(bboxes)
        self.gc.runtime_stats.observePerfMs(
            "classification.rev01.rotate.primary_bbox_ms",
            (time.perf_counter() - primary_bbox_started) * 1000.0,
        )
        if bbox_frame is not None and primary_bbox is not None:
            frame_ts = float(bbox_frame.timestamp)
            if frame_ts > self.ctx.last_capture_frame_ts:
                crop_started = time.perf_counter()
                crop = self.cv.cropBbox(bbox_frame.raw, primary_bbox, self.ctx.config.crop_padding_px)
                self.gc.runtime_stats.observePerfMs(
                    "classification.rev01.rotate.crop_bbox_ms",
                    (time.perf_counter() - crop_started) * 1000.0,
                )
                if crop is not None:
                    self.ctx.captured_crops.append(crop)
                    self.ctx.captured_crop_timestamps.append(frame_ts)
                    self.ctx.last_capture_frame_ts = frame_ts
                    elapsed = now - self.ctx.rotating_started_at
                    self.logger.info(
                        f"{LOG_TAG} capture #{len(self.ctx.captured_crops)} "
                        f"(t+{elapsed:.2f}s, ts={frame_ts:.3f}, "
                        f"bbox={primary_bbox}, shape={crop.shape})"
                    )
                    self._maybeDumpSkewDebug(bbox_frame, primary_bbox, crop, frame_ts)
                    if self.ctx.known_object is not None:
                        encode_started = time.perf_counter()
                        encoded = self.encodeFrame(crop)
                        self.gc.runtime_stats.observePerfMs(
                            "classification.rev01.rotate.encode_crop_ms",
                            (time.perf_counter() - encode_started) * 1000.0,
                        )
                        if encoded is not None:
                            self.ctx.known_object.latest_captured_crop = encoded
                            self.ctx.known_object.latest_captured_crop_ts = frame_ts
                            self.ctx.known_object.recognition_images.append(encoded)
                        self.emitKnownObject()

        exit_zone_started = time.perf_counter()
        in_exit, angles = self.anyBboxInExitZone(bboxes)
        self.gc.runtime_stats.observePerfMs(
            "classification.rev01.rotate.any_bbox_in_exit_ms",
            (time.perf_counter() - exit_zone_started) * 1000.0,
        )
        if in_exit and not self._exit_seen:
            self._exit_seen = True
            self.logger.info(
                f"{LOG_TAG} observed exit-zone overlap during capture sweep "
                f"(bbox_angles={[round(a, 1) for a in angles]})"
            )

        stepper = getattr(self.irl, "carousel_stepper", None)
        if self._rotation_started and stepper is not None and bool(stepper.stopped):
            self.logger.info(
                f"{LOG_TAG} ROTATING_AND_CAPTURING -> CLASSIFYING "
                f"(sweep complete; captures={len(self.ctx.captured_crops)}, "
                f"exit_seen={self._exit_seen})"
            )
            return ClassificationChannelState.REV01_CLASSIFYING

        return None

    def cleanup(self) -> None:
        super().cleanup()
        self.stopStepper()
        self._rotation_started = False
        self._empty_streak = 0
        self._exit_seen = False
        self._skew_dump_count = 0

    def _maybeDumpSkewDebug(
        self,
        bbox_frame: CameraFrame,
        primary_bbox: tuple[int, int, int, int],
        crop: np.ndarray,
        frame_ts: float,
    ) -> None:
        # Cheap-when-off: zero work unless CLASSIFICATION_SKEW_DUMP_IMAGES=1
        # sets the root in GlobalConfig. Capped per sweep so a stuck rotation
        # cannot pile up gigabytes of 4K JPEGs.
        root = getattr(self.gc, "classification_skew_dump_root", None)
        if root is None:
            return
        if self._skew_dump_count >= _SKEW_DUMP_MAX_PER_SWEEP:
            return
        piece = self.ctx.known_object
        piece_uuid = getattr(piece, "uuid", None) if piece is not None else None
        if not isinstance(piece_uuid, str) or not piece_uuid:
            return
        capture = getattr(self._vision_manager, "_carousel_capture", None)
        latest_frame_now = getattr(capture, "latest_frame", None) if capture is not None else None
        try:
            dump_dir = Path(root) / piece_uuid
            dump_dir.mkdir(parents=True, exist_ok=True)
            idx = self._skew_dump_count
            x1, y1, x2, y2 = (int(v) for v in primary_bbox)
            annotated = bbox_frame.raw.copy()
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 3)
            cv2.imwrite(
                str(dump_dir / f"{idx:02d}_bbox_frame.jpg"),
                annotated,
                [cv2.IMWRITE_JPEG_QUALITY, 75],
            )
            cv2.imwrite(
                str(dump_dir / f"{idx:02d}_crop.jpg"),
                crop,
                [cv2.IMWRITE_JPEG_QUALITY, 80],
            )
            # Save the LATEST frame at the moment of the dump call (i.e. AFTER
            # inference completed) with the SAME bbox drawn on. Visual diff
            # between this and bbox_frame is the skew the old code would have
            # had. Now we always crop from bbox_frame, so this is diagnostic.
            if latest_frame_now is not None and latest_frame_now.raw is not None:
                drift_frame = latest_frame_now.raw.copy()
                cv2.rectangle(drift_frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                cv2.imwrite(
                    str(dump_dir / f"{idx:02d}_post_inference_frame.jpg"),
                    drift_frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 60],
                )
                meta_path = dump_dir / f"{idx:02d}_meta.txt"
                meta_path.write_text(
                    f"bbox_frame_ts={frame_ts:.6f}\n"
                    f"latest_frame_ts={float(latest_frame_now.timestamp):.6f}\n"
                    f"delta_ms={(float(latest_frame_now.timestamp) - frame_ts) * 1000.0:.2f}\n"
                    f"bbox_xyxy={x1},{y1},{x2},{y2}\n"
                )
            self._skew_dump_count += 1
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} skew debug dump failed: {exc}")

    @property
    def _vision_manager(self):
        return getattr(self.cv, "_vision", None)
