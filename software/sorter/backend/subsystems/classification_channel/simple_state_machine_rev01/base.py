import base64
import json
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from classification.brickognize import MAX_QUERY_IMAGES, _classifyImages
from defs.known_object import ClassificationStatus, PieceStage
from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from states.base_state import BaseState
from subsystems.classification_channel.five_sector_platter import C4FiveSectorPlatter
from subsystems.shared_variables import SharedVariables
from utils.event import knownObjectToEvent

from .constants import LOG_TAG
from .context import SimpleStateMachineRev01Context
from .vision import Rev01Vision


class Rev01BaseState(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        transport: ClassificationChannelTransport,
        vision,
        event_queue,
        context: SimpleStateMachineRev01Context,
    ):
        super().__init__(irl, gc)
        self.irl_config = irl_config
        self.shared = shared
        self.transport = transport
        self.event_queue = event_queue
        self.ctx = context
        self.cc_config = irl_config.classification_channel_config
        self.cv = Rev01Vision(vision, gc)

    def setClassificationReady(self, ready: bool, reason: str) -> None:
        setter = getattr(self.shared, "set_classification_gate", None)
        getter = getattr(self.shared, "get_classification_ready", None)
        prev = bool(getter()) if callable(getter) else None
        if callable(setter):
            setter(ready, reason=reason)
        else:
            self.shared.classification_ready = ready
        # Log only on transition. This fires every tick; logging it
        # unconditionally was a main-thread log-flood source.
        if prev is None or prev != bool(ready):
            self.logger.info(f"{LOG_TAG} classification_ready -> {ready} ({reason})")

    def stopStepper(self) -> None:
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None or not hasattr(stepper, "move_at_speed"):
            return
        try:
            if bool(getattr(stepper, "stopped", False)):
                return
            stepper.move_at_speed(0)
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} stepper stop failed: {exc}")

    def startRotation(self, speed_usteps_per_s: int) -> bool:
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None:
            self.logger.error(f"{LOG_TAG} carousel_stepper missing — cannot rotate")
            return False
        try:
            stepper.set_speed_limits(16, max(16, speed_usteps_per_s))
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} set_speed_limits failed: {exc}")
        try:
            ok = bool(stepper.move_at_speed(int(speed_usteps_per_s)))
        except Exception as exc:
            self.logger.error(f"{LOG_TAG} move_at_speed failed: {exc}")
            return False
        if not ok:
            self.logger.error(f"{LOG_TAG} move_at_speed not acknowledged")
        return ok

    def startOutputMove(self, output_degrees: float, speed_usteps_per_s: int) -> bool:
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None:
            self.logger.error(f"{LOG_TAG} carousel_stepper missing — cannot move")
            return False
        try:
            stepper.set_speed_limits(16, max(16, speed_usteps_per_s))
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} set_speed_limits failed: {exc}")
        try:
            platter = C4FiveSectorPlatter.from_irl_config(self.irl_config)
            move_steps = platter.output_degrees_to_motor_microsteps(output_degrees)
            ok = bool(stepper.move_steps(int(move_steps)))
        except Exception as exc:
            self.logger.error(f"{LOG_TAG} sweep move failed: {exc}")
            return False
        if not ok:
            self.logger.error(f"{LOG_TAG} move not acknowledged")
        return ok

    def startCaptureSweepMove(self, output_degrees: float, speed_usteps_per_s: int) -> bool:
        return self.startOutputMove(output_degrees, speed_usteps_per_s)

    def emitKnownObject(self) -> None:
        obj = self.ctx.known_object
        if obj is None:
            return
        obj.updated_at = time.time()
        self.event_queue.put(knownObjectToEvent(obj))

    def abandonInFlightObject(self, reason: str) -> None:
        # A piece was photographed (emitted to the UI with a crop) but its cycle
        # is being torn down before it ever classified or distributed — machine
        # stop, or a reset mid-capture. Mark it aborted and emit a final update
        # so the UI drops it instead of leaving it stuck in "capturing" forever.
        # No-op for finalized pieces (already classified/distributed) and pieces
        # that never started capturing.
        obj = self.ctx.known_object
        if obj is None or obj.aborted:
            return
        terminal_status = obj.classification_status not in (
            ClassificationStatus.pending,
            ClassificationStatus.classifying,
        )
        already_distributed = (
            obj.stage == PieceStage.distributed or obj.distributed_at is not None
        )
        if terminal_status or already_distributed:
            return
        obj.aborted = True
        self.logger.info(f"{LOG_TAG} abandoning in-flight piece {obj.uuid[:8]} ({reason})")
        self.emitKnownObject()

    @staticmethod
    def encodeFrame(frame: np.ndarray) -> Optional[str]:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        return base64.b64encode(buf).decode("utf-8")

    @staticmethod
    def sharpness(frame: np.ndarray) -> float:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def anyBboxInExitZone(
        self, bboxes: list[tuple[int, int, int, int]]
    ) -> tuple[bool, list[float]]:
        center = self.cv.channelCenter()
        if center is None:
            return False, []
        angles = [self.cv.bboxAngleDeg(b, center) for b in bboxes]
        hit = any(
            self.cv.bboxInExitZone(
                b, center, self.cc_config.drop_angle_deg, self.cc_config.drop_tolerance_deg
            )
            for b in bboxes
        )
        return hit, angles

    def computeDischargeOutputDeg(
        self, bbox: tuple[int, int, int, int]
    ) -> Optional[float]:
        center = self.cv.channelCenter()
        if center is None:
            return None
        piece_angle = self.cv.bboxAngleDeg(bbox, center)
        target_angle = (
            float(self.cc_config.drop_angle_deg)
            + float(self.cc_config.drop_tolerance_deg)
        ) % 360.0
        delta = (target_angle - piece_angle) % 360.0
        return max(2.0, min(delta, 270.0))

    def bboxesOutsideExitZone(
        self, bboxes: list[tuple[int, int, int, int]]
    ) -> list[tuple[int, int, int, int]]:
        center = self.cv.channelCenter()
        if center is None:
            return list(bboxes)
        return [
            b
            for b in bboxes
            if not self.cv.bboxInExitZone(
                b,
                center,
                self.cc_config.drop_angle_deg,
                self.cc_config.drop_tolerance_deg,
            )
        ]

    # ---- Brickognize classification helpers ----
    # Shared by CAPTURING (which spawns the request) and AWAITING_DISTRIBUTION
    # (which applies the result) — the spawn/apply split spans two states, and
    # all handoff flows through ``self.ctx``.

    def selectRecognitionCrops(self, crops: list[np.ndarray]) -> list[np.ndarray]:
        # Hard-cap at the Brickognize per-request image limit regardless of the
        # configured max_captures — over the limit the API errors the whole call.
        n = min(self.ctx.config.max_captures, MAX_QUERY_IMAGES)
        if len(crops) <= n:
            return list(crops)
        if not crops:
            return []
        last_index = len(crops) - 1
        chosen_indices: list[int] = []
        for slot_idx in range(n):
            capture_idx = round((slot_idx * last_index) / max(1, n - 1))
            if chosen_indices and capture_idx <= chosen_indices[-1]:
                capture_idx = min(last_index, chosen_indices[-1] + 1)
            chosen_indices.append(capture_idx)
        return [crops[idx] for idx in chosen_indices]

    def spawnClassifyThread(self, captures: list[np.ndarray]) -> None:
        gc = self.gc
        piece_uuid = self.ctx.known_object.uuid if self.ctx.known_object is not None else None

        def _run() -> None:
            try:
                result = _classifyImages(gc, captures, piece_uuid=piece_uuid)
                with self.ctx.classify_lock:
                    self.ctx.classification_result = result
            except Exception as exc:
                with self.ctx.classify_lock:
                    self.ctx.classification_error = str(exc)

        thread = threading.Thread(target=_run, daemon=True)
        self.ctx.classify_thread = thread
        thread.start()

    def updateKnownObjectWithResult(self, result: object, error: Optional[str]) -> None:
        obj = self.ctx.known_object
        if obj is None:
            return

        frames = list(self.ctx.captured_crops)

        if error is not None:
            obj.classification_status = ClassificationStatus.unknown
        elif isinstance(result, dict):
            items = result.get("items", [])
            colors = result.get("colors", [])
            if items:
                best = items[0]
                obj.part_id = best.get("id")
                obj.part_name = best.get("name")
                obj.part_category = best.get("category")
                obj.confidence = best.get("score")
                obj.brickognize_preview_url = best.get("img_url")
                obj.classification_status = ClassificationStatus.classified
            else:
                obj.classification_status = ClassificationStatus.not_found
            if colors:
                best_color = max(colors, key=lambda c: c.get("score", 0))
                obj.color_id = str(best_color.get("id", "any_color"))
                obj.color_name = str(best_color.get("name", "Any Color"))
        else:
            obj.classification_status = ClassificationStatus.unknown

        obj.classified_at = time.time()

        if obj.classification_status == ClassificationStatus.classified and obj.part_id:
            self._applyHiveSizeMetadata(obj)

        if frames:
            best_idx = max(range(len(frames)), key=lambda i: self.sharpness(frames[i]))
            obj.thumbnail = self.encodeFrame(frames[best_idx])

        self.emitKnownObject()

    def _applyHiveSizeMetadata(self, obj) -> None:
        # Resolve physical dimensions from the primary Hive target and flag the
        # piece as too_big when any single axis exceeds the oversize limit. Hive
        # being unreachable must never block classification — best effort only.
        try:
            from hive_metadata import (
                OVERSIZE_MAX_DIMENSION_MM,
                getMetadataForPieceFromHive,
                isOversize,
                maxDimensionMm,
            )

            metadata = getMetadataForPieceFromHive(self.gc, obj.part_id)
            max_dim = maxDimensionMm(metadata)
            if max_dim is None:
                return
            obj.max_dimension_mm = max_dim
            obj.too_big = isOversize(max_dim)
            if obj.too_big:
                self.gc.logger.info(
                    f"piece {obj.uuid} part {obj.part_id} is oversize "
                    f"({max_dim:.1f}mm > {OVERSIZE_MAX_DIMENSION_MM}mm) -> misc bottom bin"
                )
        except Exception as exc:
            self.gc.logger.warn(f"hive size metadata lookup failed: {exc}")

    def dumpBurstCaptureArtifacts(
        self,
        all_captures: list[np.ndarray],
        selected_captures: list[np.ndarray],
        *,
        result: object | None,
        error: str | None,
    ) -> None:
        root = getattr(self.gc, "classification_burst_dump_root", None)
        piece = self.ctx.known_object
        if root is None or piece is None:
            return
        piece_uuid = getattr(piece, "uuid", None)
        if not isinstance(piece_uuid, str) or not piece_uuid:
            return
        piece_dir = Path(root) / piece_uuid
        captures_dir = piece_dir / "captures"
        selected_dir = piece_dir / "selected"
        try:
            captures_dir.mkdir(parents=True, exist_ok=True)
            selected_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} could not create burst dump dir: {exc}")
            return

        all_paths: list[str] = []
        for idx, image in enumerate(all_captures):
            path = captures_dir / f"burst_{idx:03d}.jpg"
            if self._writeJpeg(path, image):
                all_paths.append(str(path))

        selected_paths: list[str] = []
        for idx, image in enumerate(selected_captures):
            path = selected_dir / f"selected_{idx:03d}.jpg"
            if self._writeJpeg(path, image):
                selected_paths.append(str(path))

        manifest = {
            "piece_uuid": piece_uuid,
            "captured_count": len(all_captures),
            "selected_count": len(selected_captures),
            "capture_timestamps": list(self.ctx.captured_crop_timestamps[: len(all_captures)]),
            "capture_paths": all_paths,
            "selected_paths": selected_paths,
            "classification_error": error,
            "classification_result": result if isinstance(result, dict) else None,
            "brickognize_result": self._knownObjectResultSnapshot(),
        }
        try:
            (piece_dir / "brickognize_result.json").write_text(
                json.dumps(
                    {
                        "piece_uuid": piece_uuid,
                        "classification_error": error,
                        "classification_result": result if isinstance(result, dict) else None,
                        "brickognize_result": self._knownObjectResultSnapshot(),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            (piece_dir / "burst_manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True)
            )
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} could not write burst manifest: {exc}")

    def _knownObjectResultSnapshot(self) -> dict[str, object]:
        obj = self.ctx.known_object
        if obj is None:
            return {}
        return {
            "status": str(obj.classification_status.value)
            if hasattr(obj.classification_status, "value")
            else str(obj.classification_status),
            "part_id": obj.part_id,
            "part_name": obj.part_name,
            "part_category": obj.part_category,
            "color_id": obj.color_id,
            "color_name": obj.color_name,
            "confidence": obj.confidence,
            "brickognize_preview_url": obj.brickognize_preview_url,
            "brickognize_source_view": obj.brickognize_source_view,
        }

    @staticmethod
    def _writeJpeg(path: Path, image: np.ndarray) -> bool:
        if image is None or image.size == 0:
            return False
        try:
            ok = bool(
                cv2.imwrite(
                    str(path),
                    image,
                    [cv2.IMWRITE_JPEG_QUALITY, 80],
                )
            )
        except Exception:
            return False
        return ok
