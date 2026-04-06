---
layout: default
title: Model Artifacts
slug: model-artifacts
kicker: Artifact Registry
lede: Which detector artifacts currently exist, what each format is for, and how each target path is produced from training outputs.
---

## Scope

The current maintained detector set is:

- `20260331-zone-classification-chamber-yolo11s`
- `20260331-zone-classification-chamber-nanodet`

These are the chamber-zone detector models used for the April 6, 2026 cross-device benchmark work.

## Canonical source runs

### YOLO11s

- Source run:
  - `software/client/blob/local_detection_models/20260331-zone-classification_chamber-yolo11s/run.json`
- Canonical ONNX export:
  - `software/client/blob/local_detection_models/20260331-zone-classification_chamber-yolo11s/exports/best.onnx`
- Canonical benchmark bundle copy:
  - `software/client/blob/device_benchmarks/chamber_zone_pair_bundle/models/20260331-zone-classification-chamber-yolo11s/model.onnx`

### NanoDet

- Source run:
  - `software/client/blob/local_detection_models/20260331-zone-classification_chamber-nanodet/run.json`
- Canonical ONNX export:
  - `software/client/blob/local_detection_models/20260331-zone-classification_chamber-nanodet/exports/best.onnx`
- Canonical benchmark bundle copy:
  - `software/client/blob/device_benchmarks/chamber_zone_pair_bundle/models/20260331-zone-classification-chamber-nanodet/model.onnx`

## Format matrix

| Format | Purpose | Current status | Canonical location |
| --- | --- | --- | --- |
| `ONNX` | Main interchange format and correctness reference on CPU paths | Approved | `software/client/blob/device_benchmarks/chamber_zone_pair_bundle/models/.../model.onnx` |
| `NCNN` | CPU deployment experiments on low-power devices | Built, but currently not quality-approved for these chamber-zone exports | `software/client/blob/device_benchmarks/chamber_zone_pair_bundle/models/.../model.ncnn.param` and `model.ncnn.bin` |
| `CoreMLExecutionProvider` | Fast local Mac acceleration path using ONNX Runtime | Approved for local benchmarking; no separate `.mlpackage` is maintained right now | Reuses the canonical ONNX models |
| `RKNN` | Orange Pi NPU deployment path | Experimental; current artifacts are not rebuilt from the exact current ONNX exports | Existing Orange Pi device-side artifacts under `/root/bench/models` |
| `HEF` | Raspberry Pi 5 AI HAT deployment path | Built for both models; NanoDet currently has the stronger quality result | `software/client/blob/hailo_compile_bundles/.../results/` |
| `HAR` | Intermediate Hailo compiler output | Built and worth keeping with the matching `HEF` | `software/client/blob/hailo_compile_bundles/.../results/` |

## Current target mapping

### Mac Mini M4

CPU reference:

- Input format: `ONNX`
- Runtime: `onnxruntime` on CPU
- Status: reference path

Accelerated local path:

- Input format: `ONNX`
- Runtime: `onnxruntime` with `CoreMLExecutionProvider`
- Status: benchmark-approved

### Raspberry Pi 5

CPU fallback and correctness path:

- Input format: `ONNX`
- Runtime: `onnxruntime==1.23.2`
- Status: approved

AI HAT path:

- Input format: `HEF`
- Runtime: Hailo runtime stack on Raspberry Pi OS
- Status:
  - `NanoDet`: strongest current accelerated result
  - `YOLO11s`: built and runnable, but still needs closer parity tuning

### Orange Pi 5

CPU fallback and correctness path:

- Input format: `ONNX`
- Runtime: `onnxruntime`
- Status: approved

NPU path:

- Input format: `RKNN`
- Runtime: `rknnlite`
- Status: experimental until rebuilt from the exact current ONNX exports

## Conversion rule

The durable rule is:

`training run -> canonical ONNX export -> target-specific compiled format`

Do not compile target-specific formats directly from ad hoc copies if the ONNX source is unclear.

## Conversion map

### 1. Training run to ONNX

The training and export runs live under:

- `software/client/blob/local_detection_models/...`

The ONNX export from that run is the canonical source for downstream targets.

### 2. ONNX to benchmark bundle

Use:

```bash
cd software/client
uv run python scripts/device_detector_benchmark.py bundle \
  --preset chamber_zone_pair \
  --output blob/device_benchmarks/chamber_zone_pair_bundle \
  --archive
```

The bundle becomes the single benchmarking input across devices.

### 3. ONNX to Mac CPU, Mac CoreML, Pi CPU, Orange Pi CPU

Use:

```bash
uv run python scripts/device_detector_benchmark.py run \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --output-dir <target-output-dir> \
  --runtime onnx
```

For the Mac accelerated path:

```bash
uv run python scripts/device_detector_benchmark.py run \
  --bundle blob/device_benchmarks/chamber_zone_pair_bundle \
  --output-dir <target-output-dir> \
  --runtime coreml
```

### 4. ONNX to NCNN

The benchmark bundle already carries NCNN exports, but the current chamber-zone NCNN results are not approved yet.

### 5. ONNX to RKNN

The Orange Pi NPU path needs:

- the exact current ONNX export
- a matching RKNN toolkit and compiler environment
- a fresh `.rknn` rebuild

Current status: runtime-side RKNN execution exists, but the current chamber-zone RKNN artifacts are not yet quality-approved.

### 6. ONNX to Hailo HEF

Use:

- `software/client/scripts/prepare_hailo_compile_bundle.py`
- `software/client/scripts/vastai_hailo_session.py`

Detailed instructions live in [Hailo HEF Workflow](hailo-hef-workflow.html).

Current maintained results:

- `software/client/blob/hailo_compile_bundles/classification_chamber_yolo11s/results/yolov11s_piece_320.hef`
- `software/client/blob/hailo_compile_bundles/classification_chamber_nanodet/results/nanodet_plus_m_1_5x_piece_416_raw.hef`

## Update policy

When a new detector export replaces the current chamber-zone models, update:

1. this page
2. [Runtime Status](runtime-status.html)
3. [Device Benchmarking](device-benchmarking.html) if the benchmark preset or runtime rules change
4. [Hailo HEF Workflow](hailo-hef-workflow.html) if the Hailo compile flow changes
