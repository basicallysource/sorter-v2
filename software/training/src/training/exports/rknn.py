"""Prepare self-contained Rockchip RKNN compile bundles for our detector models.

Mirrors ``exports/hailo.py``: a *preset* points at a trained ONNX + a calibration
image directory; ``build`` packages everything (model, calibration subset,
convert script, README, manifest) into one self-contained directory that can be
copied to an x86_64 Linux host with ``rknn-toolkit2`` installed and compiled
in-place via ``./convert.sh``.

The actual ONNX → RKNN conversion runs on the host with the toolkit
(Python 3.8–3.11, x86_64 Linux only). This module does not invoke it; it just
produces the bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from dataclasses import dataclass, field
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
OUTPUT_ROOT = TRAINING_ROOT / "rknn_bundles"


@dataclass(frozen=True)
class RknnPreset:
    name: str
    label: str
    model_id: str
    model_family: str  # "yolo" | "nanodet"
    target_platform: str  # rk3588 / rk3568 / rk3576 / rk3562
    onnx_path: Path
    onnx_input_name: str
    onnx_input_shape: tuple[int, int, int, int]  # (N, C, H, W)
    classes: int
    default_conf: float
    default_iou: float
    calibration_dir: Path
    calibration_count: int
    quantization: str  # "i8" | "fp"
    # Mean/std applied INSIDE the RKNN graph (rknn config(mean_values=..., std_values=...)).
    # Layout matches the ONNX input order — typically RGB for our YOLO exports.
    mean_values: tuple[float, float, float] = (0.0, 0.0, 0.0)
    std_values: tuple[float, float, float] = (255.0, 255.0, 255.0)
    best_metrics: dict[str, float] = field(default_factory=dict)
    # Optional hint that the ONNX detect head was stripped (airockchip ultralytics fork).
    # Only affects README copy + how the runtime decodes outputs.
    head_stripped: bool = False


PRESETS: dict[str, RknnPreset] = {
    # Placeholder — gets filled once the first Lambda training run lands. Mirrors
    # the hailo preset entries; concrete run-id slot stays empty until the
    # `runs/<id>/exports/best.onnx` exists.
    "c_channel_yolo11n_320_rk3588": RknnPreset(
        name="c_channel_yolo11n_320_rk3588",
        label="C-Channel YOLO11n 320 -> RKNN (RK3588)",
        model_id="TBD-c-channel-yolo11n-320",
        model_family="yolo",
        target_platform="rk3588",
        onnx_path=RUNS_DIR / "TBD-c-channel-yolo11n-320" / "exports" / "best.onnx",
        onnx_input_name="images",
        onnx_input_shape=(1, 3, 320, 320),
        classes=1,
        default_conf=0.25,
        default_iou=0.45,
        calibration_dir=ZONE_DATASETS_DIR / "c_channel_full" / "train" / "images",
        calibration_count=150,
        quantization="i8",
        mean_values=(0.0, 0.0, 0.0),
        std_values=(255.0, 255.0, 255.0),
        head_stripped=False,
    ),
    # Target preset for the upcoming H100 build: yolo26s @ 320×320 → Orange Pi 5
    # (RK3588 NPU, int8). The May 14 head-to-head comparison had yolo26s 320 (A7)
    # ahead of yolo11s 320 (A5) on the harder metric:
    #   A7 yolo26s 320 → mAP50=0.9638, mAP50_95=0.8497, recall=0.9066
    #   A5 yolo11s 320 → mAP50=0.9618, mAP50_95=0.8367, recall=0.9050
    # Same exporter shape; both produce stock Ultralytics ONNX that RKNN-Toolkit2
    # ≥1.6 handles identically. The bigger lever this round is the ~6× larger,
    # machine-balanced dataset (5500 across 4 active rigs), not the architecture.
    #
    # After the H100 run finishes, update model_id + onnx_path + calibration_dir
    # to point at the actual run folder (e.g. "20260524-...-c_channel_full-yolo26s-320").
    "c_channel_full_yolo26s_320_rk3588": RknnPreset(
        name="c_channel_full_yolo26s_320_rk3588",
        label="C-Channel Full YOLO26s 320 → RKNN (Orange Pi 5 / RK3588)",
        # Resolved after the 20260524 H100 run completed (mAP50=0.948,
        # mAP50_95=0.839 on the v2 val set across all 4 active machines).
        model_id="20260524-c-channel-full-yolo26s-320",
        model_family="yolo",
        target_platform="rk3588",
        onnx_path=RUNS_DIR
            / "20260524-104900-c_channel_full-yolo-v2"
            / "A7-yolo26s-320"
            / "weights"
            / "best.onnx",
        onnx_input_name="images",
        onnx_input_shape=(1, 3, 320, 320),
        classes=1,
        default_conf=0.25,
        default_iou=0.45,
        calibration_dir=ZONE_DATASETS_DIR / "c_channel_full" / "v2" / "images" / "train",
        calibration_count=150,
        quantization="i8",
        mean_values=(0.0, 0.0, 0.0),
        std_values=(255.0, 255.0, 255.0),
        head_stripped=False,
    ),
}


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


def _validate_onnx(preset: RknnPreset) -> dict[str, Any]:
    model = onnx.load(str(preset.onnx_path))
    inputs: dict[str, list] = {}
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

    expected_shape = list(preset.onnx_input_shape)
    actual_shape = inputs.get(preset.onnx_input_name)
    if actual_shape != expected_shape:
        raise RuntimeError(
            f"Unexpected ONNX input for {preset.name}: expected {preset.onnx_input_name}={expected_shape}, got {actual_shape!r}"
        )

    outputs: dict[str, list] = {}
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

    return {
        "input_name": preset.onnx_input_name,
        "input_shape": actual_shape,
        "outputs": outputs,
        "sha256": _sha256(preset.onnx_path),
    }


def _copy_calibration_images(preset: RknnPreset, destination_dir: Path) -> list[str]:
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


def _make_dataset_txt(calibration_filenames: list[str]) -> str:
    """RKNN's quantizer resolves each line in dataset.txt RELATIVE to dataset.txt
    itself, not the bundle root. We place dataset.txt at calibration/dataset.txt
    next to calibration/images/, so the lines have to be ``images/<file>``."""
    return "\n".join(f"images/{name}" for name in calibration_filenames) + "\n"


def _make_convert_script(preset: RknnPreset) -> str:
    do_quant = "True" if preset.quantization == "i8" else "False"
    return f'''#!/usr/bin/env python3
"""Convert ONNX -> RKNN inside a bundle directory.

