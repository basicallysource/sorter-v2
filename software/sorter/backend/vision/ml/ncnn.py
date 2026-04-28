"""NCNN detection processors (CPU, ARM-friendly).

Processor constructor expects ``model_path`` pointing at the ``.param`` file.
The sibling ``.bin`` is located by replacing the suffix. Input + output blob
names are parsed from the ``.param`` file or overridden via the constructor.
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
    NANODET_MEAN,
    NANODET_STD,
    decode_nanodet,
    decode_yolo,
    letterbox,
)


log = logging.getLogger(__name__)


def _parse_param_blobs(param_path: Path) -> tuple[str, str]:
    """Extract the first input blob and the last output blob from a .param file.

    NCNN .param format (after the magic and counts line) is one layer per line:

        <layer_type> <layer_name> <bottom_count> <top_count> [bottoms...] [tops...] [kv-args...]

    We find the first ``Input`` layer (its single top is the model input blob)
    and take the last layer's first top as the primary output.
    """
    lines = [line.strip() for line in param_path.read_text().splitlines() if line.strip()]
    # Drop magic number line + count line.
    body = [ln for ln in lines if not ln.startswith("7767517") and not _is_counts_line(ln)]
    input_blob: str | None = None
    last_top: str | None = None
    for line in body:
        tokens = line.split()
        if len(tokens) < 4:
            continue
        layer_type = tokens[0]
        try:
            bottom_count = int(tokens[2])
            top_count = int(tokens[3])
        except ValueError:
            continue
        first_top_index = 4 + bottom_count
        if first_top_index >= len(tokens) or top_count <= 0:
            continue
        top_names = tokens[first_top_index : first_top_index + top_count]
        if not top_names:
            continue
        if input_blob is None and layer_type == "Input":
            input_blob = top_names[0]
        last_top = top_names[-1]
    return (input_blob or "in0", last_top or "out0")


def _is_counts_line(line: str) -> bool:
    parts = line.split()
    return len(parts) == 2 and all(token.isdigit() for token in parts)


class _NcnnMixin:
    model_path: Path
    _lock: Any
    _net: Any = None
    _input_blob: str = ""
    _output_blob: str = ""

    def __init__(
        self,
        model_path: Path,
        *,
        imgsz: int,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        input_blob: str | None = None,
        output_blob: str | None = None,
        use_vulkan: bool = False,
        **extra: Any,
    ) -> None:
        super().__init__(
            model_path,
            imgsz=imgsz,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            **extra,
        )
        self._input_blob_override = input_blob
        self._output_blob_override = output_blob
        self._use_vulkan = bool(use_vulkan)

    def _ensure_net(self) -> Any:
        with self._lock:
            if self._net is not None:
                return self._net
            try:
                import ncnn
            except ImportError as exc:
                raise RuntimeError(
                    "The 'ncnn' package is required for NCNN inference. "
                    "Install it on the target device (e.g. `pip install ncnn`)."
                ) from exc
            param_path = self.model_path
            bin_path = param_path.with_suffix(".bin")
            if not param_path.exists():
                raise FileNotFoundError(f".param missing: {param_path}")
            if not bin_path.exists():
                raise FileNotFoundError(f".bin missing: {bin_path}")
            detected_input, detected_output = _parse_param_blobs(param_path)
            self._input_blob = self._input_blob_override or detected_input
            self._output_blob = self._output_blob_override or detected_output
            gpu_count = 0
            if self._use_vulkan:
                try:
                    gpu_count = int(ncnn.get_gpu_count())
                except Exception as exc:
                    log.warning(
                        "ncnn.get_gpu_count() failed (%s) — falling back to CPU", exc
                    )
                    gpu_count = 0
            vulkan_enabled = bool(self._use_vulkan) and gpu_count > 0
            if self._use_vulkan and not vulkan_enabled:
                log.warning(
                    "Vulkan requested for %s but no Vulkan device available — falling back to CPU",
                    param_path,
                )
            net = ncnn.Net()
            net.opt.use_vulkan_compute = vulkan_enabled
            net.load_param(str(param_path))
            net.load_model(str(bin_path))
            self._net = net
            log.info(
                "Loaded NCNN net %s (input=%s output=%s vulkan=%s)",
                param_path,
                self._input_blob,
                self._output_blob,
                vulkan_enabled,
            )
            return net


def _extract(net: Any, input_blob: str, output_blob: str, ncnn_in: Any) -> np.ndarray:
    ex = net.create_extractor()
    ex.input(input_blob, ncnn_in)
    _ret, ncnn_out = ex.extract(output_blob)
    return np.array(ncnn_out)


class NcnnYoloProcessor(_NcnnMixin, BaseProcessor):
    family = "yolo"
    runtime = "ncnn"

    def infer(self, image_bgr: np.ndarray) -> list[Detection]:
        net = self._ensure_net()
        import ncnn  # guaranteed to import after _ensure_net
        letterboxed, scale, pad_x, pad_y = letterbox(image_bgr, self.imgsz)
        # NCNN likes contiguous uint8 arrays; convert BGR→RGB channel order via PIXEL_BGR2RGB.
        ncnn_in = ncnn.Mat.from_pixels(
            np.ascontiguousarray(letterboxed),
            ncnn.Mat.PixelType.PIXEL_BGR2RGB,
            self.imgsz,
            self.imgsz,
        )
        ncnn_in.substract_mean_normalize([0.0, 0.0, 0.0], [1.0 / 255.0, 1.0 / 255.0, 1.0 / 255.0])

        with self._lock:
            output = _extract(net, self._input_blob, self._output_blob, ncnn_in)
        pre = {
            "scale": scale,
            "pad_x": float(pad_x),
            "pad_y": float(pad_y),
            "original_w": float(image_bgr.shape[1]),
            "original_h": float(image_bgr.shape[0]),
        }
        return decode_yolo(
            output,
            pre=pre,
            conf_threshold=self.conf_threshold,
            iou_threshold=self.iou_threshold,
        )


class NcnnNanodetProcessor(_NcnnMixin, BaseProcessor):
    family = "nanodet"
    runtime = "ncnn"

    def __init__(
        self,
        model_path: Path,
        *,
        imgsz: int,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        reg_max: int = 7,
        strides: tuple[int, ...] = (8, 16, 32, 64),
        input_blob: str | None = None,
        output_blob: str | None = None,
        use_vulkan: bool = False,
    ) -> None:
        super().__init__(
            model_path,
            imgsz=imgsz,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            input_blob=input_blob,
            output_blob=output_blob,
            use_vulkan=use_vulkan,
        )
        self.reg_max = int(reg_max)
        self.strides = tuple(int(s) for s in strides)

    def infer(self, image_bgr: np.ndarray) -> list[Detection]:
        net = self._ensure_net()
        import ncnn  # guaranteed to import after _ensure_net
        resized = cv2.resize(
            image_bgr,
            (self.imgsz, self.imgsz),
            interpolation=cv2.INTER_LINEAR,
        )
        ncnn_in = ncnn.Mat.from_pixels(
            np.ascontiguousarray(resized),
            ncnn.Mat.PixelType.PIXEL_BGR,
            self.imgsz,
            self.imgsz,
        )
        mean_vals = [float(v) for v in NANODET_MEAN.tolist()]
        norm_vals = [1.0 / float(v) for v in NANODET_STD.tolist()]
        ncnn_in.substract_mean_normalize(mean_vals, norm_vals)

        with self._lock:
            output = _extract(net, self._input_blob, self._output_blob, ncnn_in)
        pre = {
            "original_w": float(image_bgr.shape[1]),
            "original_h": float(image_bgr.shape[0]),
        }
        return decode_nanodet(
            output,
            pre=pre,
            imgsz=self.imgsz,
            reg_max=self.reg_max,
            strides=self.strides,
            conf_threshold=self.conf_threshold,
            iou_threshold=self.iou_threshold,
        )
