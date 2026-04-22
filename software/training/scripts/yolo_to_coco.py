#!/usr/bin/env python3
"""Convert a YOLO-format dataset (produced by `train build`) into COCO JSON
annotations that NanoDet / YOLOX expect.

Produces:
  <dataset>/annotations/train.json
  <dataset>/annotations/val.json

Single class "piece" (class_id=0 in YOLO labels, category_id=1 in COCO).

Usage:
  uv run python scripts/yolo_to_coco.py datasets/carousel/v1_diverse
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("pillow required: uv add pillow")


def convert_split(dataset: Path, split: str) -> dict:
    images_dir = dataset / "images" / split
    labels_dir = dataset / "labels" / split
    images = sorted(images_dir.glob("*.jpg")) + sorted(images_dir.glob("*.png"))

    coco = {
        "info": {"description": f"{dataset.name} {split}"},
        "licenses": [],
        "images": [],
        "annotations": [],
        "categories": [{"id": 1, "name": "piece", "supercategory": "piece"}],
    }

    ann_id = 1
    for img_id, img_path in enumerate(images, start=1):
        with Image.open(img_path) as im:
            w, h = im.size
        coco["images"].append({
            "id": img_id,
            "file_name": img_path.name,
            "width": w,
            "height": h,
        })
        label_path = labels_dir / (img_path.stem + ".txt")
        if not label_path.exists():
            continue
        for line in label_path.read_text().splitlines():
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            cls, cx, cy, bw, bh = parts
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


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: yolo_to_coco.py <dataset_dir>")
    dataset = Path(sys.argv[1]).resolve()
    if not (dataset / "images").is_dir() or not (dataset / "labels").is_dir():
        sys.exit(f"{dataset} missing images/ or labels/")
    ann_dir = dataset / "annotations"
    ann_dir.mkdir(exist_ok=True)
    for split in ("train", "val"):
        coco = convert_split(dataset, split)
        out = ann_dir / f"{split}.json"
        out.write_text(json.dumps(coco, indent=None))
        print(f"wrote {out}: {len(coco['images'])} images, {len(coco['annotations'])} anns")


if __name__ == "__main__":
    main()
