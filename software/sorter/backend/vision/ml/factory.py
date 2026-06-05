"""Factory + metadata helpers shared by the registry and VisionManager.

The ``create_processor`` entry picks the right processor class based on the
``(runtime, model_family)`` tuple and resolves the on-disk location of the
model artifact inside a ``hive-<id>/`` directory.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .base import BaseProcessor


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inference device policy
# ---------------------------------------------------------------------------
# Detection inference must run on the NPU/accelerator by default. CPU runtimes
# (onnx/ncnn/pytorch) quietly turning up — e.g. an overlay detector resolving to
# an onnx model variant — saturate the CPU and starve the live pipeline (the NPU
# sits idle while the CPU melts). So CPU inference is an explicit, warned
# exception: it is refused unless SORTER_ALLOW_CPU_INFERENCE is set.
_CPU_INFERENCE_RUNTIMES = frozenset({"onnx", "ncnn", "pytorch", "torch"})


class CpuInferenceForbiddenError(RuntimeError):
    """A CPU inference runtime was requested without explicit opt-in."""


def cpu_inference_allowed() -> bool:
    return os.environ.get("SORTER_ALLOW_CPU_INFERENCE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _enforce_inference_device_policy(runtime: str, model_path: Path) -> None:
    if runtime not in _CPU_INFERENCE_RUNTIMES:
        return
    if cpu_inference_allowed():
        log.warning(
            "CPU inference ENABLED (SORTER_ALLOW_CPU_INFERENCE) for runtime=%s model=%s — "
            "this loads the CPU and is meant to be a deliberate exception, not the norm.",
            runtime,
            model_path,
        )
        return
    log.error(
        "Refusing CPU inference for runtime=%s model=%s. Detection must run on the NPU "
        "(rknn). Assign an rknn model variant, or set SORTER_ALLOW_CPU_INFERENCE=1 to "
        "explicitly allow CPU inference.",
        runtime,
        model_path,
    )
    raise CpuInferenceForbiddenError(
        f"CPU inference refused for runtime={runtime!r} (model={model_path}); "
        "use an NPU (rknn) variant or set SORTER_ALLOW_CPU_INFERENCE=1."
    )


def create_processor(
    *,
    model_path: Path,
    model_family: str,
    runtime: str,
    imgsz: int,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
    rknn_core_mask_name: str | None = None,
) -> BaseProcessor:
    family = (model_family or "").lower()
    runtime = (runtime or "onnx").lower()

    # NPU by default; CPU inference only as an explicitly-enabled exception.
    _enforce_inference_device_policy(runtime, model_path)

    if runtime == "onnx":
        from .onnx import OnnxNanodetProcessor, OnnxYoloProcessor

        if family == "yolo":
            return OnnxYoloProcessor(
                model_path,
                imgsz=imgsz,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
            )
        if family == "nanodet":
            return OnnxNanodetProcessor(
                model_path,
                imgsz=imgsz,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
            )

    if runtime == "ncnn":
        from .ncnn import NcnnNanodetProcessor, NcnnYoloProcessor

        if family == "yolo":
            return NcnnYoloProcessor(
                model_path,
                imgsz=imgsz,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
            )
        if family == "nanodet":
            return NcnnNanodetProcessor(
                model_path,
                imgsz=imgsz,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
            )

    if runtime == "rknn":
        from .rknn import RknnYoloProcessor

        if family == "yolo":
            return RknnYoloProcessor(
                model_path,
                imgsz=imgsz,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
                core_mask_name=rknn_core_mask_name,
            )
        # NanoDet on RKNN is intentionally not wired yet — no .rknn nanodet
        # artifact in scope. Add when the export pipeline produces one.

    if runtime == "hailo":
        from .hailo import HailoNanodetProcessor, HailoYoloProcessor

        if family == "yolo":
            return HailoYoloProcessor(
                model_path,
                imgsz=imgsz,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
            )
        if family == "nanodet":
            return HailoNanodetProcessor(
                model_path,
                imgsz=imgsz,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
            )

    raise ValueError(
        f"Unsupported combination runtime={runtime!r} family={family!r}"
    )


def imgsz_from_run_metadata(meta: dict) -> int:
    """Best-effort extraction of input-size from a run.json payload."""
    for key in ("imgsz", "input_size", "image_size"):
        value = meta.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], int):
            return int(value[0])
    dataset = meta.get("dataset")
    if isinstance(dataset, dict):
        imgsz = dataset.get("imgsz")
        if isinstance(imgsz, int) and imgsz > 0:
            return imgsz
    run_name = str(meta.get("run_name") or "")
    for token in run_name.replace("_", "-").split("-"):
        if token.isdigit() and int(token) in (160, 224, 320, 416, 512, 640):
            return int(token)
    return 320


def resolve_variant_artifact(run_dir: Path, runtime: str) -> Path | None:
    """Find the on-disk model file/dir for a given ``variant_runtime`` inside a hive model dir.

    Layout assumptions (matches ``DownloadJobManager`` behavior):
      onnx   → ``exports/best.onnx`` (strict; renaming the file disables the model)
      ncnn   → a directory inside ``exports/`` with ``*_ncnn_model`` in its name containing
               a ``.param`` file (the extracted tarball). Returns the ``.param`` path.
      hailo  → ``exports/*.hef`` (the tar bundle should have been extracted during download
               for hailo variants that ship as ``.tar.gz``).
      pytorch → ``exports/*.pt`` (not currently used by any runtime processor)
    """
    exports = run_dir / "exports"
    if not exports.exists():
        return None

    rt = runtime.lower()
    if rt == "onnx":
        preferred = exports / "best.onnx"
        if preferred.exists():
            return preferred
        return None

    if rt == "ncnn":
        for ncnn_dir in sorted(exports.iterdir()):
            if not ncnn_dir.is_dir() or "ncnn" not in ncnn_dir.name.lower():
                continue
            for param in sorted(ncnn_dir.glob("*.param")):
                return param
        # Fallback: plain .param next to exports
        for param in sorted(exports.glob("*.param")):
            return param
        return None

    if rt == "rknn":
        for rknn in sorted(exports.glob("*.rknn")):
            if not rknn.name.startswith("._"):
                return rknn
        return None

    if rt == "hailo":
        for hef in sorted(exports.glob("*.hef")):
            return hef
        # The tarball may still be there; user must extract.
        return None

    if rt == "pytorch":
        for pt in sorted(exports.glob("*.pt")):
            return pt
        return None

    return None
