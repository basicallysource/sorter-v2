"""Quick onnxruntime latency benchmark for the v6 c_channel yolo26s-320 model.

Mirrors the format of runs/benchmark_c_all_combined_20260514.json so the result
can be appended into the model catalog entry.

Run:
    uv run python scripts/benchmark_v6_local.py
"""
from __future__ import annotations

import json
import platform
import statistics as stats
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

RUN_DIR = Path(__file__).resolve().parents[1] / "runs" / "20260517-092535-c_channel_full-yolo-v6_maxout_score095"
ONNX_PATH = RUN_DIR / "exports" / "best.onnx"
OUT_PATH = Path(__file__).resolve().parents[1] / "reports_out" / "device_benchmarks" / "local_v6_yolo26s_20260517.json"

ITERS = 30
WARMUP = 5
SLUG = "c-channel-combined-yolo26s-320"


def bench(provider: str, input_shape: tuple[int, int, int, int]) -> dict:
    session = ort.InferenceSession(str(ONNX_PATH), providers=[provider])
    inp_name = session.get_inputs()[0].name
    x = np.random.rand(*input_shape).astype("float32")
    for _ in range(WARMUP):
        session.run(None, {inp_name: x})
    samples_ms: list[float] = []
    for _ in range(ITERS):
        t0 = time.perf_counter()
        session.run(None, {inp_name: x})
        samples_ms.append((time.perf_counter() - t0) * 1000.0)
    return {
        "provider": provider,
        "input_shape": list(input_shape),
        "iterations": ITERS,
        "mean_ms": round(stats.mean(samples_ms), 4),
        "median_ms": round(stats.median(samples_ms), 4),
        "min_ms": round(min(samples_ms), 4),
        "max_ms": round(max(samples_ms), 4),
        "p95_ms": round(sorted(samples_ms)[int(len(samples_ms) * 0.95)], 4),
        "stddev_ms": round(stats.pstdev(samples_ms), 4),
        "fps_mean": round(1000.0 / stats.mean(samples_ms), 1),
    }


def main() -> None:
    if not ONNX_PATH.exists():
        raise SystemExit(f"missing onnx: {ONNX_PATH}")

    input_shape = (1, 3, 320, 320)
    onnx_size = ONNX_PATH.stat().st_size
    pt_size = (RUN_DIR / "exports" / "best.pt").stat().st_size
    ncnn_dir = RUN_DIR / "exports" / "best_ncnn_model"
    ncnn_size = sum(p.stat().st_size for p in ncnn_dir.glob("*") if p.is_file())

    cpu = bench("CPUExecutionProvider", input_shape)
    try:
        coreml = bench("CoreMLExecutionProvider", input_shape)
    except Exception as exc:
        coreml = {"provider": "CoreMLExecutionProvider", "error": str(exc)}

    train_results = json.loads((RUN_DIR / "track_a_results.json").read_text())["A7"]

    payload = [{
        "slug": SLUG,
        "host": f"{platform.system().lower()}/{platform.machine()} (local laptop)",
        "benchmarked_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "version": 1,
        "onnx_size_bytes": onnx_size,
        "variant_sizes_bytes": {
            "onnx": onnx_size,
            "ncnn": ncnn_size,
            "pytorch": pt_size,
        },
        "training_best": train_results["best_metrics"],
        "CPUExecutionProvider": cpu,
        "CoreMLExecutionProvider": coreml,
    }]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT_PATH}")
    print(f"  CPU    mean={cpu['mean_ms']}ms p95={cpu['p95_ms']}ms fps={cpu['fps_mean']}")
    print(f"  CoreML mean={coreml.get('mean_ms','-')}ms p95={coreml.get('p95_ms','-')}ms fps={coreml.get('fps_mean','-')}")


if __name__ == "__main__":
    main()
