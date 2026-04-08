---
layout: default
title: Object Detection Research
section: lab
slug: lab-object-detection
kicker: Lab — Research Area
lede: The Sorter needs to know where each LEGO piece sits inside the chamber so it can decide what to do next. This page records what we have measured so far — which detector models we trained and what kind of throughput each piece of hardware actually delivers.
permalink: /lab/object-detection/
---

## What this research area is about

The sorter's camera sits over a fixed chamber. The job of the detector is: given one camera frame, **find the piece in the chamber** and return a tight bounding box around it. That box becomes the cropped image we feed into the next stage and is also what the mechanical system plans its next motion around.

There is exactly one class — `piece` — and the camera position is fixed. That single-class, fixed-viewpoint setup is what lets a comparatively small model do useful work on edge hardware.

This page is a **measurement record**, not a recommendation. The deeper trade-off discussion and the eventual deployment decision live elsewhere; here we just write down what we did and what came out of it.

## Current maintained models

Both models share the same training dataset (1,877 labelled chamber frames, single class `piece`, 90/10 train/val split) and were trained on rented Vast.ai GPU instances.

| Model | Architecture | Input size | Training mAP |
| --- | --- | --- | --- |
| **Chamber Zone NanoDet** | NanoDet-Plus-m 1.5x | 416 × 416 | mAP 0.885 (AP50 0.941, AP75 0.900) |
| **Chamber Zone YOLO11s** | YOLOv11s | 320 × 320 | mAP50 0.960, mAP50–95 0.911 (precision 0.944, recall 0.872 at epoch 124) |

The canonical exports live under `software/client/blob/local_detection_models/`. Dig into [How the Models Are Built]({{ '/lab/object-detection/how-models-are-built/' | relative_url }}) for the training and export pipeline.

## Single-stream FPS across devices

Every row below is a real run against the same 50-image chamber-zone benchmark bundle (3 warm-up frames, then 50 timed frames per model). The numbers come from `software/client/blob/device_benchmarks/*/…__*.json`.

| Device | Runtime | NanoDet FPS | YOLO11s FPS |
| --- | --- | ---: | ---: |
| Mac Mini (Apple Silicon) | CPU via ONNX Runtime | 76.5 | 59.8 |
| Mac Mini (Apple Silicon) | CoreML via ORT | 40.4 | 418.3 |
| Raspberry Pi 5 | Hailo-8 | 132.1 | 100.1 |
| Raspberry Pi 5 | CPU via ONNX Runtime 1.23.2 | 12.7 | 8.6 |
| Raspberry Pi 5 | NCNN | 25.7 | 18.5 |
| Orange Pi 5 | CPU via ONNX Runtime | 20.6 | 12.0 |
| Orange Pi 5 | NPU via RKNN (1 worker) | 46.0 | 41.6 |

FPS is the average frames-per-second across the 50 benchmark samples after the warm-up.

## Sustained parallel throughput

A single-stream FPS number does not tell the whole story for accelerator hardware. Both the Hailo-8 on the Pi 5 and the RKNPU on the Orange Pi 5 expose multiple inference workers, so we ran a separate concurrency harness (`software/client/blob/device_benchmarks/concurrency/`) to measure what happens when several streams hit the same device at the same time.

### Orange Pi 5 NPU (RKNN) — 3 sustained workers

The RK3588 ships with **three physical NPU cores**, and the parallel benchmark shows that we can keep all three of them busy with independent inference workers without losing per-worker throughput. Each worker runs at very close to its single-worker speed.

| Model | Workers | Per-worker FPS | Combined FPS |
| --- | ---: | ---: | ---: |
| NanoDet | 1 | 40.0 | 40.0 |
| NanoDet | 3 (sustained) | ~33 each | **95.0** |
| YOLO11s | 1 | 39.0 | 39.0 |
| YOLO11s | 3 (sustained) | ~36 each | **106.0** |

Source: `concurrency/orangepi_parallel_npu_20260406.json`. The three-worker scenarios are real sustained runs (~165–192 frames per worker), not micro-bursts, so this is genuine sustained throughput rather than a peak number.

### Raspberry Pi 5 Hailo-8 — concurrency behaviour

The Hailo-8 also accepts multiple workers, but it does not parallelize the same way the RK3588 NPU does — it **time-slices a roughly fixed throughput budget**. Combined throughput stays nearly constant as you add workers, while per-worker FPS falls off proportionally.

| Model | Workers | Per-worker FPS | Combined FPS |
| --- | ---: | ---: | ---: |
| NanoDet | 1 | 111.8 | 111.8 |
| NanoDet | 2 | 57.9 | 115.8 |
| NanoDet | 3 | 38.6 | 115.8 |
| YOLO11s | 1 | 72.8 | 72.8 |
| YOLO11s | 2 | 36.4 | 72.8 |
| YOLO11s | 3 | 24.3 | 73.0 |

Source: `concurrency/hailo_parallel_20260406.json`. Note that the single-worker numbers in this run differ slightly from the main single-stream table above (132.1 vs 111.8 for NanoDet, 100.1 vs 72.8 for YOLO11s) because the concurrency harness is a separate measurement script — the relative behaviour across worker counts is what this table is for.

### Raspberry Pi 5 CPU — concurrency behaviour

For comparison, the same concurrency harness against the Pi 5 CPU (ONNX Runtime) shows the opposite pattern: parallel workers actively cost combined throughput because the four CPU cores get into contention.

| Model | Workers | Per-worker FPS | Combined FPS |
| --- | ---: | ---: | ---: |
| NanoDet | 1 | 12.2 | 11.4 |
| NanoDet | 2 | 5.8 | 10.4 |
| NanoDet | 3 | 3.6 | 9.1 |
| YOLO11s | 1 | 8.8 | 8.2 |
| YOLO11s | 2 | 4.6 | 7.9 |
| YOLO11s | 3 | 2.8 | 6.7 |

Source: `concurrency/spencer_pi_cpu_parallel_20260406.json`.

## What this tells us about the hardware

These three concurrency tables together describe three different concurrency behaviours:

- **RK3588 NPU (Orange Pi 5):** scales close to linearly up to 3 workers because each worker gets one of the three physical NPU cores. Three sustained streams at ~33 FPS each.
- **Hailo-8 (Raspberry Pi 5 AI HAT):** time-slices a fixed throughput budget. One worker is already saturating the device; adding workers just splits the same total FPS across them.
- **Pi 5 CPU (ONNX Runtime):** loses combined throughput as workers are added because the four ARM cores get into contention.

Interpretation of which combination is the right one to actually deploy is intentionally **out of scope on this page** — it depends on per-worker latency, quality of the deployed export, and the surrounding pipeline. We will come back to that in a dedicated decision page once the deployment direction is settled.

## Where to dig deeper

<div class="callout-grid">
  <div class="callout">
    <strong><a href="{{ '/lab/object-detection/how-models-are-built/' | relative_url }}">How the Models Are Built</a></strong>
    <p>Dataset, architectures, the Vast.ai training workflow, the canonical export pipeline, and the quantization story for Hailo and RKNN targets.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/object-detection/device-benchmarking/' | relative_url }}">Benchmarking Workflow</a></strong>
    <p>How to run the same benchmark bundle on a new device, compare the results against the Mac CPU reference, and regenerate the FPS and parity tables.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/object-detection/hailo-hef-workflow/' | relative_url }}">Hailo HEF Workflow</a></strong>
    <p>The maintained ONNX → HEF compile path for the Raspberry Pi 5 AI HAT, including the Vast.ai compile session packaging.</p>
  </div>
</div>
