"""Evaluate the deployed Bronze model (c-channel-yolo26s-320-v2)
against the human-accepted samples on live Hive.

Reads from ``datasets/c_channel_full/raw/<id>/`` (must be freshly
pulled with ``train pull --status accepted``), keeps only the rows
whose metadata says ``review_status == 'accepted'``, builds a tiny
YOLO val dataset, runs Ultralytics ``val()`` and prints the headline
metrics next to the training-time numbers from the publish manifest.

Why: the original training labels came from Gemini-SAM with no human
QA — there's likely noise in the val set the model was scored
against. Re-scoring against the human-validated set tells us what the
model actually delivers.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import cv2
from ultralytics import YOLO


REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "training" / "datasets" / "c_channel_full" / "raw"
EVAL_DIR = REPO / "training" / "runs" / "eval-bronze-vs-accepted"
MODEL_PT = REPO / "training" / "runs" / "publish-A7-yolo26s-320-v2-20260524" / "exports" / "best.pt"
# Bronze was trained on this dataset — when --holdout-only is passed we
# drop any accepted sample whose id appears here so the eval is a clean
# held-out set, not a re-test of memorised images.
BRONZE_DATASET = REPO / "training" / "datasets" / "c_channel_full" / "v2"


def load_bronze_seen_ids() -> set[str]:
    """Return the set of sample IDs Bronze saw at training time.

    The published v2 dataset stores both train/ and val/ images under
    images/<split>/<sample_id>.jpg, so the basenames give us the
    sample-id universe directly.
    """
    seen: set[str] = set()
    for split in ("train", "val"):
        d = BRONZE_DATASET / "images" / split
        if not d.exists():
            continue
        for p in d.iterdir():
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                seen.add(p.stem)
    return seen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--holdout-only",
        action="store_true",
        help="Exclude samples Bronze already saw in train+val (clean hold-out eval).",
    )
    args = parser.parse_args()

    if not MODEL_PT.exists():
        raise SystemExit(f"Bronze weights missing: {MODEL_PT}")
    if not RAW.exists():
        raise SystemExit(f"Pulled samples missing: {RAW}")

    bronze_seen = load_bronze_seen_ids() if args.holdout_only else set()
    if args.holdout_only:
        print(f"hold-out mode: excluding {len(bronze_seen)} samples Bronze saw in train+val")

    images_dir = EVAL_DIR / "images" / "val"
    labels_dir = EVAL_DIR / "labels" / "val"
    if EVAL_DIR.exists():
        shutil.rmtree(EVAL_DIR)
    images_dir.mkdir(parents=True)
    labels_dir.mkdir(parents=True)

    n_accepted = 0
    n_missing_image = 0
    n_no_boxes = 0
    n_box_total = 0
    n_excluded_seen = 0
    for d in sorted(RAW.iterdir()):
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        if meta.get("review_status") != "accepted":
            continue
        if args.holdout_only and d.name in bronze_seen:
            n_excluded_seen += 1
            continue
        img_path = d / "image.jpg"
        if not img_path.exists():
            n_missing_image += 1
            continue

        # Read image dims directly — the metadata field is often null.
        img = cv2.imread(str(img_path))
        if img is None:
            n_missing_image += 1
            continue
        h, w = img.shape[:2]

        bboxes = meta.get("detection_bboxes") or []
        # Convert pixel xyxy → YOLO cx,cy,w,h normalised.
        lines: list[str] = []
        for bb in bboxes:
            if not isinstance(bb, list) or len(bb) < 4:
                continue
            x1, y1, x2, y2 = bb[:4]
            x1 = max(0.0, min(float(x1), w))
            y1 = max(0.0, min(float(y1), h))
            x2 = max(0.0, min(float(x2), w))
            y2 = max(0.0, min(float(y2), h))
            bw = x2 - x1
            bh = y2 - y1
            if bw <= 1 or bh <= 1:
                continue
            cx = (x1 + x2) / 2.0 / w
            cy = (y1 + y2) / 2.0 / h
            lines.append(f"0 {cx:.6f} {cy:.6f} {bw / w:.6f} {bh / h:.6f}")

        if not lines:
            n_no_boxes += 1
            # Accepted-empty frames are still valid val signal (negative samples).
            # Ultralytics treats an empty label file as "no objects expected".

        n_accepted += 1
        n_box_total += len(lines)
        # Symlink the image (cheap, doesn't copy gigabytes).
        link = images_dir / f"{d.name}.jpg"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(img_path.resolve())
        (labels_dir / f"{d.name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))

    print(f"accepted samples: {n_accepted}")
    if args.holdout_only:
        print(f"  excluded (Bronze had seen): {n_excluded_seen}")
    print(f"  with 0 boxes (legit empty frames): {n_no_boxes}")
    print(f"  total ground-truth boxes: {n_box_total}")
    print(f"  missing/unreadable images: {n_missing_image}")

    data_yaml = EVAL_DIR / "data.yaml"
    data_yaml.write_text(
        f"path: {EVAL_DIR}\n"
        f"train: images/val\n"
        f"val: images/val\n"
        f"nc: 1\n"
        f"names: [lego_piece]\n"
    )

    print(f"\nRunning Bronze inference on {n_accepted} samples...")
    model = YOLO(str(MODEL_PT))
    metrics = model.val(
        data=str(data_yaml),
        imgsz=320,
        batch=32,
        conf=0.25,
        iou=0.6,
        max_det=300,
        device="cpu",
        verbose=False,
        save=False,
        plots=False,
        project=str(EVAL_DIR),
        name="results",
        exist_ok=True,
    )

    # Pull the headline scalars.
    box = metrics.box
    print()
    print("Bronze vs. accepted (human-validated) samples:")
    print(f"  mAP50      : {float(box.map50):.4f}")
    print(f"  mAP50-95   : {float(box.map):.4f}")
    print(f"  Precision  : {float(box.mp):.4f}")
    print(f"  Recall     : {float(box.mr):.4f}")
    print()

    # Compare with the model's reported training-time best metrics.
    publish_run = MODEL_PT.parents[1] / "run.json"
    if publish_run.exists():
        run = json.loads(publish_run.read_text())
        training_meta = run.get("training_metadata") or {}
        bm = (training_meta.get("model") or {}).get("best_metrics") or {}
        if bm:
            print("Bronze training-time (Gemini-SAM val set):")
            for k in ("mAP50", "mAP50_95", "precision", "recall"):
                v = bm.get(k)
                if isinstance(v, (int, float)):
                    print(f"  {k:<11}: {v:.4f}")
            print()
            print("Delta (accepted - training):")
            mapping = {"mAP50": float(box.map50), "mAP50_95": float(box.map),
                       "precision": float(box.mp), "recall": float(box.mr)}
            for k, v_new in mapping.items():
                v_old = bm.get(k)
                if isinstance(v_old, (int, float)):
                    delta = v_new - v_old
                    sign = "+" if delta >= 0 else ""
                    print(f"  {k:<11}: {sign}{delta:.4f}")


if __name__ == "__main__":
    main()
