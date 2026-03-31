"""Train a NanoDet-Plus detector on classification-chamber samples.

This script:
1. Prepares a COCO JSON dataset from the existing pseudo-labeled samples
2. Clones nanodet (if needed) and installs it in an isolated venv
3. Generates a training config YAML
4. Runs training via subprocess
5. Exports to ONNX
6. Evaluates the ONNX model with consistent metrics

Usage:
    uv run python scripts/train_nanodet_detector.py \\
        --variant plus-m --imgsz 320 --epochs 200 --name "nanodet-plus-m-320"

Variants: plus-m, plus-m-1.5x
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from local_detector_dataset import (
    TRAINING_ROOT,
    PreparedSample,
    collect_samples,
    dataset_stats,
    parse_segmentation_label,
    polygon_to_bbox,
    prepare_run_dir,
    split_samples,
)


CLIENT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = CLIENT_ROOT / "blob" / "local_detection_models"
NANODET_REPO = "https://github.com/RangiLyu/nanodet.git"
NANODET_DIR = CLIENT_ROOT / "blob" / "nanodet_repo"
NANODET_VENV = CLIENT_ROOT / "blob" / "nanodet_venv"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a NanoDet-Plus detector on classification-chamber samples."
    )
    parser.add_argument("--training-root", default=str(TRAINING_ROOT))
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    parser.add_argument("--name", default="nanodet-plus-m-320-benchmark")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--test-fraction", type=float, default=0.10)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--variant",
        choices=("plus-m", "plus-m-1.5x"),
        default="plus-m",
        help="NanoDet model variant.",
    )
    parser.add_argument("--imgsz", type=int, default=320, help="Input image size (320 or 416).")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--skip-venv-setup", action="store_true", help="Skip nanodet venv creation (use if already set up).")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold for evaluation.")
    parser.add_argument("--iou-threshold", type=float, default=0.45, help="NMS IoU threshold for evaluation.")
    args = parser.parse_args()
    if args.val_fraction < 0 or args.test_fraction < 0:
        parser.error("Split fractions must be non-negative.")
    if (args.val_fraction + args.test_fraction) >= 1.0:
        parser.error("Validation + test fraction must be below 1.0.")
    return args


def _write_coco_json(
    path: Path,
    samples: list[PreparedSample],
    image_dir: Path,
) -> dict[str, Any]:
    """Write COCO JSON annotations and copy images to image_dir."""
    image_dir.mkdir(parents=True, exist_ok=True)
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    ann_id = 1

    for img_id, sample in enumerate(samples, start=1):
        image = cv2.imread(str(sample.image_path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        height, width = image.shape[:2]
        ext = sample.image_path.suffix or ".jpg"
        filename = f"{sample.session_id}__{sample.sample_id}{ext}"
        dst = image_dir / filename
        if not dst.exists():
            shutil.copy2(sample.image_path, dst)

        images.append({
            "id": img_id,
            "file_name": filename,
            "width": width,
            "height": height,
        })

        polygons = parse_segmentation_label(sample.segmentation_label_path)
        for polygon in polygons:
            x_min_n, y_min_n, x_max_n, y_max_n = polygon_to_bbox(polygon)
            x = x_min_n * width
            y = y_min_n * height
            w = max(0.0, (x_max_n - x_min_n) * width)
            h = max(0.0, (y_max_n - y_min_n) * height)
            annotations.append({
                "id": ann_id,
                "image_id": img_id,
                "category_id": 1,
                "bbox": [x, y, w, h],
                "area": w * h,
                "iscrowd": 0,
            })
            ann_id += 1

    payload = {
        "images": images,
        "annotations": annotations,
        "categories": [{"id": 1, "name": "piece"}],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return {
        "path": str(path),
        "image_count": len(images),
        "annotation_count": len(annotations),
    }


def _prepare_dataset(
    run_dir: Path,
    splits: dict[str, list[PreparedSample]],
) -> dict[str, Any]:
    """Prepare COCO JSON dataset for NanoDet."""
    dataset_root = run_dir / "dataset"
    train_img_dir = dataset_root / "images" / "train"
    val_img_dir = dataset_root / "images" / "val"
    test_img_dir = dataset_root / "images" / "test"

    train_ann = _write_coco_json(
        dataset_root / "annotations" / "train.json",
        splits["train"],
        train_img_dir,
    )
    val_ann = _write_coco_json(
        dataset_root / "annotations" / "val.json",
        splits["val"],
        val_img_dir,
    )
    test_ann = _write_coco_json(
        dataset_root / "annotations" / "test.json",
        splits["test"],
        test_img_dir,
    )

    return {
        "dataset_root": str(dataset_root),
        "train": train_ann,
        "val": val_ann,
        "test": test_ann,
        "train_images": str(train_img_dir),
        "val_images": str(val_img_dir),
        "test_images": str(test_img_dir),
    }


def _generate_nanodet_config(
    config_path: Path,
    *,
    variant: str,
    imgsz: int,
    num_classes: int,
    train_img_dir: str,
    train_ann_path: str,
    val_img_dir: str,
    val_ann_path: str,
    epochs: int,
    batch_size: int,
    lr: float,
    workers: int,
    save_dir: str,
) -> None:
    """Generate a NanoDet-Plus training config YAML.

    Follows the official nanodet-plus-m_320.yml / nanodet-plus-m-1.5x_320.yml
    reference configs as closely as possible.
    """
    if variant == "plus-m":
        model_size = "1.0x"
        fpn_in_channels = [116, 232, 464]
        fpn_out_channels = 96
        aux_in_channel = 192
        aux_feat_channels = 192
    elif variant == "plus-m-1.5x":
        model_size = "1.5x"
        fpn_in_channels = [176, 352, 704]
        fpn_out_channels = 128
        aux_in_channel = 256
        aux_feat_channels = 256
    else:
        raise ValueError(f"Unknown variant: {variant}")

    strides = [8, 16, 32, 64]
    kernel_size = 5
    reg_max = 7

    # Build class_names list for the config
    class_names = ["piece"]

    config = f"""#
