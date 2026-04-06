---
layout: default
title: Device Benchmarking
slug: device-benchmarking
kicker: Repeatable Validation
lede: The maintained workflow for running the same detector benchmark on multiple devices and comparing both output parity and practical throughput.
---

## Tooling

Main entry point:

- `software/client/scripts/device_detector_benchmark.py`

Supported commands:

- `list-presets`
- `bundle`
- `run`
- `compare`
- `report`

## Core idea

We benchmark from a portable bundle, not from ad hoc local files.

A benchmark bundle contains:

- a fixed image set
- manifest metadata
- canonical exported model artifacts
- source run metadata

That gives us one reproducible input for every device.

## Standard workflow

### 1. Build the bundle on the dev machine

From `software/client`:

```bash
uv run python scripts/device_detector_benchmark.py list-presets

uv run python scripts/device_detector_benchmark.py bundle \
  --preset chamber_zone_pair \
  --output blob/device_benchmarks/chamber_zone_pair_bundle \
  --archive
```

The current standard preset is `chamber_zone_pair`. It packages the current chamber-zone `YOLO11s` and `NanoDet` pair together with the shared 50-image benchmark subset.

### 2. Run the bundle on the target device

Example CPU run:

```bash
uv run python scripts/device_detector_benchmark.py run \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --output-dir blob/device_benchmarks/pi5_aihat_cpu_ort123 \
  --runtime onnx \
  --tag pi5-aihat-cpu-ort123
```

Example Mac CoreML run:

```bash
uv run python scripts/device_detector_benchmark.py run \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --output-dir blob/device_benchmarks/local_m4_coreml_20260406 \
  --runtime coreml \
  --tag local-m4-coreml-20260406
```

Example Hailo run:

```bash
uv run python scripts/device_detector_benchmark.py run \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --output-dir blob/device_benchmarks/spencer_pi5_hailo \
  --runtime hailo
```

Example Orange Pi RKNN run:

```bash
uv run python scripts/device_detector_benchmark.py run \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --output-dir blob/device_benchmarks/orangepi_npu_rknn_20260406 \
  --runtime rknn \
  --rknn-model 20260331-zone-classification-chamber-yolo11s=/path/to/yolo11s.rknn \
  --rknn-model 20260331-zone-classification-chamber-nanodet=/path/to/nanodet.rknn
```

## Compare two result sets

Use `compare` when you want a machine-readable quality diff:

```bash
uv run python scripts/device_detector_benchmark.py compare \
  --left-results-dir blob/device_benchmarks/local_m4_cpu_20260406 \
  --right-results-dir blob/device_benchmarks/spencer_pi5_hailo \
  --output blob/device_benchmarks/local_cpu_vs_spencer_pi_hailo_20260406.json
```

This is the main parity check before trusting a new target path.

## Render a human-friendly report

Use `report` when you want a visual HTML comparison from benchmark JSONs:

```bash
uv run python scripts/device_detector_benchmark.py report \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --results-dir blob/device_benchmarks \
  --output blob/device_benchmarks/chamber_zone_pair_report.html
```

We also maintain two higher-level renderers:

- `software/client/scripts/render_platform_matrix_report.py`
- `software/client/scripts/render_legacy_parallel_matrix_report.py`

Those are summary outputs, not the source of truth. The source of truth is still:

- bundle
- result JSONs
- compare JSONs

## Runtime notes

### ONNX

Use this as the main correctness path on CPU targets.

Validated:

- Mac Mini M4 CPU
- Orange Pi CPU
- Raspberry Pi 5 CPU with `onnxruntime==1.23.2`

### CoreML

This path currently means ONNX Runtime with `CoreMLExecutionProvider`.

We are not maintaining a separate exported CoreML model package yet.

### NCNN

NCNN support exists in the benchmark tooling, but the current chamber-zone exports are not quality-approved on the tested Pi path.

Treat NCNN as experimental until parity is improved.

### RKNN

RKNN support exists in the benchmark tooling, but current quality depends entirely on whether the `.rknn` files were rebuilt from the exact current ONNX exports.

The current Orange Pi RKNN artifacts should be treated as experimental.

### Hailo

Hailo runs need compiled `HEF` files. The compile workflow is documented in [Hailo HEF Workflow](hailo-hef-workflow.html).

## Artifact policy

To avoid accumulating random JSON and HTML files:

1. Keep one canonical benchmark bundle per detector set.
2. Keep one canonical result directory per device, runtime, and date.
3. Keep compare JSONs for approved decision points.
4. Keep only the summary HTML reports that still matter.
5. Delete or regenerate exploratory reports and logs freely.

The current canonical set is listed in [Runtime Status](runtime-status.html).
