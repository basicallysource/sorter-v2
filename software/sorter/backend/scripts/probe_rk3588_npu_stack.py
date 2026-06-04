#!/usr/bin/env python3
"""Probe the RK3588 RKNN/NPU runtime.

This is an image acceptance probe, not a model-quality test. The strict mode
requires a real RKNNLite load + init_runtime + inference call so a booted image
cannot pass with only Python packages installed and no kernel NPU path.
"""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys
from pathlib import Path
from typing import Any, Callable


BACKEND_DIR = Path(__file__).resolve().parents[1]
SOFTWARE_DIR = BACKEND_DIR.parents[1]
DEFAULT_MODEL_PATH = (
    SOFTWARE_DIR
    / "training"
    / "rknn_bundles"
    / "c_channel_full_yolo26s_320_rk3588"
    / "results"
    / "c_channel_full_yolo26s_320_rk3588.rknn"
)
DEFAULT_DEVICE_NODES = (
    "/dev/rknpu",
    "/dev/dri/by-path/platform-fdab0000.npu-render",
)
DEFAULT_RUNTIME_MARKERS = (
    "/sys/kernel/debug/rknpu",
    "/sys/kernel/debug/rknpu/version",
    "/usr/lib/librknnrt.so",
    "/usr/lib/aarch64-linux-gnu/librknnrt.so",
)
DEFAULT_CORE_MASKS = ("NPU_CORE_0_1_2", "NPU_CORE_AUTO", "NPU_CORE_0")


def _parse_shape(raw: str) -> tuple[int, ...]:
    try:
        shape = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid shape {raw!r}") from exc
    if not shape or any(dim <= 0 for dim in shape):
        raise argparse.ArgumentTypeError(f"invalid shape {raw!r}")
    return shape


def _load_rknnlite() -> tuple[type[Any] | None, str | None]:
    try:
        module = importlib.import_module("rknnlite.api")
        runtime_cls = getattr(module, "RKNNLite")
    except Exception as exc:
        return None, str(exc)
    return runtime_cls, None


def _try_init_runtime(rknn: Any, mask_names: tuple[str, ...]) -> int:
    for name in mask_names:
        mask = getattr(rknn, name, None)
        if mask is None:
            continue
        try:
            ret = rknn.init_runtime(core_mask=mask)
        except Exception:
            continue
        if ret == 0:
            return 0
    return int(rknn.init_runtime())


def _shape_of(value: Any) -> list[int] | str:
    shape = getattr(value, "shape", None)
    if shape is None:
        return type(value).__name__
    try:
        return [int(dim) for dim in shape]
    except Exception:
        return str(shape)


