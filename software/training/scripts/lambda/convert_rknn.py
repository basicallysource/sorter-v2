"""Convert an ONNX to a quantized .rknn for RK3588 (low-level helper).

Designed to run inside the rknn-toolkit2 sidecar venv (Python 3.10) — NOT the
project uv venv. On the canonical Lambda box that's `/lambda/nfs/one/sorter-npu/rknn-venv/`.

WARNING — do not use ``--quantization i8`` on a *fused* YOLO ONNX (the standard
training export, output ``(1, 300, 6)`` or ``(1, 5, N)``). i8 quantizes that
output tensor per-tensor; the box coords (0..imgsz) dominate the single scale
and the confidence scores (0..1) collapse to exactly 0 — the NPU returns boxes
but zero scores, so nothing is ever detected. This silently broke Aqua, Bronze
and Cherry.

For YOLO, the canonical, correct path is ``software/training/rknn_builder/``
(``./build.sh best.pt out.rknn``), which runs ultralytics' official RKNN export:
it re-exports the model with the end2end branch disabled (so the head emits a
plain ``(1, 5, N)`` the sorter decodes via ``vision.ml.base.decode_yolo``) and
builds **fp16** (``do_quantization=False``) so the scores survive. i8 is only
safe with a true head-stripped ONNX (raw conv logits), decoded on the CPU via
``decode_yolo_head_stripped``.

i8 here uses per-channel weights + a calibration set of `n` frames; fp16 needs
no calibration. Mean/std are baked into the graph (0/255) so input tensors stay
in the 0..255 byte range coming off the Pi-side preprocess.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _writeDatasetTxt(calibration_dir: Path, count: int, dataset_txt: Path) -> int:
    images = sorted(
        p
        for p in calibration_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not images:
        raise SystemExit(f"No calibration images in {calibration_dir}")
    picked = images[:count]
    dataset_txt.write_text("\n".join(str(p.resolve()) for p in picked) + "\n")
    return len(picked)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", required=True, help="Head-stripped ONNX path")
    parser.add_argument("--calibration-dir", required=True, help="Dir of calibration JPGs")
    parser.add_argument("--calibration-count", type=int, default=150)
    parser.add_argument("--target-platform", default="rk3588")
    parser.add_argument("--quantization", choices=["i8", "fp"], default="i8")
    parser.add_argument("--output-rknn", required=True, help="Where to write .rknn")
    parser.add_argument("--result-json", required=True, help="Where to dump conversion metadata")
    args = parser.parse_args()

    try:
        from rknn.api import RKNN
    except ModuleNotFoundError:
        sys.exit("rknn-toolkit2 is not installed in this venv")

    onnx_path = Path(args.onnx).resolve()
    if not onnx_path.exists():
        sys.exit(f"ONNX missing: {onnx_path}")

    calibration_dir = Path(args.calibration_dir).resolve()
    output_rknn = Path(args.output_rknn).resolve()
    output_rknn.parent.mkdir(parents=True, exist_ok=True)

    dataset_txt = output_rknn.parent / "calibration_dataset.txt"
    used_count = _writeDatasetTxt(calibration_dir, args.calibration_count, dataset_txt)
    print(f"[calibration] {used_count} images from {calibration_dir}")

    do_quant = args.quantization == "i8"
    rknn = RKNN(verbose=False)
    rknn.config(
        mean_values=[[0, 0, 0]],
        std_values=[[255, 255, 255]],
        target_platform=args.target_platform,
        quantized_dtype="asymmetric_quantized-8" if do_quant else "float16",
        optimization_level=3,
    )

    if rknn.load_onnx(model=str(onnx_path)) != 0:
        sys.exit("load_onnx failed")
    if rknn.build(do_quantization=do_quant, dataset=str(dataset_txt)) != 0:
        sys.exit("build failed")
    if rknn.export_rknn(str(output_rknn)) != 0:
        sys.exit("export_rknn failed")
    rknn.release()

    size_bytes = output_rknn.stat().st_size
    result = {
        "onnx": str(onnx_path),
        "onnx_size_bytes": onnx_path.stat().st_size,
        "calibration_dir": str(calibration_dir),
        "calibration_used": used_count,
        "calibration_dataset_txt": str(dataset_txt),
        "target_platform": args.target_platform,
        "quantization": args.quantization,
        "rknn_path": str(output_rknn),
        "rknn_size_bytes": size_bytes,
    }
    Path(args.result_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.result_json).write_text(json.dumps(result, indent=2) + "\n")
    print(f"[done] {output_rknn} ({size_bytes} bytes); meta -> {args.result_json}")


if __name__ == "__main__":
    main()
