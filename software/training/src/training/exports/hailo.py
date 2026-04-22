#!/usr/bin/env python3
"""Prepare self-contained Hailo compile bundles for our detector models."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import onnx
except ModuleNotFoundError as exc:  # pragma: no cover - exercised via CLI
    raise SystemExit(
        "onnx is required for this script. Run `uv sync` in software/training before using it."
    ) from exc


TRAINING_ROOT = Path(__file__).resolve().parents[3]
RUNS_DIR = TRAINING_ROOT / "runs"
DATASETS_DIR = TRAINING_ROOT / "datasets"
REPORTS_OUT_DIR = TRAINING_ROOT / "reports_out"
ZONE_DATASETS_DIR = DATASETS_DIR
DEVICE_BENCHMARKS_DIR = REPORTS_OUT_DIR / "device_benchmarks"
OUTPUT_ROOT = TRAINING_ROOT / "hailo_bundles"

YOLOV11S_END_NODES = (
    "/model.23/cv2.0/cv2.0.2/Conv",
    "/model.23/cv3.0/cv3.0.2/Conv",
    "/model.23/cv2.1/cv2.1.2/Conv",
    "/model.23/cv3.1/cv3.1.2/Conv",
    "/model.23/cv2.2/cv2.2.2/Conv",
    "/model.23/cv3.2/cv3.2.2/Conv",
)
NANODET_ZONE_END_NODES = (
    "/head/Concat",
    "/head/Concat_2",
    "/head/Concat_4",
    "/head/Concat_6",
)


@dataclass(frozen=True)
class HailoPreset:
    name: str
    label: str
    network_name: str
    model_id: str
    model_family: str
    hw_arch: str
    onnx_path: Path
    onnx_input_name: str
    onnx_input_shape: tuple[int, int, int, int]
    onnx_output_name: str
    classes: int
    default_conf: float
    default_iou: float
    calibration_dir: Path
    calibration_count: int
    verification_bundle_dir: Path
    reference_results_path: Path
    parser_end_nodes: tuple[str, ...]
    best_metrics: dict[str, float]
    normalization_mean: tuple[float, float, float]
    normalization_std: tuple[float, float, float]
    strides: tuple[int, ...] = ()
    regression_length: int | None = None


PRESETS: dict[str, HailoPreset] = {
    "classification_chamber_yolo11s": HailoPreset(
        name="classification_chamber_yolo11s",
        label="Classification Chamber YOLO11s -> Hailo-8 HEF",
        network_name="yolov11s_piece_320",
        model_id="20260331-zone-classification-chamber-yolo11s",
        model_family="yolo",
        hw_arch="hailo8",
        onnx_path=RUNS_DIR / "20260331-zone-classification_chamber-yolo11s" / "exports" / "best.onnx",
        onnx_input_name="images",
        onnx_input_shape=(1, 3, 320, 320),
        onnx_output_name="output0",
        classes=1,
        default_conf=0.25,
        default_iou=0.45,
        calibration_dir=ZONE_DATASETS_DIR / "classification_chamber" / "train" / "images",
        calibration_count=1024,
        verification_bundle_dir=DEVICE_BENCHMARKS_DIR / "chamber_zone_pair_bundle",
        reference_results_path=DEVICE_BENCHMARKS_DIR / "local_reference" / "local-m4__20260331-zone-classification-chamber-yolo11s__onnx.json",
        parser_end_nodes=YOLOV11S_END_NODES,
        best_metrics={
            "epoch": 124.0,
            "mAP50": 0.96049,
            "mAP50_95": 0.91101,
            "precision": 0.94381,
            "recall": 0.8716,
        },
        normalization_mean=(0.0, 0.0, 0.0),
        normalization_std=(255.0, 255.0, 255.0),
    ),
    "classification_chamber_nanodet": HailoPreset(
        name="classification_chamber_nanodet",
        label="Classification Chamber NanoDet+ m-1.5x-416 -> Hailo-8 HEF",
        network_name="nanodet_plus_m_1_5x_piece_416_raw",
        model_id="20260331-zone-classification-chamber-nanodet",
        model_family="nanodet",
        hw_arch="hailo8",
        onnx_path=RUNS_DIR / "20260331-zone-classification_chamber-nanodet" / "exports" / "best.onnx",
        onnx_input_name="data",
        onnx_input_shape=(1, 3, 416, 416),
        onnx_output_name="output",
        classes=1,
        default_conf=0.25,
        default_iou=0.45,
        calibration_dir=ZONE_DATASETS_DIR / "classification_chamber" / "train" / "images",
        calibration_count=1024,
        verification_bundle_dir=DEVICE_BENCHMARKS_DIR / "chamber_zone_pair_bundle",
        reference_results_path=DEVICE_BENCHMARKS_DIR / "local_reference" / "local-m4__20260331-zone-classification-chamber-nanodet__onnx.json",
        parser_end_nodes=NANODET_ZONE_END_NODES,
        best_metrics={
            "mAP": 0.885,
            "AP_50": 0.941,
            "AP_75": 0.9,
        },
        normalization_mean=(103.53, 116.28, 123.675),
        normalization_std=(57.375, 57.12, 58.395),
        strides=(8, 16, 32, 64),
        regression_length=7,
    ),
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _sorted_images(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )


def _validate_onnx(preset: HailoPreset) -> dict[str, Any]:
    model = onnx.load(str(preset.onnx_path))
    inputs = {}
    for value in model.graph.input:
        dims = []
        for dim in value.type.tensor_type.shape.dim:
            if dim.dim_value:
                dims.append(dim.dim_value)
            elif dim.dim_param:
                dims.append(dim.dim_param)
            else:
                dims.append("?")
        inputs[value.name] = dims

    outputs = {}
    for value in model.graph.output:
        dims = []
        for dim in value.type.tensor_type.shape.dim:
            if dim.dim_value:
                dims.append(dim.dim_value)
            elif dim.dim_param:
                dims.append(dim.dim_param)
            else:
                dims.append("?")
        outputs[value.name] = dims

    expected_shape = list(preset.onnx_input_shape)
    actual_shape = inputs.get(preset.onnx_input_name)
    if actual_shape != expected_shape:
        raise RuntimeError(
            f"Unexpected ONNX input for {preset.name}: expected {preset.onnx_input_name}={expected_shape}, got {actual_shape!r}"
        )
    if preset.onnx_output_name not in outputs:
        raise RuntimeError(
            f"Unexpected ONNX outputs for {preset.name}: missing {preset.onnx_output_name!r}, found {sorted(outputs)}"
        )

    node_names = {node.name for node in model.graph.node}
    node_outputs = {output_name for node in model.graph.node for output_name in node.output}
    missing_nodes = [name for name in preset.parser_end_nodes if name not in node_names and name not in node_outputs]
    if missing_nodes:
        raise RuntimeError(f"Parser nodes missing from {preset.onnx_path}: {missing_nodes}")

    return {
        "input_name": preset.onnx_input_name,
        "input_shape": actual_shape,
        "output_name": preset.onnx_output_name,
        "available_outputs": outputs,
        "parser_end_nodes": list(preset.parser_end_nodes),
        "sha256": _sha256(preset.onnx_path),
    }


def _make_hailo_yaml(preset: HailoPreset) -> str:
    end_nodes = "\n".join(f"    - {node}" for node in preset.parser_end_nodes)
    if preset.model_family == "nanodet":
        if not preset.strides:
            raise RuntimeError(f"NanoDet preset {preset.name} is missing strides")
        if preset.regression_length is None:
            raise RuntimeError(f"NanoDet preset {preset.name} is missing regression_length")
        strides = "\n".join(f"    - {stride}" for stride in preset.strides)
        return f"""base:
- base/nanodet.yaml
preprocessing:
  input_shape:
  - {preset.onnx_input_shape[2]}
  - {preset.onnx_input_shape[3]}
  - {preset.onnx_input_shape[1]}
postprocessing:
  device_pre_post_layers:
    nms: false
  meta_arch: nanodet
  nms_iou_thresh: {preset.default_iou}
  score_threshold: {preset.default_conf}
  anchors:
    scale_factors:
    - 0.0
    - 0.0
    regression_length: {preset.regression_length}
    strides:
{strides}
  hpp: false
network:
  network_name: {preset.network_name}
paths:
  alls_script: {preset.network_name}.alls
parser:
  nodes:
  - null
  -
{end_nodes}
info:
  task: object detection
  input_shape: {preset.onnx_input_shape[2]}x{preset.onnx_input_shape[3]}x{preset.onnx_input_shape[1]}
  output_shape: raw nanodet feature maps
  framework: pytorch
  supported_hw_arch:
  - hailo8
  - hailo8l
"""
    return f"""base:
- base/yolov8.yaml
postprocessing:
  device_pre_post_layers:
    nms: true
  hpp: true
network:
  network_name: {preset.network_name}
paths:
  alls_script: {preset.network_name}.alls
parser:
  nodes:
  - null
  -
{end_nodes}
info:
  task: object detection
  input_shape: {preset.onnx_input_shape[2]}x{preset.onnx_input_shape[3]}x{preset.onnx_input_shape[1]}
  output_shape: {preset.classes}x5x100
  framework: pytorch
  supported_hw_arch:
  - hailo8
  - hailo8l