def _run_inference(
    *,
    runtime_cls: type[Any],
    model_path: Path,
    input_shape: tuple[int, ...],
    input_dtype: str,
    core_masks: tuple[str, ...],
) -> dict[str, Any]:
    try:
        import numpy as np
    except Exception as exc:
        return {"ok": False, "error": f"numpy not importable: {exc}"}

    dtype_map = {
        "uint8": np.uint8,
        "float32": np.float32,
    }
    dtype = dtype_map.get(input_dtype)
    if dtype is None:
        return {"ok": False, "error": f"unsupported input dtype: {input_dtype}"}

    rknn = runtime_cls()
    try:
        if int(rknn.load_rknn(str(model_path))) != 0:
            return {"ok": False, "error": "RKNNLite.load_rknn failed"}
        if _try_init_runtime(rknn, core_masks) != 0:
            return {"ok": False, "error": "RKNNLite.init_runtime failed"}
        blob = np.zeros(input_shape, dtype=dtype)
        outputs = rknn.inference(inputs=[blob])
        output_count = len(outputs) if isinstance(outputs, list) else 0
        if output_count <= 0:
            return {"ok": False, "error": "RKNNLite.inference returned no outputs"}
        return {
            "ok": True,
            "output_count": output_count,
            "output_shapes": [_shape_of(item) for item in outputs],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            rknn.release()
        except Exception:
            pass


def build_report(
    args: argparse.Namespace,
    *,
    path_exists: Callable[[str], bool] | None = None,
    runtime_loader: Callable[[], tuple[type[Any] | None, str | None]] | None = None,
) -> dict[str, Any]:
    path_exists = path_exists or (lambda path: Path(path).exists())
    runtime_loader = runtime_loader or _load_rknnlite
    machine = platform.machine()
    model_path = Path(args.model)
    runtime_cls, import_error = runtime_loader()

    checks: dict[str, Any] = {
        "machine_aarch64": machine in {"aarch64", "arm64"},
        "rknpu_device_node": any(path_exists(node) for node in DEFAULT_DEVICE_NODES),
        "rknpu_runtime_marker": any(path_exists(path) for path in DEFAULT_RUNTIME_MARKERS),
        "rknnlite_importable": runtime_cls is not None,
        "model_present": path_exists(str(model_path)),
        "inference_ok": False,
    }
    details: dict[str, Any] = {
        "machine": machine,
        "device_nodes": {node: path_exists(node) for node in DEFAULT_DEVICE_NODES},
        "runtime_markers": {path: path_exists(path) for path in DEFAULT_RUNTIME_MARKERS},
        "model": str(model_path),
        "rknnlite_import_error": import_error,
    }

    inference_result = None
    if args.require_inference and runtime_cls is not None and checks["model_present"]:
        inference_result = _run_inference(
            runtime_cls=runtime_cls,
            model_path=model_path,
            input_shape=args.input_shape,
            input_dtype=args.input_dtype,
            core_masks=tuple(args.core_mask),
        )
        checks["inference_ok"] = bool(inference_result.get("ok"))
    details["inference"] = inference_result

    blockers: list[str] = []
    if args.require_machine and not checks["machine_aarch64"]:
        blockers.append(f"Machine must be aarch64/arm64 for RK3588 NPU, got {machine!r}.")
    if args.require_device and not checks["rknpu_device_node"]:
        blockers.append(
            "Missing RK3588 NPU device node: /dev/rknpu or "
            "/dev/dri/by-path/platform-fdab0000.npu-render."
        )
    if args.require_runtime and not checks["rknnlite_importable"]:
        blockers.append(f"rknn-toolkit-lite2 / rknnlite.api is not importable: {import_error}")
    if args.require_runtime and not (
        checks["rknpu_runtime_marker"] or checks["rknpu_device_node"]
    ):
        blockers.append("No RKNN runtime marker or NPU device node found.")
    if args.require_inference and not checks["model_present"]:
        blockers.append(f"RKNN smoke model is missing: {model_path}")
    if args.require_inference and not checks["inference_ok"]:
        error = ""
        if isinstance(inference_result, dict) and inference_result.get("error"):
            error = f" {inference_result['error']}"
        blockers.append("RKNNLite inference smoke test did not complete." + error)

    return {
        "ok": not blockers,
        "checks": checks,
        "details": details,
        "blockers": blockers,
        "requirements": {
            "machine": args.require_machine,
            "device": args.require_device,
            "runtime": args.require_runtime,
            "inference": args.require_inference,
        },
    }


def _print_text(report: dict[str, Any]) -> None:
    print("RK3588 NPU Stack Probe")
    for name, value in report["checks"].items():
        marker = "OK" if value else "--"
        print(f"  {marker} {name}")
    if report["blockers"]:
        print()
        print("Blockers")
        for blocker in report["blockers"]:
            print(f"  - {blocker}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--model", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--input-shape", type=_parse_shape, default=(1, 320, 320, 3))
    parser.add_argument("--input-dtype", choices=["uint8", "float32"], default="uint8")
    parser.add_argument("--core-mask", action="append", default=list(DEFAULT_CORE_MASKS))
    parser.add_argument("--require-machine", action="store_true", default=True)
    parser.add_argument("--require-device", action="store_true")
    parser.add_argument("--require-runtime", action="store_true")
    parser.add_argument("--require-inference", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.require_inference:
        args.require_device = True
        args.require_runtime = True
    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text(report)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
