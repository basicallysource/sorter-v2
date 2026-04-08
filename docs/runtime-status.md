---
layout: default
title: Detector Runtime Status
slug: runtime-status
kicker: Runtime Findings
lede: The durable summary of what we learned from the detector experiments completed on April 6, 2026.
---

## Quality reference

The current quality reference is the local Mac Mini M4 CPU run on the shared 50-image chamber-zone benchmark bundle.

## Current validated findings

| Platform / Runtime | Model | Match vs Mac CPU | Notes |
| --- | --- | --- | --- |
| Mac Mini M4 `CPU` | `NanoDet`, `YOLO11s` | Reference | Baseline for all comparisons |
| Mac Mini M4 `CoreMLExecutionProvider` | `NanoDet`, `YOLO11s` | Decision and count parity are effectively exact | `YOLO11s` is much faster than CPU, `NanoDet` is slower |
| Orange Pi 5 `CPU (ONNX)` | `NanoDet`, `YOLO11s` | Exact on this benchmark bundle | Safe correctness path on Orange Pi |
| Orange Pi 5 `RKNN` | `NanoDet`, `YOLO11s` | Not close enough yet | Current `.rknn` files were pre-existing and were not rebuilt from the exact current ONNX exports |
| Raspberry Pi 5 `CPU (ONNXRuntime 1.23.2)` | `NanoDet`, `YOLO11s` | Exact on this benchmark bundle | Safe correctness path on Pi 5 |
| Raspberry Pi 5 `Hailo-8` | `NanoDet` | Very close | Best current accelerated target |
| Raspberry Pi 5 `Hailo-8` | `YOLO11s` | Good on decision level, weaker on count and box parity | Promising, but not yet the closest target |
| Raspberry Pi 5 `NCNN` | `NanoDet`, `YOLO11s` | Not acceptable yet | Treat as experimental for these exports |

## Throughput takeaways

- `Mac Mini M4 + CoreML` is the fastest validated developer-side path, especially for `YOLO11s`.
- `Orange Pi CPU` and `Pi 5 CPU` are correctness baselines, not the best production throughput paths.
- `Orange Pi RKNN` scales well in parallel because RK3588 has three physical NPU cores, but the current artifacts are not quality-approved.
- `Pi 5 + Hailo` behaves differently from RK3588: it supports multiple jobs, but mostly time-slices a fixed throughput budget rather than scaling total throughput linearly.
- `Pi 5 + Hailo + NanoDet` is the current best blend of speed and detection fidelity.

## Current recommendations

### If the priority is correctness

Use:

- `Mac Mini M4 CPU` for the reference run
- `Orange Pi CPU (ONNX)` when validating Orange Pi behavior
- `Raspberry Pi 5 CPU (ONNXRuntime 1.23.2)` when validating Pi 5 behavior

These paths currently mirror the reference exactly on the shared benchmark bundle.

### If the priority is accelerated deployment on the Pi 5 AI HAT

Use:

- `NanoDet HEF` first

Why:

- it is already compiled
- it is already benchmarked on the real Hailo target
- it is the closest accelerated result to the local CPU reference

Treat `YOLO11s HEF` as the next tuning candidate.

### If the priority is accelerated deployment on Orange Pi

Do not treat the current `RKNN` artifacts as release-ready.

Before using Orange Pi NPU results for product decisions, rebuild the `.rknn` files from the exact current ONNX exports and rerun the benchmark bundle.

## Canonical local artifacts to keep

Keep only the current canonical set and treat everything else under `software/client/blob/` as disposable scratch unless a document promotes it.

### Benchmark inputs and reference

- `software/client/blob/device_benchmarks/chamber_zone_pair_bundle/`
- `software/client/blob/device_benchmarks/local_reference/`

### Current result sets

- `software/client/blob/device_benchmarks/local_m4_cpu_20260406/`
- `software/client/blob/device_benchmarks/local_m4_coreml_20260406/`
- `software/client/blob/device_benchmarks/orangepi_cpu_onnx_20260406/`
- `software/client/blob/device_benchmarks/orangepi_npu_rknn_20260406/`
- `software/client/blob/device_benchmarks/pi5_aihat_cpu_ort123/`
- `software/client/blob/device_benchmarks/spencer_pi5_hailo/`

### Current comparison outputs

- `software/client/blob/device_benchmarks/local_cpu_vs_coreml_20260406.json`
- `software/client/blob/device_benchmarks/local_cpu_vs_orangepi_cpu_onnx_20260406.json`
- `software/client/blob/device_benchmarks/local_cpu_vs_orangepi_npu_rknn_20260406.json`
- `software/client/blob/device_benchmarks/local_cpu_vs_spencer_pi_cpu_ort123_20260406.json`
- `software/client/blob/device_benchmarks/local_cpu_vs_spencer_pi_hailo_20260406.json`
- `software/client/blob/device_benchmarks/orangepi_cpu_vs_npu_rknn_20260406.json`
- `software/client/blob/device_benchmarks/spencer_pi_cpu_vs_hailo_20260406.json`

### Current summary reports

- `software/client/blob/device_benchmarks/platform_matrix_report_20260406.html`
- `software/client/blob/device_benchmarks/platform_matrix_report_20260406_assets/`
- `software/client/blob/device_benchmarks/legacy_parallel_matrix_report_20260406.html`

### Current concurrency summaries

- `software/client/blob/device_benchmarks/concurrency/orangepi_parallel_npu_20260406.json`
- `software/client/blob/device_benchmarks/concurrency/hailo_parallel_20260406.json`
- `software/client/blob/device_benchmarks/concurrency/spencer_pi_cpu_parallel_20260406.json`

### Current Hailo deliverables

- `software/client/blob/hailo_compile_bundles/classification_chamber_yolo11s/results/`
- `software/client/blob/hailo_compile_bundles/classification_chamber_nanodet/results/`

## Policy for future work

1. Keep stable conclusions here in the site.
2. Keep only the latest canonical local artifacts under `software/client/blob/`.
3. Regenerate reports from benchmark JSONs instead of treating every HTML file as permanent.
4. Add new target conclusions only after the target has both:
   - a quality comparison against the Mac CPU reference
   - a sustained-throughput measurement