"""


def _make_nms_config(preset: HailoPreset) -> dict[str, Any]:
    if preset.model_family == "nanodet":
        raise RuntimeError("NanoDet raw-output bundles do not use a Hailo NMS JSON config")
    imgsz = preset.onnx_input_shape[2]
    return {
        "nms_scores_th": preset.default_conf,
        "nms_iou_th": preset.default_iou,
        "image_dims": [imgsz, imgsz],
        "max_proposals_per_class": 100,
        "classes": preset.classes,
        "regression_length": 16,
        "background_removal": False,
        "background_removal_index": 0,
        "bbox_decoders": [
            {
                "name": "bbox_decoder51",
                "stride": 8,
                "reg_layer": "conv51",
                "cls_layer": "conv54",
            },
            {
                "name": "bbox_decoder62",
                "stride": 16,
                "reg_layer": "conv62",
                "cls_layer": "conv65",
            },
            {
                "name": "bbox_decoder77",
                "stride": 32,
                "reg_layer": "conv77",
                "cls_layer": "conv80",
            },
        ],
    }


def _make_alls_script(preset: HailoPreset) -> str:
    if preset.model_family == "nanodet":
        return f"""normalization1 = normalization([{preset.normalization_mean[0]}, {preset.normalization_mean[1]}, {preset.normalization_mean[2]}], [{preset.normalization_std[0]}, {preset.normalization_std[1]}, {preset.normalization_std[2]}])
model_optimization_config(calibration, batch_size=4, calibset_size=64)
allocator_param(merge_min_layer_utilization=0.1)
"""

    nms_filename = f"{preset.network_name}_nms_config.json"
    return f"""normalization1 = normalization([{preset.normalization_mean[0]}, {preset.normalization_mean[1]}, {preset.normalization_mean[2]}], [{preset.normalization_std[0]}, {preset.normalization_std[1]}, {preset.normalization_std[2]}])
change_output_activation(conv54, sigmoid)
change_output_activation(conv65, sigmoid)
change_output_activation(conv80, sigmoid)
nms_postprocess("./{nms_filename}", meta_arch=yolov8, engine=cpu)
"""


def _make_compile_commands(preset: HailoPreset) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
RESULTS_DIR="${{1:-$BUNDLE_DIR/results}}"

# The Hailo compiler can choke on forwarded locales like de_DE.UTF-8 on minimal cloud hosts.
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export LANGUAGE=C.UTF-8

mkdir -p "$RESULTS_DIR"
cd "$RESULTS_DIR"

echo "Compiling {preset.network_name} into $RESULTS_DIR"

hailomz compile \\
  --yaml "$BUNDLE_DIR/hailo/{preset.network_name}.yaml" \\
  --ckpt "$BUNDLE_DIR/model/model.onnx" \\
  --calib-path "$BUNDLE_DIR/calibration/images" \\
  --model-script "$BUNDLE_DIR/hailo/{preset.network_name}.alls" \\
  --classes {preset.classes} \\
  --hw-arch {preset.hw_arch}

echo
echo "Expected outputs:"
echo "  $RESULTS_DIR/{preset.network_name}.har"
echo "  $RESULTS_DIR/{preset.network_name}.hef"
"""