Run from a Linux x86_64 host with rknn-toolkit2 installed
(Python 3.8-3.11). Inputs/outputs are resolved relative to this file so the
bundle stays self-contained.

    cd <bundle>
    python convert.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from rknn.api import RKNN
except ModuleNotFoundError:
    sys.exit(
        "rknn-toolkit2 is not installed. Install it on an x86_64 Linux host with Python 3.8-3.11."
    )

BUNDLE = Path(__file__).resolve().parent
ONNX_PATH = BUNDLE / "model" / "model.onnx"
DATASET_TXT = BUNDLE / "calibration" / "dataset.txt"
OUT_RKNN = BUNDLE / "results" / "{preset.name}.rknn"
OUT_RKNN.parent.mkdir(parents=True, exist_ok=True)

MEAN = [{preset.mean_values[0]}, {preset.mean_values[1]}, {preset.mean_values[2]}]
STD = [{preset.std_values[0]}, {preset.std_values[1]}, {preset.std_values[2]}]

rknn = RKNN(verbose=True)

rknn.config(
    mean_values=[MEAN],
    std_values=[STD],
    target_platform="{preset.target_platform}",
    quantized_dtype="asymmetric_quantized-8" if {do_quant} else "float16",
    optimization_level=3,
)

if rknn.load_onnx(model=str(ONNX_PATH)) != 0:
    sys.exit("load_onnx failed")

if rknn.build(do_quantization={do_quant}, dataset=str(DATASET_TXT)) != 0:
    sys.exit("build failed")

if rknn.export_rknn(str(OUT_RKNN)) != 0:
    sys.exit("export_rknn failed")

