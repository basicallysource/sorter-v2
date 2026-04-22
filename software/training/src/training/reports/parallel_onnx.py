from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure sustained parallel ONNX CPU throughput.")
    parser.add_argument("--bundle", type=Path, required=True, help="Benchmark bundle directory.")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON path.")
    parser.add_argument("--duration", type=float, default=5.0, help="Sustained test duration per scenario.")
    parser.add_argument(
        "--workers",
        type=int,
        nargs="+",
        default=[1, 2, 3],
        help="Worker counts to test.",
    )
    parser.add_argument("--device", type=str, default=os.uname().nodename, help="Device label.")
    return parser.parse_args()


def _load_manifest(bundle_dir: Path) -> dict[str, Any]:
    return json.loads((bundle_dir / "manifest.json").read_text())


def _first_image(bundle_dir: Path) -> np.ndarray:
    for image_path in sorted((bundle_dir / "images").glob("*.jpg")):
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is not None:
            return image
    raise FileNotFoundError(f"No readable JPG images found under {bundle_dir / 'images'}")


def _make_blob(image: np.ndarray, size: int) -> np.ndarray:
    resized = cv2.resize(image, (size, size), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return np.transpose(rgb, (2, 0, 1))[np.newaxis, ...]


def _make_runner(model_path: Path, blob: np.ndarray, intra_threads: int) -> callable:
    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, intra_threads)
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name

    def run() -> None:
        session.run(None, {input_name: blob})

    return run


def _sustained_worker(run_fn: callable, duration_sec: float, result_list: list[dict[str, Any]], worker_name: str) -> None:
    for _ in range(3):
        run_fn()
    times: list[float] = []
    deadline = time.perf_counter() + duration_sec
    while time.perf_counter() < deadline:
        t0 = time.perf_counter()
        run_fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    if not times:
        result_list.append({"worker": worker_name, "count": 0, "avg_latency_ms": None, "fps": 0.0})
        return
    avg_latency_ms = float(np.mean(times))
    result_list.append(
        {
            "worker": worker_name,
            "count": len(times),
            "avg_latency_ms": avg_latency_ms,
            "fps": len(times) / duration_sec,
        }
    )


def _run_parallel(model_path: Path, blob: np.ndarray, duration_sec: float, workers: int) -> dict[str, Any]:
    cpu_count = os.cpu_count() or 1
    threads_per_worker = max(1, cpu_count // workers)
    runners = [
        (_make_runner(model_path, blob, threads_per_worker), f"{workers}-{index + 1}")
        for index in range(workers)
    ]

    results: list[dict[str, Any]] = []
    threads: list[threading.Thread] = []
    wall_start = time.perf_counter()
    for run_fn, worker_name in runners:
        thread = threading.Thread(
            target=_sustained_worker,
            args=(run_fn, duration_sec, results, worker_name),
            daemon=True,
        )
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    wall_duration = time.perf_counter() - wall_start

    combined_count = sum(int(item["count"]) for item in results)
    latency_values = [float(item["avg_latency_ms"]) for item in results if item["avg_latency_ms"] is not None]
    fps_values = [float(item["fps"]) for item in results]
    return {
        "workers": workers,
        "duration_sec": duration_sec,
        "cpu_count": cpu_count,
        "threads_per_worker": threads_per_worker,
        "successful_workers": len(results),
        "combined_fps": combined_count / wall_duration if wall_duration > 0 else 0.0,
        "mean_worker_fps": float(np.mean(fps_values)) if fps_values else 0.0,
        "mean_worker_latency_ms": float(np.mean(latency_values)) if latency_values else None,
        "workers_detail": sorted(results, key=lambda item: str(item["worker"])),
    }


def main() -> int:
    args = _parse_args()
    bundle_dir = args.bundle.resolve()
    manifest = _load_manifest(bundle_dir)
    image = _first_image(bundle_dir)

    entries: list[dict[str, Any]] = []
    for model in manifest.get("models", []):
        model_id = str(model["id"])
        label = str(model.get("label", model_id))
        family = str(model.get("family", "unknown"))
        size = int(model["imgsz"])
        model_path = bundle_dir / str(model["onnx_rel"])
        blob = _make_blob(image, size)
        for workers in args.workers:
            entry = _run_parallel(model_path, blob, args.duration, workers)
            entry["model"] = family
            entry["model_id"] = model_id
            entry["model_label"] = label
            entries.append(entry)

    payload = {
        "device": args.device,
        "runtime": "onnx-cpu",
        "entries": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