def _make_readme(preset: HailoPreset, bundle_dir: Path, calibration_count: int) -> str:
    if preset.model_family == "nanodet":
        return f"""# {preset.label}

This bundle compiles our custom NanoDet export for the Raspberry Pi 5 AI HAT.

## Why this preset is separate

- The target board exposes a `Hailo-8` accelerator, so the compile target is `hailo8`.
- Our NanoDet export is compiled from the four feature-map heads instead of the final flattened ONNX output.
- We intentionally keep NanoDet postprocessing on the host side so we can mirror the existing local decode path as closely as possible.

## Contents

- `model/model.onnx`: custom ONNX export used for Hailo compilation
- `hailo/`: custom YAML and ALLS script for raw NanoDet head compilation
- `calibration/images/`: deterministic calibration subset from `classification_chamber/train/images`
- `verification/`: the 50-image benchmark subset plus the local reference results JSON for this exact model
- `compile_commands.sh`: one-shot `hailomz compile` helper

## Expected compile command

```bash
./compile_commands.sh
```

That command expects a host with `hailomz` and the Hailo Dataflow Compiler already installed.

## Reference expectations

- Compile target: `{preset.hw_arch}`
- Classes: `{preset.classes}`
- Local reference runtime: `onnxruntime 1.23.2`
- Local benchmark thresholds: `conf={preset.default_conf}`, `iou={preset.default_iou}`
- Calibration images in bundle: `{calibration_count}`

## Output path

The prepared bundle lives at:

`{bundle_dir}`
"""
    return f"""# {preset.label}

This bundle is the first Hailo compile target for the Raspberry Pi 5 AI HAT system.

## Why this preset first

- The target board exposes a `Hailo-8` accelerator, so the compile target is `hailo8`.
- Our custom `YOLO11s` export already matches Hailo's official `YOLOv11` parser node layout.
- The ONNX model is fixed-shape (`1x3x320x320`) and already matches the local benchmark pipeline.

## Contents

- `model/model.onnx`: custom ONNX export used for Hailo compilation
- `hailo/`: custom YAML, ALLS script, and NMS config derived from the official `v2.18` `yolov11s` config
- `calibration/images/`: deterministic calibration subset from `classification_chamber/train/images`
- `verification/`: the 50-image benchmark subset plus the local reference results JSON for this exact model
- `compile_commands.sh`: one-shot `hailomz compile` helper

## Expected compile command

```bash
./compile_commands.sh
```

That command expects a host with `hailomz` and the Hailo Dataflow Compiler already installed.

## Reference expectations

- Compile target: `{preset.hw_arch}`
- Classes: `{preset.classes}`
- Local reference runtime: `onnxruntime 1.23.2`
- Local benchmark thresholds: `conf={preset.default_conf}`, `iou={preset.default_iou}`
- Calibration images in bundle: `{calibration_count}`

## Output path

The prepared bundle lives at:

`{bundle_dir}`
"""


def _copy_calibration_images(preset: HailoPreset, destination_dir: Path) -> list[str]:
    available = _sorted_images(preset.calibration_dir)
    if len(available) < preset.calibration_count:
        raise RuntimeError(
            f"Calibration source {preset.calibration_dir} has only {len(available)} images, need {preset.calibration_count}"
        )

    copied: list[str] = []
    for source in available[: preset.calibration_count]:
        target = destination_dir / source.name
        _copy_file(source, target)
        copied.append(source.name)
    return copied


def _copy_verification_assets(preset: HailoPreset, destination_dir: Path) -> dict[str, Any]:
    source_manifest = _load_json(preset.verification_bundle_dir / "manifest.json")
    model_entry = next(
        (model for model in source_manifest.get("models", []) if model.get("id") == preset.model_id),
        None,
    )
    if model_entry is None:
        raise RuntimeError(f"Could not find model {preset.model_id!r} in {preset.verification_bundle_dir / 'manifest.json'}")

    images_dir = destination_dir / "images"
    copied_images: list[str] = []
    for sample in source_manifest.get("samples", []):
        image_name = sample["image"]
        _copy_file(preset.verification_bundle_dir / "images" / image_name, images_dir / image_name)
        copied_images.append(image_name)

    _copy_file(preset.reference_results_path, destination_dir / "reference" / preset.reference_results_path.name)
    verification_manifest = {
        "source_bundle": str(preset.verification_bundle_dir),
        "model": model_entry,
        "sample_count": len(source_manifest.get("samples", [])),
        "samples": source_manifest.get("samples", []),
        "reference_results": str(Path("reference") / preset.reference_results_path.name),
    }
    _write_json(destination_dir / "manifest.json", verification_manifest)
    return {
        "sample_count": verification_manifest["sample_count"],
        "copied_images": copied_images,
        "reference_results": verification_manifest["reference_results"],
    }


