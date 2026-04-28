"""Hardware-acceleration capability discovery for the Hive model pipeline.

Answers the ``which inference backends can this machine run?`` question so
the UI can surface it in Settings → Hive. Kept lightweight — each probe
catches its own import error and reports ``{available: False, reason:
"..."}`` so the endpoint never 500s just because one backend is missing.

Phase 1: detection only. Phase 2 will add ``/benchmark`` for per-model
timing; Phase 3 will persist per-model default runtime preference.
"""

from __future__ import annotations

import functools
import json
import os
import platform
import statistics
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from runtime_preferences import PREFS_PATH as _PREFS_PATH, read_runtime_preferences


router = APIRouter(prefix="/api/runtimes", tags=["runtimes"])


# ---------------------------------------------------------------------------
# Runtime preferences — which option_id is the chosen inference backend for
# each model format on this machine. Persisted to a JSON file so the choice
# survives restarts. The shared reader lives in ``runtime_preferences`` at the
# backend root so the production ML factory can import it too.
# ---------------------------------------------------------------------------


_PREFS_LOCK = threading.Lock()


def _load_prefs() -> dict[str, str]:
    return read_runtime_preferences()


def _save_prefs(prefs: dict[str, str]) -> None:
    _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PREFS_PATH.write_text(json.dumps(prefs, indent=2, sort_keys=True))


def _probe_cpu() -> dict:
    return {
        "available": True,
        "cores": os.cpu_count() or 0,
        "machine": platform.machine(),
        "system": platform.system(),
    }


def _probe_onnxruntime() -> dict:
    try:
        import onnxruntime as ort  # type: ignore
    except Exception as exc:
        return {"available": False, "reason": f"onnxruntime not installed: {exc}"}
    providers = list(ort.get_available_providers())
    return {
        "available": True,
        "version": getattr(ort, "__version__", "?"),
        "providers": providers,
    }


def _probe_coreml() -> dict:
    ort_info = _probe_onnxruntime()
    if not ort_info.get("available"):
        return {"available": False, "reason": "onnxruntime missing"}
    provs = ort_info.get("providers", [])
    has_coreml = "CoreMLExecutionProvider" in provs
    return {
        "available": has_coreml,
        "reason": None if has_coreml else "CoreMLExecutionProvider not in onnxruntime build",
    }


def _probe_cuda() -> dict:
    ort_info = _probe_onnxruntime()
    if not ort_info.get("available"):
        return {"available": False, "reason": "onnxruntime missing"}
    provs = ort_info.get("providers", [])
    has_cuda = "CUDAExecutionProvider" in provs
    return {
        "available": has_cuda,
        "reason": None if has_cuda else "CUDAExecutionProvider not in onnxruntime build",
    }


def _probe_ncnn() -> dict:
    try:
        import ncnn  # type: ignore
    except Exception as exc:
        return {"available": False, "reason": f"ncnn not installed: {exc}"}
    gpu_count = 0
    try:
        gpu_count = int(ncnn.get_gpu_count())
    except Exception:
        gpu_count = 0
    return {
        "available": True,
        "vulkan_devices": gpu_count,
    }


def _probe_hailo() -> dict:
    try:
        import hailo_platform as hp  # type: ignore
    except Exception as exc:
        return {"available": False, "reason": f"hailo_platform not installed: {exc}"}
    try:
        device_ids = list(hp.Device.scan())
    except Exception as exc:
        return {"available": False, "reason": f"hailo scan failed: {exc}"}
    return {
        "available": len(device_ids) > 0,
        "device_count": len(device_ids),
        "device_ids": [str(d) for d in device_ids],
    }


def _probe_torch() -> dict:
    try:
        import torch  # type: ignore
    except Exception as exc:
        return {"available": False, "reason": f"torch not installed: {exc}"}
    info: dict[str, Any] = {
        "available": True,
        "version": getattr(torch, "__version__", "?"),
        "mps": False,
        "cuda": False,
    }
    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            info["mps"] = True
    except Exception:
        pass
    try:
        if torch.cuda.is_available():
            info["cuda"] = True
            info["cuda_devices"] = torch.cuda.device_count()
    except Exception:
        pass
    return info


@functools.lru_cache(maxsize=1)
def _cached_capabilities() -> dict:
    return {
        "cpu": _probe_cpu(),
        "onnxruntime": _probe_onnxruntime(),
        "coreml": _probe_coreml(),
        "cuda": _probe_cuda(),
        "ncnn": _probe_ncnn(),
        "hailo": _probe_hailo(),
        "torch": _probe_torch(),
    }


