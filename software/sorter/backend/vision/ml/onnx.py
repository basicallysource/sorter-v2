"""ONNX detection processors (CPU + CoreML when available)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from .base import (
    BaseProcessor,
    Detection,
    decode_nanodet,
    decode_yolo,
    preprocess_nanodet,
    preprocess_yolo,
)


log = logging.getLogger(__name__)


def _make_session(model_path: Path) -> Any:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    providers = ["CPUExecutionProvider"]
    try:
        available = set(ort.get_available_providers())
    except Exception:
        available = set()
    if "CoreMLExecutionProvider" in available:
        providers = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    return ort.InferenceSession(str(model_path), sess_options=options, providers=providers)


class _OnnxMixin:
    model_path: Path
    _lock: Any
    _session: Any = None
    _input_name: str = ""

    def _ensure_session(self) -> Any:
        with self._lock:
            if self._session is None:
                log.info("Loading ONNX session for %s", self.model_path)
                self._session = _make_session(self.model_path)
                self._input_name = self._session.get_inputs()[0].name
            return self._session


class OnnxYoloProcessor(_OnnxMixin, BaseProcessor):
    family = "yolo"
    runtime = "onnx"

    def infer(self, image_bgr: np.ndarray) -> list[Detection]:
        session = self._ensure_session()
        blob, pre = preprocess_yolo(image_bgr, self.imgsz)
        outputs = session.run(None, {self._input_name: blob})
        return decode_yolo(
            outputs[0],
            pre=pre,
            conf_threshold=self.conf_threshold,
            iou_threshold=self.iou_threshold,
        )


class OnnxNanodetProcessor(_OnnxMixin, BaseProcessor):
    family = "nanodet"
    runtime = "onnx"

    def __init__(
        self,
        model_path: Path,
        *,
        imgsz: int,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        reg_max: int = 7,
        strides: tuple[int, ...] = (8, 16, 32, 64),
    ) -> None:
        super().__init__(
            model_path,
            imgsz=imgsz,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
        )
        self.reg_max = int(reg_max)
        self.strides = tuple(int(s) for s in strides)

    def infer(self, image_bgr: np.ndarray) -> list[Detection]:
        session = self._ensure_session()
        blob, pre = preprocess_nanodet(image_bgr, self.imgsz)
        outputs = session.run(None, {self._input_name: blob})
        return decode_nanodet(
            outputs[0],
            pre=pre,
            imgsz=self.imgsz,
            reg_max=self.reg_max,
            strides=self.strides,
            conf_threshold=self.conf_threshold,
            iou_threshold=self.iou_threshold,
        )