def _build_bundle(preset: HailoPreset, output_dir: Path, archive: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    onnx_meta = _validate_onnx(preset)
    calibration_images = _copy_calibration_images(preset, output_dir / "calibration" / "images")
    verification_meta = _copy_verification_assets(preset, output_dir / "verification")

    _copy_file(preset.onnx_path, output_dir / "model" / "model.onnx")
    (output_dir / "hailo").mkdir(parents=True, exist_ok=True)
    (output_dir / "hailo" / f"{preset.network_name}.yaml").write_text(_make_hailo_yaml(preset))
    if preset.model_family == "yolo":
        _write_json(output_dir / "hailo" / f"{preset.network_name}_nms_config.json", _make_nms_config(preset))
    (output_dir / "hailo" / f"{preset.network_name}.alls").write_text(_make_alls_script(preset))
    compile_script_path = output_dir / "compile_commands.sh"
    compile_script_path.write_text(_make_compile_commands(preset))
    compile_script_path.chmod(0o755)
    (output_dir / "README.md").write_text(_make_readme(preset, output_dir, len(calibration_images)))

    manifest = {
        "preset": preset.name,
        "label": preset.label,
        "network_name": preset.network_name,
        "hw_arch": preset.hw_arch,
        "model_family": preset.model_family,
        "model_id": preset.model_id,
        "classes": preset.classes,
        "default_conf": preset.default_conf,
        "default_iou": preset.default_iou,
        "source_onnx": str(preset.onnx_path),
        "source_calibration_dir": str(preset.calibration_dir),
        "best_metrics": preset.best_metrics,
        "onnx": onnx_meta,
        "calibration": {
            "count": len(calibration_images),
            "images": calibration_images,
        },
        "verification": verification_meta,
        "artifacts": {
            "compile_script": "compile_commands.sh",
            "yaml": f"hailo/{preset.network_name}.yaml",
            "alls": f"hailo/{preset.network_name}.alls",
            "onnx": "model/model.onnx",
        },
    }
    if preset.model_family == "yolo":
        manifest["artifacts"]["nms_config"] = f"hailo/{preset.network_name}_nms_config.json"
    _write_json(output_dir / "manifest.json", manifest)

    if archive:
        archive_path = output_dir.with_suffix(".tar.gz")
        if archive_path.exists():
            archive_path.unlink()
        with tarfile.open(archive_path, "w:gz") as handle:
            handle.add(output_dir, arcname=output_dir.name)

    return output_dir


def _default_output_dir(preset_name: str) -> Path:
    return OUTPUT_ROOT / preset_name


def _list_presets() -> int:
    for preset in PRESETS.values():
        print(f"{preset.name}: {preset.label}")
        print(f"  model={preset.onnx_path}")
        print(f"  calibration={preset.calibration_dir} ({preset.calibration_count} images)")
        print(f"  verification={preset.verification_bundle_dir}")
    return 0


def _build_command(args: argparse.Namespace) -> int:
    preset = PRESETS[args.preset]
    output_dir = Path(args.output_dir).resolve() if args.output_dir else _default_output_dir(preset.name).resolve()
    built_dir = _build_bundle(preset, output_dir, archive=args.archive)
    print(f"Prepared Hailo bundle: {built_dir}")
    if args.archive:
        print(f"Archive: {built_dir.with_suffix('.tar.gz')}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-presets", help="Show available Hailo compile presets.")

    build = subparsers.add_parser("build", help="Build one Hailo compile bundle.")
    build.add_argument("--preset", choices=sorted(PRESETS), required=True)
    build.add_argument("--output-dir", help="Override the bundle output directory.")
    build.add_argument("--archive", action="store_true", help="Also create a .tar.gz archive next to the bundle directory.")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "list-presets":
        return _list_presets()
    if args.command == "build":
        return _build_command(args)
    raise RuntimeError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