# Auto-generated NanoDet-Plus config for LEGO chamber detection
# Variant: {variant}, Input: {imgsz}x{imgsz}
#
save_dir: {save_dir}
check_point_save_period: 10
keep_checkpoint_max: 3
log:
  interval: 50

model:
  weight_averager:
    name: ExpMovingAverager
    decay: 0.9998
  arch:
    name: NanoDetPlus
    detach_epoch: 10
    backbone:
      name: ShuffleNetV2
      model_size: {model_size}
      out_stages: [2, 3, 4]
      activation: LeakyReLU
    fpn:
      name: GhostPAN
      in_channels: {fpn_in_channels}
      out_channels: {fpn_out_channels}
      kernel_size: {kernel_size}
      num_extra_level: 1
      use_depthwise: True
      activation: LeakyReLU
    head:
      name: NanoDetPlusHead
      num_classes: {num_classes}
      input_channel: {fpn_out_channels}
      feat_channels: {fpn_out_channels}
      stacked_convs: 2
      kernel_size: {kernel_size}
      strides: {strides}
      activation: LeakyReLU
      reg_max: {reg_max}
      norm_cfg:
        type: BN
      loss:
        loss_qfl:
          name: QualityFocalLoss
          use_sigmoid: True
          beta: 2.0
          loss_weight: 1.0
        loss_dfl:
          name: DistributionFocalLoss
          loss_weight: 0.25
        loss_bbox:
          name: GIoULoss
          loss_weight: 2.0
    aux_head:
      name: SimpleConvHead
      num_classes: {num_classes}
      input_channel: {aux_in_channel}
      feat_channels: {aux_feat_channels}
      stacked_convs: 4
      strides: {strides}
      activation: LeakyReLU
      reg_max: {reg_max}

data:
  train:
    name: CocoDataset
    img_path: {train_img_dir}
    ann_path: {train_ann_path}
    input_size: [{imgsz}, {imgsz}]
    keep_ratio: False
    pipeline:
      perspective: 0.0
      scale: [0.6, 1.4]
      stretch: [[0.8, 1.2], [0.8, 1.2]]
      rotation: 0
      shear: 0
      translate: 0.2
      flip: 0.5
      brightness: 0.2
      contrast: [0.6, 1.4]
      saturation: [0.5, 1.2]
      normalize: [[103.53, 116.28, 123.675], [57.375, 57.12, 58.395]]
  val:
    name: CocoDataset
    img_path: {val_img_dir}
    ann_path: {val_ann_path}
    input_size: [{imgsz}, {imgsz}]
    keep_ratio: False
    pipeline:
      normalize: [[103.53, 116.28, 123.675], [57.375, 57.12, 58.395]]

device:
  gpu_ids: -1
  workers_per_gpu: {workers}
  batchsize_per_gpu: {batch_size}
  precision: 32

