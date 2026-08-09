---
layout: default
title: How the Models Are Built
type: explanation
section: lab
slug: how-models-are-built
kicker: Object Detection Research
lede: The dataset, the model architectures, the training pipeline, and the export workflow that turn raw chamber frames into the deployable detector files we ship to each target device.
permalink: /lab/object-detection/how-models-are-built/
---

## What the model has to do

The detector's job is narrow on purpose: **find the LEGO piece in the chamber and return one tight bounding box around it.** There is exactly one class — `piece` — and the camera position is fixed, so the model never has to deal with arbitrary scenes or many objects. That single-class, fixed-viewpoint setup is what lets a comparatively small model reach the quality we need.

Everything downstream — the cropped image we feed into colour and shape classification, the position the mechanical system plans against, the decision about whether the chamber holds zero, one, or several pieces — is built on top of that one bounding box.

## The dataset

| Property | Value |
| --- | --- |
| Source location | `software/sorter/backend/blob/zone_datasets/classification_chamber/` |
| Images total | 1,877 |
| Train / val split | 1,690 / 187 (≈ 90 / 10) |
| Classes | 1 (`piece`) |
| Resolution | Native chamber camera resolution; resized at training time |
| Annotation format | YOLO-style bounding boxes |

The dataset is single-class and chamber-specific. Every image was captured in the same fixed camera rig with the same lighting, which is the main reason a model with under 10M parameters can hit `mAP > 0.88` on real frames.

The same dataset feeds **both** model architectures — there is no separate NanoDet dataset and YOLO dataset. That keeps the cross-architecture comparison fair: any quality difference between NanoDet and YOLO11s is a property of the model and the export pipeline, not of the data.

## The two architectures we maintain

We deliberately keep two model families in production rotation. They are not redundant — they trade off in different directions, and on different target hardware different trade-offs win.

### NanoDet-Plus-m 1.5x (`Chamber Zone NanoDet`)

- **Family:** NanoDet — an anchor-free detector designed for mobile and edge inference.
- **Variant:** the `Plus-m` head with the `1.5x` width multiplier. This is the heaviest of the standard NanoDet sizes, but it still ends up substantially smaller than YOLO11s.
- **Input size:** 416 × 416.
- **Best training metrics:** `mAP 0.885`, `AP_50 0.941`, `AP_75 0.900`.
- **Why we keep it:** it is the model that compiles cleanly to Hailo HEF and stays close to reference quality after the compile. The Hailo `NanoDet` path is currently our **best edge deployment** — see the [Overview]({{ '/lab/object-detection/' | relative_url }}) FPS table.

### YOLO11s (`Chamber Zone YOLO11s`)

- **Family:** Ultralytics YOLOv11 in the `s` (small) size class.
- **Input size:** 320 × 320.
- **Best training metrics:** `mAP_50 0.96049`, `mAP_50–95 0.91101`, `precision 0.94381`, `recall 0.87160` — captured at training epoch 124.
- **Why we keep it:** it is the highest-fidelity model we have on the Mac CoreML path, where it hits about **418 FPS** while staying parity-exact to the Mac CPU reference. It is also the architecture where we want to invest in better Hailo post-training optimization, because the runtime is fast on Hailo (100 FPS) but the box parity is currently weaker than NanoDet's.

### Why not pick one and drop the other?

Because the right model depends on where you are running it. NanoDet wins on Hailo, YOLO11s wins on CoreML, and they are both exact-match on plain CPU paths. Maintaining both costs almost nothing — they share the same dataset and the same benchmark bundle — and it gives the rest of the project a real choice rather than a fixed bet.

## The training pipeline

Both models are trained off-machine on rented Vast.ai GPU instances. We do not train on the Mac Mini or on the Pi — training would be unreasonably slow on either, and it would block the developer machine for hours.

The end-to-end flow is:

1. **Prepare the labelled chamber dataset** in `software/sorter/backend/blob/zone_datasets/classification_chamber/` (the `data.yaml` plus `train/` and `val/` splits).
2. **Provision a Vast.ai GPU instance** with the appropriate framework (Ultralytics for YOLO, the NanoDet trainer for NanoDet).
3. **Run the training job** on the instance, capturing best-checkpoint metrics into a `run.json` file.
4. **Pull the resulting checkpoint and the `run.json`** back into `software/sorter/backend/blob/local_detection_models/<run-id>/`.
5. **Run the export step** on the developer machine, producing the canonical `best.onnx` and a sibling `best_ncnn_model/` directory.

The `run.json` for each model is the durable record of the training run — it carries the model family, the input size, the source provider (`vastai`), the best metrics, and the absolute paths to the resulting ONNX and NCNN exports. Both maintained models point at:

- `blob/local_detection_models/20260331-zone-classification_chamber-yolo11s/`
- `blob/local_detection_models/20260331-zone-classification_chamber-nanodet/`

## The export and packaging pipeline

Once the training step has produced a checkpoint, the rule is simple:

`training run → canonical ONNX export → target-specific compiled format`

