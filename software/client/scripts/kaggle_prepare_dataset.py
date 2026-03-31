"""Prepare the LEGO chamber detection dataset for Kaggle upload."""
from __future__ import annotations
import json, shutil, os
from pathlib import Path
import cv2
from local_detector_dataset import (
    TRAINING_ROOT, collect_samples, split_samples,
    parse_segmentation_label, polygon_to_bbox,
)

CLIENT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = CLIENT_ROOT / "blob" / "kaggle_dataset"

def write_coco_json(path, samples, image_dir):
    image_dir.mkdir(parents=True, exist_ok=True)
    images, annotations = [], []
    ann_id = 1
    for img_id, sample in enumerate(samples, 1):
        img = cv2.imread(str(sample.image_path), cv2.IMREAD_COLOR)
        if img is None: continue
        h, w = img.shape[:2]
        ext = sample.image_path.suffix or ".jpg"
        fname = f"{sample.session_id}__{sample.sample_id}{ext}"
        dst = image_dir / fname
        if not dst.exists(): shutil.copy2(sample.image_path, dst)
        images.append({"id": img_id, "file_name": fname, "width": w, "height": h})
        for poly in parse_segmentation_label(sample.segmentation_label_path):
            xn, yn, xx, yx = polygon_to_bbox(poly)
            x, y, bw, bh = xn*w, yn*h, max(0,(xx-xn)*w), max(0,(yx-yn)*h)
            annotations.append({"id": ann_id, "image_id": img_id, "category_id": 1,
                              "bbox": [x,y,bw,bh], "area": bw*bh, "iscrowd": 0})
            ann_id += 1
    payload = {"images": images, "annotations": annotations,
               "categories": [{"id": 1, "name": "piece"}]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return len(images), len(annotations)

def main():
    if OUTPUT_DIR.exists(): shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    accepted, skipped = collect_samples(TRAINING_ROOT, limit=0, seed=42)
    if not accepted:
        raise SystemExit("No samples found")

    splits = split_samples(accepted, val_fraction=0.15, test_fraction=0.10, seed=42)

    for split_name, samples in splits.items():
        img_dir = OUTPUT_DIR / "images" / split_name
        ann_path = OUTPUT_DIR / "annotations" / f"{split_name}.json"
        n_img, n_ann = write_coco_json(ann_path, samples, img_dir)
        print(f"{split_name}: {n_img} images, {n_ann} annotations")

    # Kaggle dataset metadata
    metadata = {
        "title": "lego-chamber-detection",
        "id": "INSERT_USERNAME/lego-chamber-detection",
        "licenses": [{"name": "CC0-1.0"}]
    }
    (OUTPUT_DIR / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2))

    print(f"\nDataset ready at {OUTPUT_DIR}")
    print("Next: Set your username in dataset-metadata.json, then run:")
    print("  kaggle datasets create -p blob/kaggle_dataset/")

if __name__ == "__main__":
    main()
