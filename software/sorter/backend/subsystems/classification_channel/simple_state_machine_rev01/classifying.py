import threading
import time
from typing import Optional

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

    def step(self) -> Optional[ClassificationChannelState]:
        now = time.monotonic()

        if not self._submitted:
            self.ctx.classify_started_at = now
            all_captures = list(self.ctx.captured_crops)
            captures = self.selectRecognitionCrops(all_captures)
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
            return ClassificationChannelState.REV01_DISCHARGING

        if now - self.ctx.classify_started_at > self.ctx.config.classify_timeout_s:
            self.logger.error(
                f"{LOG_TAG} Brickognize timed out after {self.ctx.config.classify_timeout_s}s — "
                f"continuing to DISCHARGING"
            )
            return ClassificationChannelState.REV01_DISCHARGING

        return None

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
            others = [i for i in range(len(frames)) if i != best_idx]
            if others:
                obj.top_image = self.encodeFrame(frames[others[0]])
            if len(others) >= 2:
                obj.bottom_image = self.encodeFrame(frames[others[-1]])

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
