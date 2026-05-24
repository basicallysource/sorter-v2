"""Train a YOLO detector and export an NPU-friendly ONNX.

Designed to run on a Lambda Labs box inside the project uv venv (Python 3.11):

    cd software/training && uv run python scripts/lambda/train_export.py ...

The export step monkeypatches Ultralytics' `Detect.forward` to return raw
feature maps (no DFL decode, no sigmoid, no anchor math) so the resulting ONNX
is friendly to the RK3588 NPU. Decode runs CPU-side on the Pi at inference.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


YOLO_MODELS: dict[str, dict] = {
    "A1": {"name": "yolo26n-320", "model": "yolo26n.pt", "imgsz": 320, "batch": 64},
    "A2": {"name": "yolo26n-416", "model": "yolo26n.pt", "imgsz": 416, "batch": 48},
    "A3": {"name": "yolo11n-320", "model": "yolo11n.pt", "imgsz": 320, "batch": 64},
    "A4": {"name": "yolo11n-416", "model": "yolo11n.pt", "imgsz": 416, "batch": 48},
    "A5": {"name": "yolo11s-320", "model": "yolo11s.pt", "imgsz": 320, "batch": 32},
    "A6": {"name": "yolov8n-320", "model": "yolov8n.pt", "imgsz": 320, "batch": 64},
    "A7": {"name": "yolo26s-320", "model": "yolo26s.pt", "imgsz": 320, "batch": 32},
    "A8": {"name": "yolo26s-416", "model": "yolo26s.pt", "imgsz": 416, "batch": 24},
}


def _patchedDetectForward() -> None:
    import ultralytics.nn.modules.head as head_mod

    def _stripped(self, x):
        # Apply box (cv2) and cls (cv3) convolutions per scale, returning
        # [B, 4*reg_max+nc, H, W] per scale — DFL/anchor/sigmoid stripped.
        # The raw neck features (what `return x` alone would give) are NOT
        # decodable; we must keep cv2+cv3 so Pi-side DFL decode can work.
        for i in range(self.nl):
            x[i] = __import__("torch").cat((self.cv2[i](x[i]), self.cv3[i](x[i])), 1)
        return x

    head_mod.Detect.forward = _stripped


def _verifyHeadStrippedOnnx(onnx_path: Path) -> dict:
    import onnx

    model = onnx.load(str(onnx_path))
    outs = []
    for o in model.graph.output:
        dims = [d.dim_value or d.dim_param or "?" for d in o.type.tensor_type.shape.dim]
        outs.append({"name": o.name, "shape": dims})
    if len(outs) != 3:
        raise RuntimeError(
            f"Head-stripped ONNX should have 3 outputs, got {len(outs)}: {outs}"
        )
    return {"outputs": outs, "num_outputs": 3, "head_stripped": True}


def _resolveModelSpec(model_id: str) -> dict:
    key = model_id.strip().upper()
    if key not in YOLO_MODELS:
        raise SystemExit(f"Unknown model id {model_id!r}. Available: {sorted(YOLO_MODELS)}")
    return YOLO_MODELS[key]


def _applyRelu6() -> None:
    import torch.nn as nn
    import ultralytics.nn.modules.conv as conv_mod

    conv_mod.Conv.default_act = nn.ReLU6()


def _trainOne(
    spec: dict,
    data_yaml: Path,
    project: Path,
    run_name: str,
    epochs: int,
    workers: int,
    cache: bool,
    head_stripped: bool,
    activation: str = "silu",
) -> dict:
    from ultralytics import YOLO

    t0 = time.time()
    model_src = spec["model"]
    if activation == "relu6":
        # ReLU6 must be set before the model is instantiated. Use the .yaml
        # architecture (no pretrained weights) so the activations are consistent
        # from the very first forward pass; loading a SiLU-pretrained .pt and
        # then changing the activation mid-flight wrecks the learned features.
        _applyRelu6()
        model_src = model_src.replace(".pt", ".yaml")
        print(f"[relu6] Conv.default_act = ReLU6, training from scratch ({model_src})")
    print(f"[train] model={model_src} imgsz={spec['imgsz']} batch={spec['batch']} epochs={epochs}")
    model = YOLO(model_src)
    model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=spec["imgsz"],
        batch=spec["batch"],
        device=0,
        project=str(project),
        name=run_name,
        cache=cache,
        workers=workers,
        patience=max(10, epochs // 6),
        verbose=True,
    )
    train_minutes = round((time.time() - t0) / 60, 2)

    best_pt = project / run_name / "weights" / "best.pt"
    if not best_pt.exists():
        raise RuntimeError(f"best.pt missing after train: {best_pt}")

    print(f"[export] head_stripped={head_stripped} onnx imgsz={spec['imgsz']}")
    if head_stripped:
        _patchedDetectForward()

    export_model = YOLO(str(best_pt))
    onnx_path_str = export_model.export(
        format="onnx",
        imgsz=spec["imgsz"],
        simplify=True,
        opset=12,
    )
    onnx_path = Path(onnx_path_str)
    if not onnx_path.exists():
        raise RuntimeError(f"ONNX export missing: {onnx_path}")

    onnx_meta: dict = {"path": str(onnx_path), "size_bytes": onnx_path.stat().st_size}
    if head_stripped:
        onnx_meta.update(_verifyHeadStrippedOnnx(onnx_path))

    return {
        "model_id_spec": spec,
        "activation": activation,
        "best_pt": str(best_pt),
        "best_onnx": str(onnx_path),
        "train_minutes": train_minutes,
        "onnx": onnx_meta,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-yaml", required=True, help="Path to dataset.yaml")
    parser.add_argument("--project-dir", required=True, help="Ultralytics 'project' dir (parent of run_name/)")
    parser.add_argument("--run-name", required=True, help="Ultralytics run name (subdir under project-dir)")
    parser.add_argument("--model-id", required=True, help="One of A1..A8 (see YOLO_MODELS)")
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--cache", action="store_true", help="Cache images in RAM (Ultralytics cache=True)")
    parser.add_argument(
        "--no-head-strip",
        action="store_true",
        help="Disable the Detect.forward monkeypatch (export stock Ultralytics ONNX).",
    )
    parser.add_argument(
        "--activation",
        choices=["silu", "relu6"],
        default="silu",
        help="Activation function. relu6 trains from scratch (no pretrained weights) with ReLU6.",
    )
    parser.add_argument("--result-json", required=True, help="Where to dump result metadata")
    args = parser.parse_args()

    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    spec = _resolveModelSpec(args.model_id)
    result = _trainOne(
        spec=spec,
        data_yaml=Path(args.data_yaml),
        project=Path(args.project_dir),
        run_name=args.run_name,
        epochs=args.epochs,
        workers=args.workers,
        cache=args.cache,
        head_stripped=not args.no_head_strip,
        activation=args.activation,
    )

    Path(args.result_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.result_json).write_text(json.dumps(result, indent=2) + "\n")
    print(f"[done] wrote {args.result_json}")


if __name__ == "__main__":
    main()
