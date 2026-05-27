"""Minimal RKNN inference wrapper for the benchmark.

Mirrors the live code's `RknnYoloProcessor._ensure_runtime` + `infer`:
- one runtime instance per (model, core_mask)
- pinned NPU core via init_runtime(core_mask=...)
- HWC uint8 RGB letterbox preprocessing
- inference returns N bounding boxes (we only need the count + shape for
  the benchmark; we do NOT do full YOLO decode, since the bench cares about
  the inference-call cost + GIL behavior, not detection accuracy)
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, List, Tuple

import cv2
import numpy as np


log = logging.getLogger("rknn_runner")


def _letterbox(image_bgr: np.ndarray, imgsz: int) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    scale = imgsz / max(h, w)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((imgsz, imgsz, 3), 114, dtype=np.uint8)
    canvas[:new_h, :new_w] = resized
    return canvas


class RknnRunner:
    """One instance per (model, NPU core). Thread-safe via internal lock."""

    def __init__(self, model_path: Path, imgsz: int = 320, core_mask_name: str = "NPU_CORE_AUTO"):
        self.model_path = Path(model_path)
        self.imgsz = imgsz
        self.core_mask_name = core_mask_name
        self._lock = threading.Lock()
        self._runtime: Any = None
        self._infer_count = 0

    def _ensure(self) -> Any:
        if self._runtime is not None:
            return self._runtime
        with self._lock:
            if self._runtime is not None:
                return self._runtime
            from rknnlite.api import RKNNLite  # type: ignore
            rknn = RKNNLite()
            if rknn.load_rknn(str(self.model_path)) != 0:
                raise RuntimeError(f"load_rknn failed for {self.model_path}")
            mask = getattr(rknn, self.core_mask_name, None) or getattr(rknn, "NPU_CORE_AUTO", None)
            if mask is None:
                ret = rknn.init_runtime()
            else:
                ret = rknn.init_runtime(core_mask=mask)
            if ret != 0:
                raise RuntimeError(f"init_runtime failed (mask={self.core_mask_name})")
            self._runtime = rknn
            log.warning("RKNN runtime ready: %s (core=%s)", self.model_path.name, self.core_mask_name)
            return self._runtime

    def infer(self, image_bgr: np.ndarray) -> Tuple[int, float]:
        """Return (output_tensor_count, infer_ms). We don't decode YOLO here;
        the bench only needs to measure the cost and contention of the call."""
        rknn = self._ensure()
        blob = _letterbox(image_bgr, self.imgsz)
        blob = cv2.cvtColor(blob, cv2.COLOR_BGR2RGB)
        blob = np.expand_dims(blob, axis=0)
        t0 = time.perf_counter()
        # rknn.inference holds the GIL in the Python binding; the actual NPU
        # work happens off-CPU. We measure the wall-clock cost of the call.
        with self._lock:
            outputs = rknn.inference(inputs=[blob])
        infer_ms = (time.perf_counter() - t0) * 1000.0
        self._infer_count += 1
        return (len(outputs) if outputs else 0), infer_ms

    def stats(self) -> dict:
        return {"infer_count": self._infer_count, "model": self.model_path.name}
