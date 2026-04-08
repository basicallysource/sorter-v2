---
layout: default
title: Hailo HEF Workflow
section: lab
slug: hailo-hef-workflow
kicker: Object Detection Research
lede: The maintained ONNX to HEF path for running our custom detector models on the Raspberry Pi 5 AI HAT.
permalink: /lab/object-detection/hailo-hef-workflow/
---

## Before you start

Read these first:

- [How the Models Are Built]({{ '/lab/object-detection/how-models-are-built/' | relative_url }}) — in particular the quantization section, which explains why calibration matters here.
- [Benchmarking Workflow]({{ '/lab/object-detection/device-benchmarking/' | relative_url }}) — the compiled `.hef` is only useful once it has been run through the benchmark bundle and compared against the Mac CPU reference.

## Current state

- The Raspberry Pi target is healthy on the runtime side: `hailo-all` is installed, `/dev/hailo0` exists, and `hailortcli scan` sees the board.
- The board currently attached to the Pi reports as a `Hailo-8`, so the compile target is `hailo8`.
- Our `classification_chamber` `YOLO11s` export is the best first Hailo target because its ONNX graph already matches the official `YOLOv11` parser node layout from `hailo_model_zoo v2.18`.
- The local CPU reference run for this same model already matches between the Mac Mini M4 and the Pi 5 CPU path.

## Tooling

- `software/client/scripts/prepare_hailo_compile_bundle.py`
  - Builds a self-contained compile bundle with ONNX, Hailo config files, calibration images, and local reference artifacts.
- `software/client/scripts/vastai_hailo_session.py`
  - Searches Vast.ai offers and packages a manual compile workspace tarball.
  - Can auto-pick the required Hailo SDK payloads from a local download directory and stage an install script for the Vast.ai host.

## Current presets

- `classification_chamber_yolo11s`
- `classification_chamber_nanodet`

The YOLO11s preset pulls from:

- ONNX: `software/client/blob/local_detection_models/20260331-zone-classification_chamber-yolo11s/exports/best.onnx`
- Calibration set: `software/client/blob/zone_datasets/classification_chamber/train/images`
- Verification bundle: `software/client/blob/device_benchmarks/chamber_zone_pair_bundle`
- Local reference results: `software/client/blob/device_benchmarks/local_reference/local-m4__20260331-zone-classification-chamber-yolo11s__onnx.json`

The NanoDet preset pulls from:

- ONNX: `software/client/blob/local_detection_models/20260331-zone-classification_chamber-nanodet/exports/best.onnx`
- Calibration set: `software/client/blob/zone_datasets/classification_chamber/train/images`
- Verification bundle: `software/client/blob/device_benchmarks/chamber_zone_pair_bundle`
- Local reference results: `software/client/blob/device_benchmarks/local_reference/local-m4__20260331-zone-classification-chamber-nanodet__onnx.json`

## Refresh the compile bundle

From `software/client`:

```bash
uv run python scripts/prepare_hailo_compile_bundle.py build \
  --preset classification_chamber_yolo11s \
  --archive
```

Or:

```bash
uv run python scripts/prepare_hailo_compile_bundle.py build \
  --preset classification_chamber_nanodet \
  --archive
```

This creates the matching bundle directory plus archive, for example:

- `software/client/blob/hailo_compile_bundles/classification_chamber_yolo11s/`
- `software/client/blob/hailo_compile_bundles/classification_chamber_yolo11s.tar.gz`

## Packaging a manual Vast.ai session

If the Hailo downloads sit in `~/Downloads`:

```bash
uv run python scripts/vastai_hailo_session.py package-workspace \
  --bundle-dir blob/hailo_compile_bundles/classification_chamber_yolo11s \
  --output blob/hailo_compile_bundles/classification_chamber_yolo11s_vastai_session.tar.gz
```

Or point to a custom download directory:

```bash
uv run python scripts/vastai_hailo_session.py package-workspace \
  --bundle-dir blob/hailo_compile_bundles/classification_chamber_yolo11s \
  --vendor-downloads-dir /path/to/hailo-downloads \
  --output blob/hailo_compile_bundles/classification_chamber_yolo11s_vastai_session.tar.gz
```

## Compile host profile

The expected host is:

- `amd64`
- `Ubuntu 22.04` or `Ubuntu 24.04`
- one NVIDIA GPU is enough for the optimization step

Inside the session:

1. Extract the session archive under `/workspace`.
2. Install the matching Hailo SDK payloads.
3. Activate the Hailo environment.
4. Run `./compile_commands.sh` inside the bundle.

## Working Hailo-8 toolchain line

The successful Hailo-8 compile path used:

- `hailo_dataflow_compiler-3.33.1-py3-none-linux_x86_64.whl`
- `hailo_model_zoo-2.18.0-py3-none-any.whl`
- `hailort_4.23.0_amd64.deb`

The newer `5.x` toolchain line is for newer Hailo hardware and is not valid for our Pi AI HAT target.

## Current canonical outputs

YOLO11s:

- `software/client/blob/hailo_compile_bundles/classification_chamber_yolo11s/results/yolov11s_piece_320.har`
- `software/client/blob/hailo_compile_bundles/classification_chamber_yolo11s/results/yolov11s_piece_320.hef`

NanoDet:

- `software/client/blob/hailo_compile_bundles/classification_chamber_nanodet/results/nanodet_plus_m_1_5x_piece_416_raw.har`
- `software/client/blob/hailo_compile_bundles/classification_chamber_nanodet/results/nanodet_plus_m_1_5x_piece_416_raw.hef`

These `results/` directories are the canonical Hailo deliverables we keep locally.

## Known gotchas

- The compile host needed `libgl1`, `python3-tk`, and `bsdextrautils` in addition to the original package list.
- The Hailo compiler was sensitive to the shell locale, so `LANG`, `LC_ALL`, and `LANGUAGE` were pinned to `C.UTF-8`.
- The successful compile ran at optimization level `0` because the chosen Vast.ai image did not expose a compiler-usable GPU stack for that Hailo release line.
- For NanoDet, Pi-side validation matters even more because the raw heads are compiled and the final NanoDet decode and NMS stay on the host side.

## Validation after compilation

Once the `HEF` is ready:

1. Copy it to the Raspberry Pi 5.
2. Run inference on the same verification subset.
3. Compare the detections against the matching local reference JSON.

The target is not merely "it runs", but "it mirrors the local detections as closely as possible".
