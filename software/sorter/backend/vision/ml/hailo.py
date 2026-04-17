"""Hailo-8 HEF detection processors.

Ported from ``software/training/src/training/reports/benchmark.py``:

- ``_HailoRunner`` → ``_HailoSession`` (owns VDevice lifecycle)
- ``_decode_hailo_yolo_output`` → ``_decode_hailo_yolo``
- ``_flatten_hailo_nanodet_outputs`` → ``_flatten_nanodet_outputs`` (then feeds the
  shared NanoDet decoder in ``base.decode_nanodet``)

Only runs on machines with HailoRT + a Hailo accelerator (``hailo_platform``
import). On other platforms the import raises a clear error.
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
    decode_nanodet,
    letterbox,
    nms,
)


log = logging.getLogger(__name__)

HAILO_TIMEOUT_MS = 10_000


class _HailoSession:
    """Owns the VDevice + configured network group for a single HEF."""

    def __init__(self, hef_path: Path):
        try:
            from hailo_platform import (
                ConfigureParams,
                FormatType,
                HailoStreamInterface,
                HEF,
                InferVStreams,
                InputVStreamParams,
                OutputVStreamParams,
                VDevice,
            )
        except ImportError as exc:
            raise RuntimeError(
                "hailo_platform is not installed. Install python3-hailort and the Hailo "
                "runtime on this device to use Hailo inference."
            ) from exc

        self.hef_path = Path(hef_path)
        self._vdevice = VDevice()
        self._hef = HEF(str(self.hef_path))
        configure_params = ConfigureParams.create_from_hef(self._hef, HailoStreamInterface.PCIe)
        configured_networks = self._vdevice.configure(self._hef, configure_params)
        if not configured_networks:
            raise RuntimeError(f"Could not configure HEF: {self.hef_path}")
        self._network_group = configured_networks[0]
        self.input_name = self._hef.get_input_vstream_infos()[0].name
        self.output_names = [info.name for info in self._hef.get_output_vstream_infos()]

        input_params = InputVStreamParams.make_from_network_group(
            self._network_group,
            quantized=False,
            format_type=FormatType.UINT8,
            timeout_ms=HAILO_TIMEOUT_MS,
        )
        output_params = OutputVStreamParams.make_from_network_group(
            self._network_group,
            quantized=False,
            format_type=FormatType.FLOAT32,
            timeout_ms=HAILO_TIMEOUT_MS,
        )
        self._activation = self._network_group.activate(self._network_group.create_params())
        self._activation.__enter__()
        self._pipeline = InferVStreams(self._network_group, input_params, output_params)
        self._pipeline.__enter__()

    def close(self) -> None:
        pipeline = getattr(self, "_pipeline", None)
        if pipeline is not None:
            try:
                pipeline.__exit__(None, None, None)
            except Exception:
                pass
            self._pipeline = None
        activation = getattr(self, "_activation", None)
        if activation is not None:
            try:
                activation.__exit__(None, None, None)
            except Exception:
                pass
            self._activation = None
        vdevice = getattr(self, "_vdevice", None)
        if vdevice is not None:
            try:
                vdevice.release()
            except Exception:
                pass
            self._vdevice = None

    def infer(self, input_buffer: np.ndarray) -> Any:
        batch = np.ascontiguousarray(input_buffer)
        if batch.ndim == 3:
            batch = batch[None, ...]
        outputs = self._pipeline.infer({self.input_name: batch})
        if len(outputs) == 1:
            return next(iter(outputs.values()))
        return outputs


def _decode_hailo_yolo_box(
    raw_box: list[float],
    *,
    preprocess: dict[str, float],
    assume_yxyx: bool,
) -> list[int] | None:
    coords = np.asarray(raw_box[:4], dtype=np.float32)
    if np.max(np.abs(coords)) <= 1.5:
        coords = coords * float(preprocess["input_size"])
    if assume_yxyx:
        y1, x1, y2, x2 = coords.tolist()
    else:
        x1, y1, x2, y2 = coords.tolist()
    x1 = (x1 - preprocess["pad_x"]) / preprocess["scale"]
    y1 = (y1 - preprocess["pad_y"]) / preprocess["scale"]
    x2 = (x2 - preprocess["pad_x"]) / preprocess["scale"]
    y2 = (y2 - preprocess["pad_y"]) / preprocess["scale"]
    x1 = max(0.0, min(float(preprocess["original_w"]), x1))
    y1 = max(0.0, min(float(preprocess["original_h"]), y1))
    x2 = max(0.0, min(float(preprocess["original_w"]), x2))
    y2 = max(0.0, min(float(preprocess["original_h"]), y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return [int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))]


def _decode_hailo_yolo(
    output: Any,
    *,
    preprocess: dict[str, float],
    conf_threshold: float,
    iou_threshold: float,
) -> list[Detection]:
    class_outputs = output if isinstance(output, list) else [output]
    boxes: list[list[int]] = []
    scores: list[float] = []
    for class_output in class_outputs:
        array = np.asarray(class_output)
        if array.size == 0:
            continue
        if array.ndim == 3 and array.shape[0] == 1:
            array = array[0]
        if array.ndim == 1:
            if array.size % 5 != 0:
                raise RuntimeError(f"Unexpected Hailo YOLO output shape: {array.shape}")
            array = array.reshape(-1, 5)
        if array.ndim == 3 and array.shape[-1] >= 5:
            array = array.reshape(-1, array.shape[-1])
        if array.ndim != 2 or array.shape[1] < 5:
            raise RuntimeError(f"Unexpected Hailo YOLO output shape: {array.shape}")
        for row in array:
            score = float(row[4])
            if score < conf_threshold:
                continue
            box = _decode_hailo_yolo_box(row.tolist(), preprocess=preprocess, assume_yxyx=True)
            if box is None:
                box = _decode_hailo_yolo_box(row.tolist(), preprocess=preprocess, assume_yxyx=False)
            if box is None:
                continue
            boxes.append(box)
            scores.append(score)
    if not boxes:
        return []
    boxes_np = np.asarray(boxes, dtype=np.float32)
    scores_np = np.asarray(scores, dtype=np.float32)
    kept = nms(boxes_np, scores_np, iou_threshold)
    return [
        Detection(
            bbox=(
                int(round(boxes_np[i, 0])),
                int(round(boxes_np[i, 1])),
                int(round(boxes_np[i, 2])),
                int(round(boxes_np[i, 3])),
            ),
            score=float(scores_np[i]),
        )
        for i in kept
    ]


def _flatten_hailo_nanodet_outputs(output: Any) -> np.ndarray:
    if isinstance(output, dict):
        arrays = [
            np.asarray(value)
            for _, value in sorted(output.items(), key=lambda item: (-np.asarray(item[1]).shape[1], item[0]))
        ]
    elif isinstance(output, list):
        arrays = [np.asarray(value) for value in output]
        arrays.sort(key=lambda value: -value.shape[1])
    else:
        raise RuntimeError(f"Unexpected Hailo NanoDet output container: {type(output)!r}")

    flattened: list[np.ndarray] = []
    for array in arrays:
        if array.ndim == 4 and array.shape[0] == 1:
            array = array[0]
        if array.ndim != 3:
            raise RuntimeError(f"Unexpected Hailo NanoDet output shape: {array.shape}")
        flattened.append(array.reshape(-1, array.shape[-1]))
    if not flattened:
        raise RuntimeError("Hailo NanoDet inference returned no outputs.")
    return np.concatenate(flattened, axis=0)


class _HailoMixin:
    model_path: Path
    _lock: Any
    _session: _HailoSession | None = None

    def _ensure_session(self) -> _HailoSession:
        with self._lock:
            if self._session is None:
                log.info("Loading Hailo HEF %s", self.model_path)
                self._session = _HailoSession(self.model_path)
            return self._session

    def close(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None


class HailoYoloProcessor(_HailoMixin, BaseProcessor):
    family = "yolo"
    runtime = "hailo"

    def infer(self, image_bgr: np.ndarray) -> list[Detection]:
        session = self._ensure_session()
        letterboxed, scale, pad_x, pad_y = letterbox(image_bgr, self.imgsz)
        rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
        pre = {
            "scale": scale,
            "pad_x": float(pad_x),
            "pad_y": float(pad_y),
            "input_size": float(self.imgsz),
            "original_w": float(image_bgr.shape[1]),
            "original_h": float(image_bgr.shape[0]),
        }
        with self._lock:
            raw = session.infer(np.ascontiguousarray(rgb, dtype=np.uint8))
        return _decode_hailo_yolo(
            raw,
            preprocess=pre,
            conf_threshold=self.conf_threshold,
            iou_threshold=self.iou_threshold,
        )


class HailoNanodetProcessor(_HailoMixin, BaseProcessor):
    family = "nanodet"
    runtime = "hailo"

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
        resized = cv2.resize(
            image_bgr,
            (self.imgsz, self.imgsz),
            interpolation=cv2.INTER_LINEAR,
        )
        pre = {
            "original_w": float(image_bgr.shape[1]),
            "original_h": float(image_bgr.shape[0]),
        }
        with self._lock:
            raw = session.infer(np.ascontiguousarray(resized, dtype=np.uint8))
        output = _flatten_hailo_nanodet_outputs(raw)
        return decode_nanodet(
            output,
            pre=pre,
            imgsz=self.imgsz,
            reg_max=self.reg_max,
            strides=self.strides,
            conf_threshold=self.conf_threshold,
            iou_threshold=self.iou_threshold,
        )
