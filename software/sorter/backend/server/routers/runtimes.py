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
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/runtimes", tags=["runtimes"])


# ---------------------------------------------------------------------------
# Runtime preferences — which option_id is the chosen inference backend for
# each model format on this machine. Persisted to a JSON file so the choice
# survives restarts.
# ---------------------------------------------------------------------------


_PREFS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "blob" / "runtime_preferences.json"
)
_PREFS_LOCK = threading.Lock()


def _load_prefs() -> dict[str, str]:
    try:
        raw = json.loads(_PREFS_PATH.read_text())
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


def _save_prefs(prefs: dict[str, str]) -> None:
    _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=_PREFS_PATH.parent, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, _PREFS_PATH)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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


def _probe_rknn() -> dict:
    """Detect rknn-toolkit-lite2 + RK3588-class NPU.

    Two distinct checks: the Python bindings (``from rknnlite.api import RKNNLite``)
    must be importable, AND ``/sys/kernel/debug/rknpu/version`` (or fall back to
    ``/usr/lib/librknnrt.so`` existence) must indicate a real NPU. We don't
    actually instantiate ``RKNNLite()`` here — that pulls the runtime into the
    process even on a smoke probe — but we surface the librknnrt version when
    available because the driver/runtime/toolkit triple must match.
    """
    try:
        import rknnlite.api  # type: ignore  # noqa: F401
    except Exception as exc:
        return {"available": False, "reason": f"rknn-toolkit-lite2 not installed: {exc}"}

    npu_present = False
    driver_version: str | None = None
    runtime_version: str | None = None
    try:
        ver_path = Path("/sys/kernel/debug/rknpu/version")
        if ver_path.exists():
            txt = ver_path.read_text(errors="replace").strip()
            driver_version = txt or None
            npu_present = True
    except Exception:
        pass
    if not npu_present and Path("/usr/lib/librknnrt.so").exists():
        npu_present = True
    if Path("/usr/lib/librknnrt.so").exists():
        try:
            # librknnrt embeds a version string; surface it for the UI.
            import subprocess

            out = subprocess.run(
                ["strings", "/usr/lib/librknnrt.so"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            for line in out.stdout.splitlines():
                if "librknnrt version" in line:
                    runtime_version = line.strip()
                    break
        except Exception:
            pass

    # RK3588 has 3 cores. We don't probe live; just hard-report the topology.
    cores = 3 if npu_present else 0
    return {
        "available": npu_present,
        "reason": None if npu_present else "no /sys/kernel/debug/rknpu/version or librknnrt.so",
        "npu_cores": cores,
        "driver_version": driver_version,
        "runtime_version": runtime_version,
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
        "rknn": _probe_rknn(),
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


def _format_rknn(caps: dict) -> dict:
    rknn = caps.get("rknn") or {}
    has_rknn = bool(rknn.get("available"))
    cores = int(rknn.get("npu_cores", 0) or 0)
    runtime_version = rknn.get("runtime_version") or ""
    options = [
        {
            "id": "rknn-npu-auto",
            "label": "NPU (auto core)",
            "available": has_rknn,
            "reason": None if has_rknn else rknn.get("reason") or "no NPU detected",
            "rank": 1,
            "detail": f"{cores} core(s); {runtime_version}" if has_rknn else "",
        },
    ]
    # Per-core options are useful for multi-stream pinning (one camera per core).
    for core_index in range(cores):
        options.append(
            {
                "id": f"rknn-npu-core{core_index}",
                "label": f"NPU core {core_index}",
                "available": has_rknn,
                "reason": None,
                "rank": 1,
                "detail": "pinned",
            }
        )
    return {
        "id": "rknn",
        "label": "Rockchip RKNN",
        "extensions": [".rknn"],
        "description": "RK3588 NPU. INT8-native, 3 independent cores for free multi-stream parallelism.",
        "options": options,
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


def _bench_rknn(model_dir: Path, core_mask_name: str, warmup: int, iterations: int) -> dict:
    rknn_path = _pick_first(["*.rknn"], model_dir)
    if rknn_path is None:
        raise HTTPException(status_code=400, detail="No .rknn file in model directory")
    try:
        from rknnlite.api import RKNNLite  # type: ignore
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"rknn-toolkit-lite2 unavailable: {exc}")

    masks = {
        "auto": getattr(RKNNLite, "NPU_CORE_AUTO", 0),
        "core0": getattr(RKNNLite, "NPU_CORE_0", 1),
        "core1": getattr(RKNNLite, "NPU_CORE_1", 2),
        "core2": getattr(RKNNLite, "NPU_CORE_2", 4),
        "all": getattr(RKNNLite, "NPU_CORE_0_1_2", 7),
    }
    mask = masks.get(core_mask_name, masks["auto"])

    rknn = RKNNLite()
    try:
        if rknn.load_rknn(str(rknn_path)) != 0:
            raise HTTPException(status_code=500, detail="load_rknn failed")
        if rknn.init_runtime(core_mask=mask) != 0:
            # Fall through to default (no core pinning) — older lite builds
            # vary in which mask constants they accept.
            if rknn.init_runtime() != 0:
                raise HTTPException(status_code=500, detail="init_runtime failed")
        # Probe input shape from the model — RKNN INT8 wants HWC uint8.
        # We can't easily introspect post-quantization shape, so default to
        # 320x320 (matches our bundled YOLO export).
        size = 320
        # RKNN graph expects NHWC — wrap in a batch axis or rknn-toolkit-lite2
        # raises "The input[0] need 4dims input, but 3dims input buffer feed."
        dummy = np.random.randint(0, 255, (1, size, size, 3), dtype=np.uint8)

        def fn():
            outs = rknn.inference(inputs=[dummy])
            if outs is None:
                raise HTTPException(status_code=500, detail="inference returned None")

        return _time_loop(fn, warmup=warmup, iterations=iterations)
    finally:
        try:
            rknn.release()
        except Exception:
            pass


_OPTION_DISPATCH: dict[str, dict] = {
    "onnx-cpu": {"backend": "onnx", "providers": ["CPUExecutionProvider"]},
    "onnx-coreml": {"backend": "onnx", "providers": ["CoreMLExecutionProvider", "CPUExecutionProvider"]},
    "onnx-cuda": {"backend": "onnx", "providers": ["CUDAExecutionProvider", "CPUExecutionProvider"]},
    "onnx-dml": {"backend": "onnx", "providers": ["DmlExecutionProvider", "CPUExecutionProvider"]},
    "ncnn-cpu": {"backend": "ncnn", "use_vulkan": False},
    "ncnn-vulkan": {"backend": "ncnn", "use_vulkan": True},
    "rknn-npu-auto": {"backend": "rknn", "core_mask_name": "auto"},
    "rknn-npu-core0": {"backend": "rknn", "core_mask_name": "core0"},
    "rknn-npu-core1": {"backend": "rknn", "core_mask_name": "core1"},
    "rknn-npu-core2": {"backend": "rknn", "core_mask_name": "core2"},
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
        elif spec["backend"] == "rknn":
            result = _bench_rknn(
                model_dir,
                core_mask_name=spec["core_mask_name"],
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
        _format_rknn(caps),
        _format_onnx(caps),
        _format_ncnn(caps),
    ]
    # Sort options inside each format by rank (best first), then by label.
    for fmt in formats:
        fmt["options"].sort(key=lambda o: (o.get("rank", 99), o.get("label", "")))
    return {"formats": formats}
