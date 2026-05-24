"""Rockchip RKNN detection processors (RK3588 NPU).

Mirrors ``onnx.py`` / ``ncnn.py``: load once, run repeatedly, share between
threads with a lock. Three independent NPU cores on RK3588 are exposed via
``init_runtime(core_mask=...)`` — we try the most-parallel mask first and
gracefully fall back so older ``rknn-toolkit-lite2`` builds with fewer
constants still work.

The RKNN graph for our INT8 YOLO export expects **HWC uint8** inputs in
``[0, 255]`` — the mean/std subtraction lives inside the graph (configured
at convert time). Do NOT pre-normalize to float32 — passing the same blob
ONNX uses produces silent garbage outputs.

The current bundled artifact (`_MEDIOCRE_CONVERSION`) carries a broken
sigmoid: confidences come out roughly logit-shaped and can exceed 1. We
ship raw pass-through here per agent-notes decision — operators can drop
the conf threshold close to 0 to surface boxes, and use this purely for
pipeline validation, not production accuracy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .base import (
    BaseProcessor,
    Detection,
    decode_yolo,
    decode_yolo_head_stripped,
    letterbox,
)


log = logging.getLogger(__name__)


_DEFAULT_MASK_FALLBACK_NAMES: tuple[str, ...] = ("NPU_CORE_0_1_2", "NPU_CORE_AUTO", "NPU_CORE_0")


def _try_init_runtime(rknn: Any, mask_names: tuple[str, ...]) -> int:
    """Try the given core masks in order until one succeeds. Returns 0 on success."""
    attempts: list[Any] = []
    for name in mask_names:
        mask = getattr(rknn, name, None)
        if mask is not None:
            attempts.append(mask)
    for mask in attempts:
        try:
            ret = rknn.init_runtime(core_mask=mask)
            if ret == 0:
                return 0
        except Exception:
            continue
    return rknn.init_runtime()


class _RknnMixin:
    model_path: Path
    imgsz: int
    _lock: Any
    _runtime: Any = None
    _load_failed: bool = False
    core_mask_name: str | None = None

    def _ensure_runtime(self) -> Any:
        with self._lock:
            if self._load_failed:
                raise RuntimeError(f"RKNN model load permanently failed: {self.model_path}")
            if self._runtime is None:
                log.warning(
                    "Loading RKNN runtime for %s (core_mask=%s)",
                    self.model_path,
                    self.core_mask_name or "default",
                )
                try:
                    from rknnlite.api import RKNNLite  # type: ignore
                except Exception as exc:
                    self._load_failed = True
                    raise RuntimeError(
                        f"rknn-toolkit-lite2 not importable: {exc}"
                    ) from exc
                rknn = RKNNLite()
                try:
                    if rknn.load_rknn(str(self.model_path)) != 0:
                        raise RuntimeError("RKNNLite.load_rknn failed")
                    if self.core_mask_name is not None:
                        mask_names = (self.core_mask_name,)
                    else:
                        mask_names = _DEFAULT_MASK_FALLBACK_NAMES
                    if _try_init_runtime(rknn, mask_names) != 0:
                        raise RuntimeError(
                            f"RKNNLite.init_runtime failed (masks={mask_names})"
                        )
                except Exception:
                    self._load_failed = True
                    try:
                        rknn.release()
                    except Exception:
                        pass
                    raise
                self._runtime = rknn
            return self._runtime


def _preprocess_rknn_yolo(
    image_bgr: np.ndarray, imgsz: int
) -> tuple[np.ndarray, dict[str, float]]:
    """HWC uint8 RGB letterbox — RKNN graph normalizes internally."""
    letterboxed, scale, pad_x, pad_y = letterbox(image_bgr, imgsz)
    rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
    # RKNN expects NHWC — wrap the HWC frame in a batch axis.
    nhwc = np.expand_dims(rgb, axis=0)
    return nhwc, {
        "scale": scale,
        "pad_x": pad_x,
        "pad_y": pad_y,
        "original_w": float(image_bgr.shape[1]),
        "original_h": float(image_bgr.shape[0]),
    }


class RknnYoloProcessor(_RknnMixin, BaseProcessor):
    family = "yolo"
    runtime = "rknn"

    def __init__(
        self,
        model_path: Path,
        *,
        imgsz: int,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        core_mask_name: str | None = None,
    ) -> None:
        super().__init__(
            model_path,
            imgsz=imgsz,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
        )
        self.core_mask_name = core_mask_name

    def infer(
        self,
        image_bgr: np.ndarray,
        *,
        conf_threshold: float | None = None,
    ) -> list[Detection]:
        rknn = self._ensure_runtime()
        blob, pre = _preprocess_rknn_yolo(image_bgr, self.imgsz)
        outputs = rknn.inference(inputs=[blob])
        if not outputs:
            return []
        conf = float(conf_threshold) if conf_threshold is not None else self.conf_threshold
        # Head-stripped models produce 3 separate [1, C, H, W] tensors per scale.
        # Fused models produce a single [1, N, 5+] tensor.
        if len(outputs) == 3 and np.asarray(outputs[0]).ndim == 4:
            return decode_yolo_head_stripped(
                outputs,
                pre=pre,
                imgsz=self.imgsz,
                conf_threshold=conf,
                iou_threshold=self.iou_threshold,
            )
        return decode_yolo(
            outputs[0],
            pre=pre,
            conf_threshold=conf,
            iou_threshold=self.iou_threshold,
        )
