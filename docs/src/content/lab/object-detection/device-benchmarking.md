---
layout: default
title: Benchmark a new device
type: how-to
section: lab
slug: device-benchmarking
kicker: Object Detection Research
lede: How to run the same detector benchmark on a new device and compare its results against the existing runs.
permalink: /lab/object-detection/device-benchmarking/
---

## Why a bundle, not loose files

Every benchmark run on every device consumes the **same portable bundle** — one directory holding a fixed 50-image sample set, the canonical model artifacts in each format, and the metadata describing how it was built. That is what makes cross-device numbers comparable in the first place. No ad hoc local copies, no "but it was a different image on that device".

The tooling lives in one script: `software/sorter/backend/scripts/device_detector_benchmark.py`. It exposes `bundle`, `run`, `compare`, and `report`.

## 1. Build the bundle (once, on the dev machine)

From `software/client`:

```bash
uv run python scripts/device_detector_benchmark.py bundle \
  --preset chamber_zone_pair \
  --output blob/device_benchmarks/chamber_zone_pair_bundle \
  --archive
```

`chamber_zone_pair` is the current standard preset — it packages the chamber-zone `YOLO11s` and `NanoDet` pair with the shared 50-image sample set. Use `list-presets` to see what else is available.

The `--archive` flag also produces a `.tar.gz` next to the bundle directory — that is what you copy to the target device.

## 2. Run the bundle on a target device

Copy the bundle archive to the target, extract it, then run whichever runtime is appropriate. The script picks up the bundle metadata automatically, so the only thing you vary per device is `--runtime` and `--output-dir`.

```bash
# CPU via ONNX Runtime (works on Mac, Pi 5, Orange Pi)
uv run python scripts/device_detector_benchmark.py run \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --output-dir blob/device_benchmarks/<device-tag> \
  --runtime onnx \
  --tag <device-tag>

# Mac CoreML (via ONNX Runtime's CoreMLExecutionProvider)
uv run python scripts/device_detector_benchmark.py run \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --output-dir blob/device_benchmarks/local_m4_coreml \
  --runtime coreml

# Raspberry Pi 5 Hailo-8 (requires a compiled .hef — see Hailo HEF Workflow)
uv run python scripts/device_detector_benchmark.py run \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --output-dir blob/device_benchmarks/spencer_pi5_hailo \
  --runtime hailo

# Orange Pi 5 RKNN (requires pre-built .rknn files — one per model)
uv run python scripts/device_detector_benchmark.py run \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --output-dir blob/device_benchmarks/orangepi_npu_rknn \
  --runtime rknn \
  --rknn-model 20260331-zone-classification-chamber-yolo11s=/path/to/yolo11s.rknn \
  --rknn-model 20260331-zone-classification-chamber-nanodet=/path/to/nanodet.rknn
```

Each run writes a result directory containing one JSON per model plus a `summary.json` with the averaged FPS and latency numbers.

## 3. Compare two result sets

`compare` is the parity gate before trusting a new target path. It diffs detections frame-by-frame and writes decision parity + IoU + count-match statistics.

```bash
uv run python scripts/device_detector_benchmark.py compare \
  --left-results-dir blob/device_benchmarks/local_m4_cpu \
  --right-results-dir blob/device_benchmarks/spencer_pi5_hailo \
  --output blob/device_benchmarks/local_cpu_vs_spencer_pi_hailo.json
```

The left side is almost always the Mac Mini M4 CPU run — that is the current quality reference because CPU ONNX Runtime reproduces the original FP32 training behaviour bit-for-bit.

## 4. Render a visual report

```bash
uv run python scripts/device_detector_benchmark.py report \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --results-dir blob/device_benchmarks \
  --output blob/device_benchmarks/chamber_zone_pair_report.html
```

Reports are regeneratable side output, not source of truth — delete them whenever they go stale. The bundle, the per-device result JSONs, and the `compare` JSONs are the durable artifacts.

## Runtime-specific notes

- **ONNX** — the correctness path on every CPU target. Reproduces training FP32 behaviour.
- **CoreML** — currently means ONNX Runtime with `CoreMLExecutionProvider`. We do not maintain a separate `.mlpackage`.
- **Hailo** — needs a compiled `.hef`. The compile path is documented in [Hailo HEF Workflow]({{ '/lab/object-detection/hailo-hef-workflow/' | relative_url }}).
- **RKNN** — needs `.rknn` files rebuilt from the exact current ONNX export. The calibration step matters — see the quantization note in [How the Models Are Built]({{ '/lab/object-detection/how-models-are-built/' | relative_url }}).
- **NCNN** — tooling exists, parity on the current chamber-zone exports is not yet good enough to trust.

## Concurrency harness

Single-stream FPS is only half the story on accelerators that expose multiple inference workers. The concurrency harness under `software/sorter/backend/blob/device_benchmarks/concurrency/` runs N workers against the same model and records per-worker and combined throughput. The three result JSONs committed there are what populate the parallel throughput tables in the [Overview]({{ '/lab/object-detection/' | relative_url }}).
