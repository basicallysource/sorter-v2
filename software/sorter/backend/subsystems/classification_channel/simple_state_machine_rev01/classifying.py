import json
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from classification.brickognize import _classifyImages
from defs.known_object import ClassificationStatus
from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


class Classifying(Rev01BaseState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._submitted = False
        self._submitted_captures: list[np.ndarray] = []

    def step(self) -> Optional[ClassificationChannelState]:
        now = time.monotonic()
        self.setClassificationReady(False, "classifying")

        if not self._submitted:
            self.ctx.classify_started_at = now
            all_captures = list(self.ctx.captured_crops)
            captures = self.selectRecognitionCrops(all_captures)
            self._submitted_captures = list(captures)
            self._submitted = True
            if not captures:
                self.logger.warning(
                    f"{LOG_TAG} CLASSIFYING with zero captures — skipping Brickognize call"
                )
                self.ctx.classification_error = "no_captures"
                return ClassificationChannelState.REV01_DISCHARGING

            total_bytes = sum(int(f.nbytes) for f in captures)
            self.logger.info(
                f"{LOG_TAG} submitting {len(captures)} of {len(all_captures)} captured images to Brickognize "
                f"(~{total_bytes / 1024:.1f} KiB raw)"
            )
            self._spawnClassifyThread(captures)

        with self.ctx.classify_lock:
            result = self.ctx.classification_result
            error = self.ctx.classification_error

        if result is not None or error is not None:
            elapsed = now - self.ctx.classify_started_at
            if error is not None:
                self.logger.error(
                    f"{LOG_TAG} Brickognize call failed after {elapsed:.2f}s: {error}"
                )
            else:
                items = result.get("items", []) if isinstance(result, dict) else []
                self.logger.info(
                    f"{LOG_TAG} Brickognize returned {len(items)} item(s) in "
                    f"{elapsed:.2f}s; top={items[0] if items else None}"
                )
                for i, item in enumerate(items[:5]):
                    self.logger.info(f"{LOG_TAG}   item[{i}]={item}")
            self._updateKnownObjectWithResult(result, error)
            self._dumpBurstCaptureArtifacts(
                all_captures=list(self.ctx.captured_crops),
                selected_captures=self._submitted_captures,
                result=result,
                error=error,
            )
            return ClassificationChannelState.REV01_DISCHARGING

        if now - self.ctx.classify_started_at > self.ctx.config.classify_timeout_s:
            self.logger.error(
                f"{LOG_TAG} Brickognize timed out after {self.ctx.config.classify_timeout_s}s — "
                f"continuing to DISCHARGING"
            )
            self._dumpBurstCaptureArtifacts(
                all_captures=list(self.ctx.captured_crops),
                selected_captures=self._submitted_captures,
                result=None,
                error="timeout",
            )
            return ClassificationChannelState.REV01_DISCHARGING
        return None

    def _dumpBurstCaptureArtifacts(
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

    def _updateKnownObjectWithResult(self, result: object, error: Optional[str]) -> None:
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

        if frames:
            best_idx = max(range(len(frames)), key=lambda i: self.sharpness(frames[i]))
            obj.thumbnail = self.encodeFrame(frames[best_idx])

        self.emitKnownObject()

    def selectRecognitionCrops(self, crops: list[np.ndarray]) -> list[np.ndarray]:
        n = self.ctx.config.max_captures
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

    def _spawnClassifyThread(self, captures: list[np.ndarray]) -> None:
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

    def cleanup(self) -> None:
        super().cleanup()
        self._submitted = False
        self._submitted_captures = []