schedule:
  optimizer:
    name: AdamW
    lr: {lr}
    weight_decay: 0.05
  warmup:
    name: linear
    steps: 500
    ratio: 0.0001
  total_epochs: {epochs}
  lr_schedule:
    name: CosineAnnealingLR
    T_max: {epochs}
    eta_min: 0.0
  val_intervals: 10

grad_clip: 35

evaluator:
  name: CocoDetectionEvaluator
  save_key: mAP

class_names: {class_names}
"""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config)


def _setup_nanodet_venv() -> Path:
    """Clone nanodet and create a venv with all dependencies."""
    # Clone repo if needed
    if not (NANODET_DIR / "setup.py").exists():
        print(f"Cloning nanodet to {NANODET_DIR}...")
        if NANODET_DIR.exists():
            shutil.rmtree(NANODET_DIR)
        subprocess.run(
            ["git", "clone", "--depth", "1", NANODET_REPO, str(NANODET_DIR)],
            check=True,
        )

    # Create venv if needed
    venv_python = NANODET_VENV / "bin" / "python"
    if not venv_python.exists():
        print(f"Creating nanodet venv at {NANODET_VENV}...")
        subprocess.run(
            [sys.executable, "-m", "venv", str(NANODET_VENV)],
            check=True,
        )
        pip = str(NANODET_VENV / "bin" / "pip")
        # Install PyTorch first (CPU-only)
        subprocess.run(
            [pip, "install", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu"],
            check=True,
        )
        # Install nanodet with dependencies
        subprocess.run(
            [pip, "install", "-e", str(NANODET_DIR)],
            check=True,
        )
        # Install extra deps (pytorch-lightning for training, various libs nanodet needs)
        subprocess.run(
            [pip, "install", "onnx", "onnxsim", "onnxruntime", "pycocotools",
             "pytorch-lightning", "termcolor", "tabulate", "opencv-python-headless",
             "matplotlib", "imagesize"],
            check=True,
        )

    return venv_python


def _run_nanodet_training(
    venv_python: Path,
    config_path: Path,
) -> dict[str, Any]:
    """Run nanodet training via subprocess."""
    train_script = NANODET_DIR / "tools" / "train.py"
    cmd = [str(venv_python), str(train_script), str(config_path)]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(NANODET_DIR),
        capture_output=False,
        timeout=36000,  # 10 hour timeout
    )
    return {"returncode": result.returncode}


def _export_nanodet_onnx(
    venv_python: Path,
    config_path: Path,
    model_path: Path,
    onnx_path: Path,
) -> dict[str, Any]:
    """Export trained NanoDet model to ONNX."""
    export_script = NANODET_DIR / "tools" / "export_onnx.py"
    cmd = [
        str(venv_python),
        str(export_script),
        "--cfg_path", str(config_path),
        "--model_path", str(model_path),
        "--out_path", str(onnx_path),
    ]
    print(f"Exporting ONNX: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(NANODET_DIR), capture_output=True, text=True)
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr[:500]}

    # Simplify with onnxsim
    sim_path = onnx_path.with_name(onnx_path.stem + "-sim.onnx")
    subprocess.run(
        [str(NANODET_VENV / "bin" / "python"), "-m", "onnxsim", str(onnx_path), str(sim_path)],
        capture_output=True,
    )
    final_onnx = sim_path if sim_path.exists() else onnx_path
    return {
        "ok": True,
        "onnx_path": str(onnx_path),
        "simplified_path": str(sim_path) if sim_path.exists() else None,
        "final_onnx": str(final_onnx),
        "size_bytes": final_onnx.stat().st_size,
    }


def _iou(box_a: list[float], box_b: list[float]) -> float:
    x_min = max(box_a[0], box_b[0])
    y_min = max(box_a[1], box_b[1])
    x_max = min(box_a[2], box_b[2])
    y_max = min(box_a[3], box_b[3])
    inter_w = max(0.0, x_max - x_min)
    inter_h = max(0.0, y_max - y_min)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    if boxes.size == 0:
        return []
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_i = max(0.0, boxes[i, 2] - boxes[i, 0]) * max(0.0, boxes[i, 3] - boxes[i, 1])
        area_rest = np.maximum(0.0, boxes[rest, 2] - boxes[rest, 0]) * np.maximum(0.0, boxes[rest, 3] - boxes[rest, 1])
        union = area_i + area_rest - inter
        ious = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
        order = rest[ious <= iou_threshold]
    return keep


def _decode_nanodet_output(
    output: np.ndarray,
    imgsz: int,
    original_h: int,
    original_w: int,
    reg_max: int = 7,
    strides: list[int] | None = None,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
) -> tuple[list[list[int]], list[float]]:
    """Decode NanoDet-Plus ONNX output to bounding boxes.

    NanoDet-Plus ONNX output is [1, N, num_classes + 4*(reg_max+1)] where
    class scores already have sigmoid applied (done in _forward_onnx).
    N is the total number of anchor points across all FPN levels.
    """
    if strides is None:
        strides = [8, 16, 32, 64]

    # Generate anchor points
    anchor_points: list[tuple[float, float, int]] = []
    for stride in strides:
        grid_h = imgsz // stride
        grid_w = imgsz // stride
        for y in range(grid_h):
            for x in range(grid_w):
                anchor_points.append((x * stride, y * stride, stride))

    preds = output[0]  # [N, C]
    num_anchors = preds.shape[0]
    num_reg = 4 * (reg_max + 1)
    num_classes = preds.shape[1] - num_reg

    # Split into class scores and bbox regressions
    # Note: sigmoid is already applied in the ONNX model's _forward_onnx path
    cls_scores = preds[:, :num_classes]
    bbox_preds = preds[:, num_classes:]

    all_boxes: list[list[float]] = []
    all_scores: list[float] = []

    for idx in range(min(num_anchors, len(anchor_points))):
        score = float(np.max(cls_scores[idx]))
        if score < conf_threshold:
            continue

        cx, cy, stride = anchor_points[idx]
        reg = bbox_preds[idx].reshape(4, reg_max + 1)

        # Softmax per side and compute distance
        distances = []
        for side in range(4):
            side_vals = reg[side]
            exp_vals = np.exp(side_vals - np.max(side_vals))
            probs = exp_vals / np.sum(exp_vals)
            dist = sum(j * probs[j] for j in range(reg_max + 1))
            distances.append(dist * stride)

        # Convert distances to bbox (ltrb format)
        x1 = cx - distances[0]
        y1 = cy - distances[1]
        x2 = cx + distances[2]
        y2 = cy + distances[3]

        # Scale to original image
        scale_x = original_w / imgsz
        scale_y = original_h / imgsz
        x1 = max(0, min(original_w, x1 * scale_x))
        y1 = max(0, min(original_h, y1 * scale_y))
        x2 = max(0, min(original_w, x2 * scale_x))
        y2 = max(0, min(original_h, y2 * scale_y))

        if x2 > x1 and y2 > y1:
            all_boxes.append([x1, y1, x2, y2])
            all_scores.append(score)

    if not all_boxes:
        return [], []

    boxes_np = np.array(all_boxes)
    scores_np = np.array(all_scores)
    kept = _nms(boxes_np, scores_np, iou_threshold)

    result_boxes = [[int(round(v)) for v in all_boxes[i]] for i in kept]
    result_scores = [all_scores[i] for i in kept]
    return result_boxes, result_scores


def _evaluate_onnx_model(
    onnx_path: Path,
    test_samples: list[PreparedSample],
    *,
    imgsz: int,
    conf: float,
    iou_threshold: float,
    model_family: str = "nanodet",
) -> dict[str, Any]:
    """Evaluate an ONNX model on test samples with consistent metrics."""
    import onnxruntime as ort

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    input_shape = session.get_inputs()[0].shape

    # NanoDet uses BGR with specific normalization
    mean = np.array([103.53, 116.28, 123.675], dtype=np.float32)
    std = np.array([57.375, 57.12, 58.395], dtype=np.float32)

    total = 0
    exact_count = 0
    decision_match = 0
    empty_correct = 0
    single_correct = 0
    multi_samples = 0
    multi_detect = 0
    multi_correct = 0
    single_ious: list[float] = []
    total_latency_ms = 0.0

    for sample in test_samples:
        image = cv2.imread(str(sample.image_path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        original_h, original_w = image.shape[:2]

        # Preprocess
        resized = cv2.resize(image, (imgsz, imgsz), interpolation=cv2.INTER_LINEAR).astype(np.float32)
        normalized = (resized - mean) / std
        if len(input_shape) == 4 and input_shape[1] == 3:
            # NCHW format
            blob = np.transpose(normalized, (2, 0, 1))[None, ...].astype(np.float32)
        else:
            blob = normalized[None, ...].astype(np.float32)

        # Inference
        start = time.perf_counter()
        outputs = session.run(None, {input_name: blob})
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        total_latency_ms += elapsed_ms

        # Decode
        pred_boxes, pred_scores = _decode_nanodet_output(
            outputs[0],
            imgsz=imgsz,
            original_h=original_h,
            original_w=original_w,
            conf_threshold=conf,
            iou_threshold=iou_threshold,
        )

        # Ground truth
        gt_polygons = parse_segmentation_label(sample.segmentation_label_path)
        gt_count = len(gt_polygons)
        gt_decision = "empty" if gt_count == 0 else "single" if gt_count == 1 else "multi"
        gt_boxes: list[list[float]] = []
        for polygon in gt_polygons:
            x_min, y_min, x_max, y_max = polygon_to_bbox(polygon)
            gt_boxes.append([x_min * original_w, y_min * original_h, x_max * original_w, y_max * original_h])

        pred_count = len(pred_boxes)
        pred_decision = "empty" if pred_count == 0 else "single" if pred_count == 1 else "multi"
        total += 1

        if pred_count == gt_count:
            exact_count += 1
        if pred_decision == gt_decision:
            decision_match += 1
        if gt_count == 0 and pred_count == 0:
            empty_correct += 1
        elif gt_count == 1 and pred_count == 1:
            single_correct += 1
            single_ious.append(_iou(
                [float(v) for v in pred_boxes[0]],
                gt_boxes[0],
            ))
        elif gt_count > 1:
            multi_samples += 1
            if pred_count == gt_count:
                multi_correct += 1
            if pred_count > 1:
                multi_detect += 1

    return {
        "samples": total,
        "exact_count_match_rate": (exact_count / total) if total else 0.0,
        "decision_match_rate": (decision_match / total) if total else 0.0,
        "empty_correct": empty_correct,
        "single_exact_count": single_correct,
        "multi_exact_count": multi_correct,
        "multi_detect_rate": (multi_detect / multi_samples) if multi_samples else None,
        "single_mean_iou": (sum(single_ious) / len(single_ious)) if single_ious else None,
        "avg_latency_ms": (total_latency_ms / total) if total else 0.0,
        "confidence_threshold": conf,
    }


def _find_best_checkpoint(save_dir: Path) -> Path | None:
    """Find the best model checkpoint from nanodet training."""
    # NanoDet saves the actual weights as nanodet_model_best.pth
    # and Lightning checkpoints as model_best.ckpt
    for pattern in [
        "**/nanodet_model_best.pth",
        "**/model_best.ckpt",
        "**/model_best.pth",
        "**/model_last.ckpt",
        "model_last.ckpt",
    ]:
        matches = sorted(save_dir.glob(pattern))
        if matches:
            return matches[-1]
    # Also check for any Lightning checkpoints
    for pattern in ["**/*.ckpt"]:
        matches = sorted(save_dir.glob(pattern))
        if matches:
            best_matches = [m for m in matches if "best" in m.name.lower()]
            return best_matches[-1] if best_matches else matches[-1]
    return None


def _write_run_summary(
    summary_path: Path,
    *,
    args: argparse.Namespace,
    sample_count: int,
    skipped: dict[str, int],
    splits: dict[str, list[PreparedSample]],
    dataset_paths: dict[str, Any],
    training: dict[str, Any] | None,
) -> None:
    payload = {
        "created_at": time.time(),
        "run_name": args.name,
        "runtime": "onnx",
        "model_family": "nanodet",
        "training_root": str(Path(args.training_root).resolve()),
        "sample_count": sample_count,
        "skipped_samples": skipped,
        "splits": {name: dataset_stats(items) for name, items in splits.items()},
        "dataset": dataset_paths,
        "train_args": {
            "variant": args.variant,
            "imgsz": args.imgsz,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "workers": args.workers,
            "seed": args.seed,
            "val_fraction": args.val_fraction,
            "test_fraction": args.test_fraction,
            "limit": args.limit,
            "conf": args.conf,
        },
        "inference": {
            "backend": "onnxruntime",
            "family": "nanodet",
            "variant": args.variant,
            "imgsz": args.imgsz,
        },
        "training": training,
    }
    summary_path.write_text(json.dumps(payload, indent=2, default=str))


def main() -> int:
    args = _parse_args()
    training_root = Path(args.training_root).resolve()
    output_root = Path(args.output_root).resolve()
    if not training_root.exists():
        raise SystemExit(f"Training root does not exist: {training_root}")

    accepted, skipped = collect_samples(training_root, limit=args.limit, seed=args.seed)
    if not accepted:
        raise SystemExit("No valid classification-chamber samples found.")

    run_dir = prepare_run_dir(output_root, args.name)
    splits = split_samples(
        accepted,
        val_fraction=args.val_fraction,
        test_fraction=args.test_fraction,
        seed=args.seed,
    )
    dataset_paths = _prepare_dataset(run_dir, splits)

    # Generate nanodet config
    config_path = run_dir / "nanodet_config.yml"
    nanodet_workspace = run_dir / "train"
    _generate_nanodet_config(
        config_path,
        variant=args.variant,
        imgsz=args.imgsz,
        num_classes=1,
        train_img_dir=dataset_paths["train_images"],
        train_ann_path=dataset_paths["train"]["path"],
        val_img_dir=dataset_paths["val_images"],
        val_ann_path=dataset_paths["val"]["path"],
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        workers=args.workers,
        save_dir=str(nanodet_workspace),
    )

    summary_path = run_dir / "run.json"
    training_summary: dict[str, Any] | None = None
    training_error: str | None = None

    if not args.prepare_only:
        try:
            # Setup nanodet environment
            if not args.skip_venv_setup:
                venv_python = _setup_nanodet_venv()
            else:
                venv_python = NANODET_VENV / "bin" / "python"
                if not venv_python.exists():
                    raise RuntimeError("NanoDet venv not found. Run without --skip-venv-setup first.")

            # Train
            train_result = _run_nanodet_training(venv_python, config_path)

            # Find best checkpoint
            best_ckpt = _find_best_checkpoint(nanodet_workspace)
            if best_ckpt is None:
                raise RuntimeError(f"No checkpoint found in {nanodet_workspace}")

            # Export to ONNX
            exports_dir = run_dir / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            onnx_path = exports_dir / "best.onnx"
            onnx_result = _export_nanodet_onnx(
                venv_python, config_path, best_ckpt, onnx_path,
            )

            training_summary = {
                "framework": "nanodet",
                "variant": args.variant,
                "train_result": train_result,
                "best_checkpoint": str(best_ckpt),
                "onnx_export": onnx_result,
            }

            # Evaluate with ONNX Runtime
            final_onnx = Path(onnx_result.get("final_onnx", str(onnx_path)))
            if final_onnx.exists():
                # Confidence sweep on val
                sweep: list[dict[str, Any]] = []
                best_conf = args.conf
                best_score = (-1.0, -1.0)
                for conf in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35]:
                    metrics = _evaluate_onnx_model(
                        final_onnx, splits["val"],
                        imgsz=args.imgsz, conf=conf, iou_threshold=args.iou_threshold,
                    )
                    metrics["confidence_threshold"] = conf
                    sweep.append(metrics)
                    score = (
                        float(metrics["decision_match_rate"]),
                        float(metrics["exact_count_match_rate"]),
                    )
                    if score > best_score:
                        best_score = score
                        best_conf = conf

                # Test with best conf
                test_metrics = _evaluate_onnx_model(
                    final_onnx, splits["test"],
                    imgsz=args.imgsz, conf=best_conf, iou_threshold=args.iou_threshold,
                )
                test_metrics["confidence_threshold"] = best_conf

                training_summary["benchmark"] = {
                    "backend": "onnxruntime",
                    "sweep_metric": "decision_match_rate",
                    "selected_confidence_threshold": best_conf,
                    "validation_sweep": sweep,
                    "test_metrics": test_metrics,
                }
                training_summary["model_size_bytes"] = final_onnx.stat().st_size

        except Exception as exc:
            import traceback
            training_error = f"{exc}\n{traceback.format_exc()}"

    _write_run_summary(
        summary_path,
        args=args,
        sample_count=len(accepted),
        skipped=skipped,
        splits=splits,
        dataset_paths=dataset_paths,
        training=(
            training_summary
            if training_error is None
            else {"error": training_error, "partial": training_summary}
        ),
    )

    if training_error is not None:
        raise SystemExit(
            f"Dataset prepared at {run_dir}, but NanoDet training failed: {training_error}. "
            f"See {summary_path}."
        )

    output = {
        "ok": True,
        "run_dir": str(run_dir),
        "run_summary": str(summary_path),
        "sample_count": len(accepted),
        "prepared_only": bool(args.prepare_only),
        "training": training_summary,
    }
    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
