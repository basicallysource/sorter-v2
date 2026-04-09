from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np


def _build_input(size: int) -> np.ndarray:
    return np.zeros((size, size, 3), dtype=np.uint8)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a short shared-service Hailo benchmark worker.")
    parser.add_argument("--hef", required=True, help="Path to the HEF file.")
    parser.add_argument("--size", type=int, required=True, help="Square input size in pixels.")
    parser.add_argument("--duration", type=float, default=5.0, help="Measured duration in seconds.")
    parser.add_argument("--warmup", type=int, default=3, help="Warmup iterations.")
    parser.add_argument("--timeout-ms", type=int, default=10_000, help="Inference timeout in milliseconds.")
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()

    from hailo_platform import FormatType, HailoSchedulingAlgorithm, VDevice

    params = VDevice.create_params()
    params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
    params.multi_process_service = True
    params.group_id = "SHARED"

    vdevice = VDevice(params)
    infer_model = vdevice.create_infer_model(str(Path(args.hef).resolve()))
    infer_model.input().set_format_type(FormatType.UINT8)
    for output_name in infer_model.output_names:
        infer_model.output(output_name).set_format_type(FormatType.FLOAT32)
    configured = infer_model.configure()
    bindings = configured.create_bindings()

    bindings.input(infer_model.input_names[0]).set_buffer(_build_input(args.size))
    for output_name in infer_model.output_names:
        shape = tuple(int(value) for value in infer_model.output(output_name).shape)
        bindings.output(output_name).set_buffer(np.empty(shape, dtype=np.float32))

    for _ in range(max(0, args.warmup)):
        configured.run([bindings], args.timeout_ms)

    latencies_ms: list[float] = []
    deadline = time.perf_counter() + max(0.1, float(args.duration))
    while time.perf_counter() < deadline:
        t0 = time.perf_counter()
        configured.run([bindings], args.timeout_ms)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    actual_duration = max(0.001, float(args.duration))
    payload = {
        "hef": str(Path(args.hef).resolve()),
        "count": len(latencies_ms),
        "duration_sec": float(args.duration),
        "avg_latency_ms": (sum(latencies_ms) / len(latencies_ms)) if latencies_ms else None,
        "fps": len(latencies_ms) / actual_duration,
    }

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2))

    print(json.dumps(payload), flush=True)

    # Shared-service teardown on the Pi's current HailoRT stack can crash at interpreter shutdown.
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
