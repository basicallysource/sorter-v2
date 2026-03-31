#!/usr/bin/env python3
"""Track A: Train 6 Ultralytics YOLO models on GPU.

Models:
  A1: YOLOv26n @ 320  (newest architecture)
  A2: YOLOv26n @ 416
  A3: YOLOv11n @ 320
  A4: YOLOv11n @ 416
  A5: YOLOv11s @ 320  (small variant, higher accuracy)
  A6: YOLOv8n  @ 320  (baseline)

Runs on Vast.ai with: pip install ultralytics
Expects dataset at /workspace/dataset/ with dataset.yaml + images/ + labels_yolo/

Usage: python vastai_track_a.py
"""
import argparse
import subprocess
import json
import time
import os
import csv
import glob
import shutil
import traceback
from pathlib import Path

DATASET = "/workspace/dataset"
RESULTS = Path("/workspace/results")
RESULTS.mkdir(exist_ok=True)

MODELS = [
    {"id": "A1", "name": "yolo26n-320",  "model": "yolo26n.pt",  "imgsz": 320, "batch": 64},
    {"id": "A2", "name": "yolo26n-416",  "model": "yolo26n.pt",  "imgsz": 416, "batch": 48},
    {"id": "A3", "name": "yolo11n-320",  "model": "yolo11n.pt",  "imgsz": 320, "batch": 64},
    {"id": "A4", "name": "yolo11n-416",  "model": "yolo11n.pt",  "imgsz": 416, "batch": 48},
    {"id": "A5", "name": "yolo11s-320",  "model": "yolo11s.pt",  "imgsz": 320, "batch": 32},
    {"id": "A6", "name": "yolov8n-320",  "model": "yolov8n.pt",  "imgsz": 320, "batch": 64},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-ids", nargs="+", default=None, help="Optional specific model IDs to run.")
    return parser.parse_args()


def select_models(models: list[dict], selected_ids: set[str]) -> list[dict]:
    if not selected_ids:
        return models
    return [model for model in models if model["id"] in selected_ids]


def setup():
    """Install dependencies."""
    # Ultralytics pulls OpenCV, which needs a few shared libs in the base image.
    subprocess.run(
        [
            "bash",
            "-lc",
            "apt-get update && "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y "
            "libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1",
        ],
        check=True,
    )
    subprocess.run(["pip", "install", "-q", "ultralytics"], check=True)
    subprocess.run(
        ["pip", "uninstall", "-y", "opencv-python", "opencv-contrib-python"],
        check=False,
    )
    subprocess.run(
        ["pip", "install", "-q", "--force-reinstall", "numpy<2", "opencv-python-headless"],
        check=True,
    )

    # Symlink YOLO labels into the expected location for Ultralytics
    # Ultralytics expects labels/ next to images/ with matching structure
    src = Path(DATASET) / "labels_yolo"
    dst = Path(DATASET) / "labels"
    if src.exists() and not dst.exists():
        dst.symlink_to(src)
        print(f"Symlinked {dst} -> {src}")


def train_model(m: dict) -> dict:
    """Train a single YOLO model and return results."""
    model_id = m["id"]
    model_name = m["name"]
    run_name = f"{model_id}-{model_name}"

    print(f"\n{'=' * 60}")
    print(f"Training {model_id}: {model_name}")
    print(f"{'=' * 60}")

    t0 = time.time()
    result = {"name": model_name, "model": m["model"], "imgsz": m["imgsz"]}

    try:
        # Train
        cmd = [
            "yolo", "detect", "train",
            f"model={m['model']}",
            f"data={DATASET}/dataset.yaml",
            "epochs=300",
            f"imgsz={m['imgsz']}",
            f"batch={m['batch']}",
            "device=0",
            "cache=True",
            "workers=8",
            "patience=50",
            f"project=/workspace/runs",
            f"name={run_name}",
        ]
        r = subprocess.run(cmd, capture_output=False)
        result["train_returncode"] = r.returncode
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)

        weights = f"/workspace/runs/{run_name}/weights/best.pt"

        # Export to NCNN
        if os.path.exists(weights):
            print(f"\nExporting {model_id} to NCNN...")
            e = subprocess.run(
                ["yolo", "export", f"model={weights}", "format=ncnn", "half=True"],
                capture_output=False,
            )
            result["ncnn_export_rc"] = e.returncode

            print(f"Exporting {model_id} to ONNX...")
            e = subprocess.run(
                ["yolo", "export", f"model={weights}", "format=onnx",
                 f"imgsz={m['imgsz']}", "simplify=True"],
                capture_output=False,
            )
            result["onnx_export_rc"] = e.returncode
        else:
            result["error"] = "best.pt not found after training"

        # Read training metrics from results.csv
        results_csv = f"/workspace/runs/{run_name}/results.csv"
        if os.path.exists(results_csv):
            rows = list(csv.DictReader(open(results_csv)))
            if rows:
                # Strip whitespace from keys (Ultralytics adds spaces)
                rows = [{k.strip(): v for k, v in row.items()} for row in rows]
                best = max(rows, key=lambda r: float(r.get("metrics/mAP50(B)", 0)))
                result["best_metrics"] = {
                    "epoch": int(float(best.get("epoch", 0))),
                    "mAP50": float(best.get("metrics/mAP50(B)", 0)),
                    "mAP50_95": float(best.get("metrics/mAP50-95(B)", 0)),
                    "precision": float(best.get("metrics/precision(B)", 0)),
                    "recall": float(best.get("metrics/recall(B)", 0)),
                }
                result["total_epochs"] = len(rows)

        # Copy artifacts to results
        for ext_name in ["best.pt", "best.onnx"]:
            src = f"/workspace/runs/{run_name}/weights/{ext_name}"
            if os.path.exists(src):
                dst = RESULTS / f"{run_name}-{ext_name}"
                shutil.copy2(src, dst)
                result[f"{ext_name}_size_kb"] = round(os.path.getsize(src) / 1024, 1)

        ncnn_dir = f"/workspace/runs/{run_name}/weights/best_ncnn_model"
        if os.path.isdir(ncnn_dir):
            dst = RESULTS / f"{run_name}-ncnn"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(ncnn_dir, dst)
            result["ncnn_exported"] = True

    except Exception as exc:
        result["error"] = f"{exc}\n{traceback.format_exc()}"
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)

    print(f"\n{model_id} done: {result.get('train_elapsed_min', '?')} min")
    if "best_metrics" in result:
        print(f"  Best metrics: {json.dumps(result['best_metrics'])}")
    if "error" in result:
        print(f"  ERROR: {result['error'][:200]}")

    return result


def main():
    args = parse_args()
    selected_ids = {model_id.strip().upper() for model_id in (args.model_ids or []) if model_id.strip()}
    models = select_models(MODELS, selected_ids)

    print("=" * 60)
    print("Track A: Ultralytics YOLO Models")
    print("=" * 60)

    setup()

    results = {}
    for m in models:
        results[m["id"]] = train_model(m)

    # Write summary
    summary_path = RESULTS / "track_a_results.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n\n{'=' * 60}")
    print("Track A Complete")
    print(f"{'=' * 60}")
    print(f"Results saved to: {summary_path}")
    for mid, r in results.items():
        status = "OK" if "error" not in r else "FAILED"
        metrics = r.get("best_metrics", {})
        mAP = metrics.get("mAP50", "N/A")
        print(f"  {mid} ({r['name']}): {status} - mAP50={mAP} - {r.get('train_elapsed_min', '?')} min")


if __name__ == "__main__":
    main()