print(f"Wrote {{OUT_RKNN}}")
rknn.release()
'''


def _make_compile_commands(preset: RknnPreset) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$BUNDLE_DIR"

# rknn-toolkit2 wants Python 3.8-3.11 on x86_64 Linux. Use the host's
# already-installed converter venv:
PY="${{PYTHON:-python3}}"

echo "Converting {preset.name} ({preset.target_platform}, quant={preset.quantization}) in $BUNDLE_DIR"
"$PY" "$BUNDLE_DIR/convert.py"

echo
echo "Expected output:"
echo "  $BUNDLE_DIR/results/{preset.name}.rknn"
"""


def _make_readme(preset: RknnPreset, bundle_dir: Path, calibration_count: int) -> str:
    head_note = (
        "ONNX **detect head removed** (airockchip ultralytics fork). The NPU runs the "
        "backbone + neck; the runtime on the Pi decodes raw feature maps on the CPU."
        if preset.head_stripped
        else "ONNX is a stock Ultralytics export — detect head is baked in. Expect slow / "
        "unsupported ops on the NPU. Re-export from `best.pt` with the airockchip "
        "ultralytics fork to get an NPU-friendly graph."
    )
    return f"""# {preset.label}

Self-contained RKNN compile bundle. Mirrors the layout of our Hailo bundles
(`software/training/hailo_bundles/`).

{head_note}

## Contents

- `model/model.onnx` — source ONNX export
- `calibration/images/` — {calibration_count} representative chamber/channel frames
- `calibration/dataset.txt` — paths list consumed by `rknn-toolkit2`'s `build(dataset=...)`
- `convert.py` — one-shot ONNX → RKNN converter (requires `rknn-toolkit2` on an x86_64 Linux host)
- `compile_commands.sh` — wrapper around `convert.py`
- `manifest.json` — full preset + onnx + calibration metadata

## Run

On a Linux x86_64 host with `rknn-toolkit2` installed (Python 3.8-3.11):

```bash
./compile_commands.sh
# → results/{preset.name}.rknn
```

## Reference expectations

- Target platform: `{preset.target_platform}`
- Quantization: `{preset.quantization}` ({"INT8 + asymmetric quantization with calibration set" if preset.quantization == "i8" else "FP16"})
- Classes: `{preset.classes}`
- Input shape: `{preset.onnx_input_shape}`
- Detection thresholds: `conf={preset.default_conf}`, `iou={preset.default_iou}`
- Calibration images in bundle: `{calibration_count}`

## Output path

The prepared bundle lives at:

`{bundle_dir}`
"""


def _build_bundle(preset: RknnPreset, output_dir: Path, archive: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    onnx_meta = _validate_onnx(preset)
    calibration_images = _copy_calibration_images(preset, output_dir / "calibration" / "images")
    (output_dir / "calibration" / "dataset.txt").write_text(_make_dataset_txt(calibration_images))

    _copy_file(preset.onnx_path, output_dir / "model" / "model.onnx")
    (output_dir / "convert.py").write_text(_make_convert_script(preset))
    (output_dir / "convert.py").chmod(0o755)
    compile_script_path = output_dir / "compile_commands.sh"
    compile_script_path.write_text(_make_compile_commands(preset))
    compile_script_path.chmod(0o755)
    (output_dir / "README.md").write_text(_make_readme(preset, output_dir, len(calibration_images)))

    manifest = {
        "preset": preset.name,
        "label": preset.label,
        "target_platform": preset.target_platform,
        "model_family": preset.model_family,
        "model_id": preset.model_id,
        "classes": preset.classes,
        "default_conf": preset.default_conf,
        "default_iou": preset.default_iou,
        "quantization": preset.quantization,
        "mean_values": list(preset.mean_values),
        "std_values": list(preset.std_values),
        "head_stripped": preset.head_stripped,
        "source_onnx": str(preset.onnx_path),
        "source_calibration_dir": str(preset.calibration_dir),
        "best_metrics": preset.best_metrics,
        "onnx": onnx_meta,
        "calibration": {
            "count": len(calibration_images),
            "images": calibration_images,
        },
        "artifacts": {
            "compile_script": "compile_commands.sh",
            "convert_script": "convert.py",
            "onnx": "model/model.onnx",
            "dataset_txt": "calibration/dataset.txt",
            "output_rknn": f"results/{preset.name}.rknn",
        },
    }
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
        print(f"  target={preset.target_platform}, quant={preset.quantization}")
    return 0


def _build_command(args: argparse.Namespace) -> int:
    preset = PRESETS[args.preset]
    output_dir = Path(args.output_dir).resolve() if args.output_dir else _default_output_dir(preset.name).resolve()
    built_dir = _build_bundle(preset, output_dir, archive=args.archive)
    print(f"Prepared RKNN bundle: {built_dir}")
    if args.archive:
        print(f"Archive: {built_dir.with_suffix('.tar.gz')}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-presets", help="Show available RKNN compile presets.")

    build = subparsers.add_parser("build", help="Build one RKNN compile bundle.")
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
