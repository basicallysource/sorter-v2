#!/usr/bin/env python3
"""Track B: Train RF-DETR detection models on GPU.

Models:
  B1: RF-DETR Nano @ 384
  B2: RF-DETR Small @ 384

Expects YOLO-format dataset at /workspace/dataset/ (images/{train,val}/,
labels/{train,val}/). Converts it to RF-DETR's COCO layout in-place and trains.

Usage: python rfdetr.py [--model-ids B1 B2]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

DATASET_YOLO = Path("/workspace/dataset")
DATASET_RFDETR = Path("/workspace/rfdetr_dataset")
RESULTS = Path("/workspace/results")
RESULTS.mkdir(exist_ok=True)

MODELS = [
    {"id": "B1", "name": "rfdetr-nano",  "klass": "RFDETRNano",  "batch": 8,  "grad_accum": 2},
    {"id": "B2", "name": "rfdetr-small", "klass": "RFDETRSmall", "batch": 4,  "grad_accum": 4},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-ids", nargs="+", default=None)
    parser.add_argument("--epochs", type=int, default=120)
    return parser.parse_args()


def select_models(models: list[dict], selected_ids: set[str]) -> list[dict]:
    if not selected_ids:
        return models
    return [m for m in models if m["id"] in selected_ids]


def setup() -> None:
    subprocess.run(
        [
            "bash", "-lc",
            "apt-get update && "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y "
            "libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1",
        ],
        check=True,
    )
    subprocess.run(["pip", "install", "-q", "rfdetr", "pillow", "pycocotools"], check=True)


def _yolo_to_coco_split(images_dir: Path, labels_dir: Path) -> dict:
    from PIL import Image

    coco = {
        "info": {"description": images_dir.parent.parent.name + "/" + images_dir.name},
        "licenses": [],
        "images": [],
        "annotations": [],
        "categories": [{"id": 1, "name": "piece", "supercategory": "piece"}],
    }
    images = sorted([p for p in images_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}])
    ann_id = 1
    for img_id, img_path in enumerate(images, start=1):
        with Image.open(img_path) as im:
            w, h = im.size
        coco["images"].append({"id": img_id, "file_name": img_path.name, "width": w, "height": h})
        label_path = labels_dir / (img_path.stem + ".txt")
        if not label_path.exists():
            continue
        for line in label_path.read_text().splitlines():
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            _cls, cx, cy, bw, bh = parts
            cx, cy, bw, bh = float(cx), float(cy), float(bw), float(bh)
            x = (cx - bw / 2) * w
            y = (cy - bh / 2) * h
            bw_px = bw * w
            bh_px = bh * h
            coco["annotations"].append({
                "id": ann_id,
                "image_id": img_id,
                "category_id": 1,
                "bbox": [round(x, 2), round(y, 2), round(bw_px, 2), round(bh_px, 2)],
                "area": round(bw_px * bh_px, 2),
                "iscrowd": 0,
            })
            ann_id += 1
    return coco


def convert_dataset() -> None:
    """YOLO-format → RF-DETR COCO layout (train/ + valid/ with _annotations.coco.json + images)."""
    if (DATASET_RFDETR / "train" / "_annotations.coco.json").exists():
        print(f"[rfdetr] dataset already converted at {DATASET_RFDETR}")
        return
    DATASET_RFDETR.mkdir(exist_ok=True)
    for yolo_split, rfd_split in [("train", "train"), ("val", "valid")]:
        src_img = DATASET_YOLO / "images" / yolo_split
        src_lbl = DATASET_YOLO / "labels" / yolo_split
        if not src_img.is_dir():
            raise SystemExit(f"missing {src_img}")
        dst = DATASET_RFDETR / rfd_split
        dst.mkdir(exist_ok=True)
        # symlink images so we don't double disk usage
        for p in src_img.iterdir():
            target = dst / p.name
            if target.exists() or target.is_symlink():
                continue
            target.symlink_to(p.resolve())
        coco = _yolo_to_coco_split(src_img, src_lbl)
        (dst / "_annotations.coco.json").write_text(json.dumps(coco))
        print(f"[rfdetr] {rfd_split}: {len(coco['images'])} images, {len(coco['annotations'])} anns")


def train_model(m: dict, epochs: int) -> dict:
    from rfdetr import RFDETRBase, RFDETRMedium, RFDETRLarge, RFDETRNano, RFDETRSmall  # noqa: F401

    klass_name = m["klass"]
    klass = {
        "RFDETRNano": RFDETRNano,
        "RFDETRSmall": RFDETRSmall,
        "RFDETRBase": RFDETRBase,
        "RFDETRMedium": RFDETRMedium,
        "RFDETRLarge": RFDETRLarge,
    }[klass_name]
    run_name = f"{m['id']}-{m['name']}"
    out_dir = Path("/workspace/runs") / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}\nTraining {run_name} ({klass_name})\n{'=' * 60}", flush=True)
    t0 = time.time()
    result: dict = {"id": m["id"], "name": m["name"], "klass": klass_name}
    try:
        model = klass()
        model.train(
            dataset_dir=str(DATASET_RFDETR),
            epochs=epochs,
            batch_size=m["batch"],
            grad_accum_steps=m["grad_accum"],
            lr=1e-4,
            output_dir=str(out_dir),
        )
        result["train_elapsed_min"] = round((time.time() - t0) / 60, 1)

        # Find best checkpoint
        cand = sorted(out_dir.glob("**/checkpoint_best*.pth")) + sorted(out_dir.glob("**/best*.pth"))
        if not cand:
            cand = sorted(out_dir.glob("**/*.pth"))
        weights = cand[-1] if cand else None
        if weights is None:
            result["error"] = "no weights found"
            return result

        # Try ONNX export via the model's export method
        try:
            print(f"\nExporting {m['id']} to ONNX...", flush=True)
            model.export()
            # rf-detr usually writes to output/ subdir; try to find ONNX
            onnx_candidates = sorted(out_dir.glob("**/*.onnx"))
            if onnx_candidates:
                shutil.copy2(onnx_candidates[-1], RESULTS / f"{run_name}-best.onnx")
                result["onnx_exported"] = True
        except Exception as exc:
            result["onnx_error"] = str(exc)[:200]

        # Always keep the .pth
        shutil.copy2(weights, RESULTS / f"{run_name}-best.pth")
        result["weights_size_kb"] = round(weights.stat().st_size / 1024, 1)

        # Read metrics file (rfdetr writes log.txt + eval metrics)
        metrics_path = next(out_dir.glob("**/results.json"), None)
        if metrics_path:
            try:
                result["best_metrics"] = json.loads(metrics_path.read_text())
            except Exception:
                pass

    except Exception as exc:
        result["error"] = f"{exc}\n{traceback.format_exc()[:1500]}"
        result["train_elapsed_min"] = round((time.time() - t0) / 60, 1)

    print(f"\n{m['id']} done: {result.get('train_elapsed_min', '?')} min", flush=True)
    if "error" in result:
        print(f"  ERROR: {result['error'][:200]}", flush=True)
    return result


def main() -> None:
    args = parse_args()
    selected = {x.strip().upper() for x in (args.model_ids or []) if x.strip()}
    models = select_models(MODELS, selected)

    print("=" * 60)
    print("Track B: RF-DETR Models")
    print("=" * 60)

    setup()
    convert_dataset()

    results: dict[str, dict] = {}
    for m in models:
        results[m["id"]] = train_model(m, args.epochs)

    summary = RESULTS / "track_b_results.json"
    summary.write_text(json.dumps(results, indent=2))

    print(f"\n{'=' * 60}\nTrack B Complete\n{'=' * 60}")
    print(f"Results saved to: {summary}")
    for mid, r in results.items():
        status = "OK" if "error" not in r else "FAILED"
        print(f"  {mid} ({r['name']}): {status} - {r.get('train_elapsed_min', '?')} min")


if __name__ == "__main__":
    main()