class PreferencePayload(BaseModel):
    format_id: str
    option_id: str


@router.get("/preferences")
def get_preferences() -> dict:
    """Return the currently-preferred option per format as ``{format_id: option_id}``."""
    with _PREFS_LOCK:
        return {"preferences": _load_prefs()}


@router.put("/preferences")
def put_preference(body: PreferencePayload) -> dict:
    """Set the preferred backend option for a given format.

    The selection sticks until overwritten; other parts of the codebase
    read this via ``_load_prefs()`` to pick the runtime when loading a
    model.
    """
    with _PREFS_LOCK:
        prefs = _load_prefs()
        prefs[body.format_id] = body.option_id
        _save_prefs(prefs)
        return {"preferences": prefs}


@router.get("/capabilities")
def get_capabilities() -> dict:
    """Report which inference backends are usable on this machine.

    Results are cached per process since installed libraries don't change
    at runtime. Refresh only happens on backend restart.
    """
    return _cached_capabilities()


# ---------------------------------------------------------------------------
# Model-format view — groups runtimes by the model artifact they consume so
# the UI can say "if you have an ONNX export, here's how it can run on this
# machine" rather than a flat hardware list.
# ---------------------------------------------------------------------------


# Rank legend (lower is faster, used to sort options within a format):
#   1 = dedicated accelerator / native HW path
#   2 = GPU acceleration
#   3 = mobile/integrated GPU
#   4 = CPU with optimized runtime
#   5 = CPU plain


def _format_onnx(caps: dict) -> dict:
    onnx = caps.get("onnxruntime") or {}
    has_ort = bool(onnx.get("available"))
    provs = set(onnx.get("providers", []) or [])
    version = onnx.get("version", "?")
    return {
        "id": "onnx",
        "label": "ONNX",
        "extensions": [".onnx"],
        "description": "Open format. Runs on the most hardware of any export we ship.",
        "options": [
            {
                "id": "onnx-cuda",
                "label": "CUDA",
                "available": has_ort and "CUDAExecutionProvider" in provs,
                "reason": None if "CUDAExecutionProvider" in provs else "CUDAExecutionProvider not in onnxruntime build",
                "rank": 1,
                "detail": "Nvidia GPU via onnxruntime",
            },
            {
                "id": "onnx-coreml",
                "label": "CoreML / ANE",
                "available": has_ort and "CoreMLExecutionProvider" in provs,
                "reason": None if "CoreMLExecutionProvider" in provs else "CoreMLExecutionProvider not in onnxruntime build",
                "rank": 1,
                "detail": "Apple Neural Engine + GPU",
            },
            {
                "id": "onnx-dml",
                "label": "DirectML",
                "available": has_ort and "DmlExecutionProvider" in provs,
                "reason": None if "DmlExecutionProvider" in provs else "DmlExecutionProvider not in onnxruntime build",
                "rank": 2,
                "detail": "Windows GPU acceleration",
            },
            {
                "id": "onnx-cpu",
                "label": "CPU",
                "available": has_ort,
                "reason": None if has_ort else onnx.get("reason") or "onnxruntime missing",
                "rank": 4,
                "detail": f"onnxruntime {version}" if has_ort else "",
            },
        ],
    }


def _format_ncnn(caps: dict) -> dict:
    ncnn = caps.get("ncnn") or {}
    has_ncnn = bool(ncnn.get("available"))
    vulkan_count = int(ncnn.get("vulkan_devices", 0) or 0)
    return {
        "id": "ncnn",
        "label": "NCNN",
        "extensions": [".param", ".bin"],
        "description": "Mobile-first inference. Small memory footprint; great on ARM.",
        "options": [
            {
                "id": "ncnn-vulkan",
                "label": "Vulkan GPU",
                "available": has_ncnn and vulkan_count > 0,
                "reason": None if (has_ncnn and vulkan_count > 0) else (
                    "no Vulkan device detected" if has_ncnn else "ncnn not installed"
                ),
                "rank": 2,
                "detail": f"{vulkan_count} device(s)" if vulkan_count else "",
            },
            {
                "id": "ncnn-cpu",
                "label": "CPU",
                "available": has_ncnn,
                "reason": None if has_ncnn else ncnn.get("reason") or "ncnn not installed",
                "rank": 4,
                "detail": "optimized ARM/x86 kernels" if has_ncnn else "",
            },
        ],
    }