The canonical ONNX export is the **single source of truth**. Every other format on every other target device is supposed to be produced from that exact ONNX file. If the source ONNX is unclear or out of date, the downstream artifact is suspect — this is exactly what bit the current Orange Pi RKNN files, where the `.rknn` artifacts were never rebuilt against the latest ONNX export.

### The benchmark bundle

The first thing we do with a new ONNX export is package it into a **benchmark bundle**. The bundle is one self-contained directory holding the model files (in every format we test), a fixed set of 50 chamber-frame images, and the metadata describing how the bundle was built.

```bash
cd software/client
uv run python scripts/device_detector_benchmark.py bundle \
  --preset chamber_zone_pair \
  --output blob/device_benchmarks/chamber_zone_pair_bundle \
  --archive
```

This single bundle then becomes the input to every device-side run, which is how we keep cross-device comparisons honest. See [Device Benchmarking]({{ '/lab/object-detection/device-benchmarking/' | relative_url }}) for the full workflow.

### Per-target export paths

| Target | Format | Producer | Notes |
| --- | --- | --- | --- |
| Mac CPU / Orange Pi CPU / Pi 5 CPU | `ONNX` | The canonical `best.onnx` from the training run | Used directly by ONNX Runtime — no further conversion |
| Mac CoreML | `ONNX` + `CoreMLExecutionProvider` | The same canonical ONNX | We do not maintain a separate `.mlpackage` — the CoreML execution provider in ORT is what wires it into the Mac neural engine |
| Raspberry Pi 5 NCNN | `.ncnn.param` + `.ncnn.bin` | Produced alongside the ONNX export at training time | Currently broken on these chamber-zone models — the parity scores collapse |
| Orange Pi 5 RKNN | `.rknn` | Built with the Rockchip RKNN toolkit from the canonical ONNX | Quantization-sensitive — the current artifacts are stale and need rebuilding |
| Raspberry Pi 5 Hailo-8 | `.hef` (compiled), `.har` (intermediate) | Built with the Hailo Dataflow Compiler on a Linux x86_64 host | The maintained compile path is documented in [Hailo HEF Workflow]({{ '/lab/object-detection/hailo-hef-workflow/' | relative_url }}) |

For the exact commands that drive each step — bundle build, per-device run, parity compare — see [Benchmarking Workflow]({{ '/lab/object-detection/device-benchmarking/' | relative_url }}). The Hailo-specific compile steps live in [Hailo HEF Workflow]({{ '/lab/object-detection/hailo-hef-workflow/' | relative_url }}).

## Why quantization matters here

ONNX, CoreML, and pure-CPU paths all run the model in **floating point**, so they reproduce the original training behaviour bit-for-bit (or close enough that the parity numbers come out at 1.0 / IoU 1.0). The accelerated edge paths are different: both **Hailo HEF** and **Rockchip RKNN** require the model to be **quantized** down to integer weights so the on-chip NPU can run it efficiently. Quantization is where most of our quality drift comes from.

There are two pieces that have to be right for quantization not to wreck the detector:

1. **The calibration dataset.** The compiler picks per-tensor activation ranges by feeding sample images through the FP32 model and recording the distributions. If the calibration set does not cover the same lighting and object shapes as production frames, the quantized model will mis-scale and start missing pieces.
2. **The compile flow itself.** Running the Hailo compiler at optimization level 0 (which is what our current NanoDet HEF uses, because the Vast.ai image we rented did not expose a working GPU stack for the Hailo toolchain) leaves performance on the table compared to a higher optimization level. The current NanoDet HEF is still very good — but a future re-compile with a better optimization pass is the obvious next quality-and-speed lever for YOLO11s on Hailo specifically.

The current state of each accelerated path:

- **Hailo + NanoDet:** quantization is currently good enough that decision parity sits at 0.98 and IoU at 0.94 against the Mac CPU reference. This is the strongest accelerated result we have.
- **Hailo + YOLO11s:** quantization holds the high-level decision (0.92) but the box IoU drops to 0.69 — the boxes are in roughly the right place but no longer tight. This is the path we want to revisit with a better optimization pass.
- **Orange Pi RKNN:** the existing artifacts are not from the current ONNX exports. They need to be rebuilt with a fresh calibration step against the current dataset before we can compare them fairly.

## How training quality maps to real-world quality

The training metrics (`mAP`, `AP_50`, `AP_75`) are useful as a sanity check — they tell us whether the trained model fundamentally learned the chamber detection task. They do **not** tell us how well that model will run on a Pi or how much quality the Hailo compile gives back.

That is why we have two parallel quality measurements:

- **Training-time `mAP`** — how well the FP32 checkpoint detects pieces on the held-out validation split.
- **Runtime parity vs Mac CPU reference** — how closely each deployed export reproduces the Mac CPU run on the same 50 chamber frames. This is the metric that actually predicts whether a target deployment will behave like the model we trained.

A new model only gets promoted into production rotation when **both** numbers are healthy: the training mAP is in the same neighbourhood as the existing models, **and** the Mac-CPU-parity comparison on the deployed export is within tolerance. That gate is what stops a "looks good in training" export from quietly regressing the running sorter.
