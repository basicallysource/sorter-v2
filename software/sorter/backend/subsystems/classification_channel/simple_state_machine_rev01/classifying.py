import threading
import time
from typing import Optional

import numpy as np

from classification.brickognize import _classifyImages
from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import CLASSIFY_TIMEOUT_S, LOG_TAG


class Classifying(Rev01BaseState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._submitted = False

    def step(self) -> Optional[ClassificationChannelState]:
        now = time.monotonic()

        if not self._submitted:
            self.ctx.classify_started_at = now
            captures = list(self.ctx.captured_frames)
            self._submitted = True
            if not captures:
                self.logger.warning(
                    f"{LOG_TAG} CLASSIFYING with zero captures — skipping Brickognize call"
                )
                self.ctx.classification_error = "no_captures"
                return ClassificationChannelState.REV01_DISCHARGING

            total_bytes = sum(int(f.nbytes) for f in captures)
            self.logger.info(
                f"{LOG_TAG} submitting {len(captures)} images to Brickognize "
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
            return ClassificationChannelState.REV01_DISCHARGING

        if now - self.ctx.classify_started_at > CLASSIFY_TIMEOUT_S:
            self.logger.error(
                f"{LOG_TAG} Brickognize timed out after {CLASSIFY_TIMEOUT_S}s — "
                f"continuing to DISCHARGING"
            )
            return ClassificationChannelState.REV01_DISCHARGING

        return None

    def _spawnClassifyThread(self, captures: list[np.ndarray]) -> None:
        def _run() -> None:
            try:
                result = _classifyImages(captures)
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