def _format_hailo(caps: dict) -> dict:
    hailo = caps.get("hailo") or {}
    has_hailo = bool(hailo.get("available"))
    devices = int(hailo.get("device_count", 0) or 0)
    return {
        "id": "hailo",
        "label": "Hailo HEF",
        "extensions": [".hef"],
        "description": "Dedicated edge accelerator — fastest path when a Hailo module is attached.",
        "options": [
            {
                "id": "hailo-device",
                "label": "Hailo accelerator",
                "available": has_hailo and devices > 0,
                "reason": None if (has_hailo and devices > 0) else hailo.get("reason") or "no Hailo device",
                "rank": 1,
                "detail": f"{devices} device(s)" if devices else "",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Benchmark runner — Phase 2
# ---------------------------------------------------------------------------


class BenchmarkRequest(BaseModel):
    local_id: str
    option_id: str
    threads: int = 1
    iterations: int = 40
    warmup: int = 5


def _find_model_dir(local_id: str) -> Path:
    from server import hive_models as hive_models_service

    for item in hive_models_service.list_installed_models():
        if item.get("local_id") == local_id:
            path = item.get("path")
            if path:
                return Path(path)
    raise HTTPException(status_code=404, detail=f"Installed model not found: {local_id}")


def _pick_first(patterns: list[str], directory: Path) -> Path | None:
    for pattern in patterns:
        matches = sorted(directory.rglob(pattern))
        if matches:
            return matches[0]
    return None


def _time_loop(fn, warmup: int, iterations: int) -> dict:
    # Warmup — not timed.
    for _ in range(max(0, warmup)):
        fn()
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples_sorted = sorted(samples)
    mean_ms = statistics.fmean(samples)
    p50_ms = samples_sorted[len(samples_sorted) // 2]
    p90_idx = max(0, int(round(len(samples_sorted) * 0.9)) - 1)
    p90_ms = samples_sorted[p90_idx]
    fps = 1000.0 / mean_ms if mean_ms > 0 else 0.0
    return {
        "iterations": iterations,
        "mean_ms": round(mean_ms, 3),
        "p50_ms": round(p50_ms, 3),
        "p90_ms": round(p90_ms, 3),
        "fps": round(fps, 1),
    }


def _bench_onnx(model_dir: Path, providers: list[str], threads: int, warmup: int, iterations: int) -> dict:
    onnx_path = _pick_first(["*.onnx"], model_dir)
    if onnx_path is None:
        raise HTTPException(status_code=400, detail="No .onnx file in model directory")
    try:
        import onnxruntime as ort  # type: ignore
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"onnxruntime unavailable: {exc}")
    opts = ort.SessionOptions()
    if threads > 0:
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
    try:
        sess = ort.InferenceSession(str(onnx_path), sess_options=opts, providers=providers)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load ONNX: {exc}")
    inputs = sess.get_inputs()
    if not inputs:
        raise HTTPException(status_code=500, detail="ONNX model has no inputs")
    meta = inputs[0]
    shape = [d if isinstance(d, int) and d > 0 else 1 for d in meta.shape]
    # Infer HxW: default to 640 for unknown dims.
    shape = [d if d != 1 or i < 2 else 640 for i, d in enumerate(shape)]
    if len(shape) == 4 and shape[0] < 1:
        shape[0] = 1
    dtype_map = {
        "tensor(float)": np.float32,
        "tensor(float16)": np.float16,
        "tensor(uint8)": np.uint8,
    }
    np_dtype = dtype_map.get(meta.type, np.float32)
    dummy = np.random.rand(*shape).astype(np_dtype) if np_dtype != np.uint8 else np.random.randint(
        0, 255, size=shape, dtype=np.uint8
    )
    feed = {meta.name: dummy}
    output_names = [o.name for o in sess.get_outputs()]

    def fn():
        sess.run(output_names, feed)

    return _time_loop(fn, warmup=warmup, iterations=iterations)


def _bench_ncnn(model_dir: Path, use_vulkan: bool, threads: int, warmup: int, iterations: int) -> dict:
    param_path = _pick_first(["*.param"], model_dir)
    bin_path = _pick_first(["*.bin"], model_dir)
    if param_path is None or bin_path is None:
        raise HTTPException(status_code=400, detail="No NCNN .param / .bin pair found")
    try:
        import ncnn  # type: ignore
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ncnn unavailable: {exc}")
    net = ncnn.Net()
    try:
        net.opt.num_threads = max(1, int(threads))
        if use_vulkan:
            if ncnn.get_gpu_count() <= 0:
                raise HTTPException(status_code=400, detail="No Vulkan device available")
            net.opt.use_vulkan_compute = True
        else:
            net.opt.use_vulkan_compute = False
        if net.load_param(str(param_path)) != 0:
            raise HTTPException(status_code=500, detail="load_param failed")
        if net.load_model(str(bin_path)) != 0:
            raise HTTPException(status_code=500, detail="load_model failed")
        # Infer input blob name; default to "in0" / first registered input.
        input_names = net.input_names() if hasattr(net, "input_names") else ["in0"]
        output_names = net.output_names() if hasattr(net, "output_names") else ["out0"]
        # Default input size 640x640 RGB.
        size = 640
        dummy = np.random.randint(0, 255, (size, size, 3), dtype=np.uint8)
        mat_in = ncnn.Mat.from_pixels(dummy, ncnn.Mat.PixelType.PIXEL_RGB, size, size)

        def fn():
            ex = net.create_extractor()
            ex.input(input_names[0], mat_in)
            ret, _ = ex.extract(output_names[0])
            if ret != 0:
                raise HTTPException(status_code=500, detail=f"extract returned {ret}")

        return _time_loop(fn, warmup=warmup, iterations=iterations)
    finally:
        try:
            net.clear()
        except Exception:
            pass


_OPTION_DISPATCH: dict[str, dict] = {
    "onnx-cpu": {"backend": "onnx", "providers": ["CPUExecutionProvider"]},
    "onnx-coreml": {"backend": "onnx", "providers": ["CoreMLExecutionProvider", "CPUExecutionProvider"]},
    "onnx-cuda": {"backend": "onnx", "providers": ["CUDAExecutionProvider", "CPUExecutionProvider"]},
    "onnx-dml": {"backend": "onnx", "providers": ["DmlExecutionProvider", "CPUExecutionProvider"]},
    "ncnn-cpu": {"backend": "ncnn", "use_vulkan": False},
    "ncnn-vulkan": {"backend": "ncnn", "use_vulkan": True},
}


@router.post("/benchmark")
def run_benchmark(req: BenchmarkRequest) -> dict:
    """Run ``req.iterations`` forward passes of the chosen model+runtime.

    Synchronous — meant to be called sequentially from the UI, one option
    at a time, so results aren't skewed by concurrent load. ``threads``
    only meaningfully differs for NCNN/ONNX-CPU; other paths ignore it.
    """
    spec = _OPTION_DISPATCH.get(req.option_id)
    if spec is None:
        raise HTTPException(
            status_code=400,
            detail=f"Option not supported for benchmarking: {req.option_id}",
        )
    model_dir = _find_model_dir(req.local_id)
    iterations = max(1, min(500, int(req.iterations)))
    warmup = max(0, min(20, int(req.warmup)))
    threads = max(1, min(32, int(req.threads)))

    try:
        if spec["backend"] == "onnx":
            result = _bench_onnx(
                model_dir,
                providers=spec["providers"],
                threads=threads,
                warmup=warmup,
                iterations=iterations,
            )
        elif spec["backend"] == "ncnn":
            result = _bench_ncnn(
                model_dir,
                use_vulkan=spec["use_vulkan"],
                threads=threads,
                warmup=warmup,
                iterations=iterations,
            )
        else:  # pragma: no cover
            raise HTTPException(status_code=400, detail="Unsupported backend")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Benchmark failed: {exc}")

    return {
        "option_id": req.option_id,
        "local_id": req.local_id,
        "threads": threads,
        **result,
    }


@router.get("/formats")
def get_formats() -> dict:
    """Structured view grouped by model artifact format.

    For each shipping format (ONNX, NCNN, Hailo HEF, PyTorch) we list the
    execution options the host can physically perform, whether they're
    actually usable right now, and a rough speed rank so the UI can
    recommend the fastest viable option per model.
    """
    caps = _cached_capabilities()
    # PyTorch is intentionally excluded from the deployable-format list —
    # we never ship .pt to the sorter, only ONNX/NCNN/HEF exports. The
    # torch probe stays in ``/capabilities`` so other code paths (BoxMOT
    # ReID etc.) can still see it.
    formats = [
        _format_hailo(caps),
        _format_onnx(caps),
        _format_ncnn(caps),
    ]
    # Sort options inside each format by rank (best first), then by label.
    for fmt in formats:
        fmt["options"].sort(key=lambda o: (o.get("rank", 99), o.get("label", "")))
    return {"formats": formats}
