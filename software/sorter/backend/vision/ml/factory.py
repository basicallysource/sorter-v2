"""Factory + metadata helpers shared by the registry and VisionManager.

The ``create_processor`` entry picks the right processor class based on the
``(runtime, model_family)`` tuple and resolves the on-disk location of the
model artifact inside a ``hive-<id>/`` directory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import BaseProcessor


log = logging.getLogger(__name__)


def _resolve_ncnn_use_vulkan() -> bool:
    """Consult ``blob/runtime_preferences.json`` for the NCNN option choice.

    Returns ``True`` iff the user selected ``ncnn-vulkan``. Any other value
    (including ``ncnn-cpu``, a missing file, or a malformed entry) resolves
    to ``False`` so the live inference path stays on the safe CPU default.
    The processor itself double-checks ``ncnn.get_gpu_count()`` before
    enabling Vulkan and logs a warning if the GPU is missing.
    """
    try:
        from runtime_preferences import preferred_option
    except Exception as exc:  # pragma: no cover - defensive import
        log.warning("runtime_preferences import failed (%s) — defaulting NCNN to CPU", exc)
        return False
    option = preferred_option("ncnn", default="ncnn-cpu")
    return option == "ncnn-vulkan"


def create_processor(
    *,
    model_path: Path,
    model_family: str,
    runtime: str,
    imgsz: int,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
) -> BaseProcessor:
    family = (model_family or "").lower()
    runtime = (runtime or "onnx").lower()

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

        use_vulkan = _resolve_ncnn_use_vulkan()
        if family == "yolo":
            return NcnnYoloProcessor(
                model_path,
                imgsz=imgsz,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
                use_vulkan=use_vulkan,
            )
        if family == "nanodet":
            return NcnnNanodetProcessor(
                model_path,
                imgsz=imgsz,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
                use_vulkan=use_vulkan,
            )

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
      onnx   → ``exports/best.onnx`` or first ``exports/*.onnx``
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
        for candidate in sorted(exports.glob("*.onnx")):
            return candidate
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
