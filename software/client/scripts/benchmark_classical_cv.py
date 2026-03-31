from __future__ import annotations

import argparse
import json
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark classical CV frame-differencing detection on classification-chamber samples."
    )
    parser.add_argument("--training-root", default=str(TRAINING_ROOT))
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    parser.add_argument("--name", default="classical-cv-frame-diff-benchmark")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--test-fraction", type=float, default=0.10)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--threshold", type=int, default=30, help="Binary threshold for absdiff.")
    parser.add_argument("--min-area-fraction", type=float, default=0.002, help="Min contour area as fraction of image area.")
    parser.add_argument("--dilate-kernel", type=int, default=7, help="Dilation kernel size.")
    parser.add_argument("--dilate-iterations", type=int, default=3, help="Number of dilation passes.")
    args = parser.parse_args()
    if args.val_fraction < 0 or args.test_fraction < 0:
        parser.error("Split fractions must be non-negative.")
    if (args.val_fraction + args.test_fraction) >= 1.0:
        parser.error("Validation + test fraction must be below 1.0.")
    return args


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


def _build_reference_image(negative_samples: list[PreparedSample]) -> np.ndarray | None:
    """Build a reference empty-chamber image by averaging all negative (0-piece) samples."""
    if not negative_samples:
        return None
    images: list[np.ndarray] = []
    for sample in negative_samples:
        image = cv2.imread(str(sample.image_path), cv2.IMREAD_COLOR)
        if image is not None:
            images.append(image.astype(np.float64))
    if not images:
        return None
    target_shape = images[0].shape
    compatible = [img for img in images if img.shape == target_shape]
    if not compatible:
        return None
    averaged = np.mean(compatible, axis=0).astype(np.uint8)
    return averaged


def _detect_classical(
    image: np.ndarray,
    reference: np.ndarray,
    *,
    threshold: int,
    min_area_fraction: float,
    dilate_kernel: int,
    dilate_iterations: int,
) -> list[list[int]]:
    """Frame-differencing detection: absdiff -> threshold -> dilate -> contours -> bboxes."""
    gray_current = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray_reference = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    if gray_current.shape != gray_reference.shape:
        gray_reference = cv2.resize(gray_reference, (gray_current.shape[1], gray_current.shape[0]))
    diff = cv2.absdiff(gray_current, gray_reference)
    _, binary = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate_kernel, dilate_kernel))
    dilated = cv2.dilate(binary, kernel, iterations=dilate_iterations)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = min_area_fraction * image.shape[0] * image.shape[1]
    bboxes: list[list[int]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        bboxes.append([x, y, x + w, y + h])
    return bboxes


def _evaluate_split(
    samples: list[PreparedSample],
    reference: np.ndarray,
    *,
    threshold: int,
    min_area_fraction: float,
    dilate_kernel: int,
    dilate_iterations: int,
) -> dict[str, Any]:
    total = 0
    exact_count = 0
    decision_match = 0
    empty_correct = 0
    single_correct = 0
    multi_correct = 0
    multi_samples = 0
    multi_detect = 0
    single_ious: list[float] = []
    total_latency_ms = 0.0

    for sample in samples:
        image = cv2.imread(str(sample.image_path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        height, width = image.shape[:2]

        gt_polygons = parse_segmentation_label(sample.segmentation_label_path)
        gt_count = len(gt_polygons)
        gt_decision = "empty" if gt_count == 0 else "single" if gt_count == 1 else "multi"
        gt_boxes: list[list[float]] = []
        for polygon in gt_polygons:
            x_min, y_min, x_max, y_max = polygon_to_bbox(polygon)
            gt_boxes.append([x_min * width, y_min * height, x_max * width, y_max * height])

        start = time.perf_counter()
        pred_bboxes = _detect_classical(
            image,
            reference,
            threshold=threshold,
            min_area_fraction=min_area_fraction,
            dilate_kernel=dilate_kernel,
            dilate_iterations=dilate_iterations,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        total_latency_ms += elapsed_ms

        pred_count = len(pred_bboxes)
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
                [float(v) for v in pred_bboxes[0]],
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
    }


def _sweep_thresholds(
    val_samples: list[PreparedSample],
    reference: np.ndarray,
    *,
    min_area_fraction: float,
    dilate_kernel: int,
    dilate_iterations: int,
) -> tuple[list[dict[str, Any]], int]:
    thresholds = [15, 20, 25, 30, 35, 40, 50]
    sweep: list[dict[str, Any]] = []
    best_threshold = 30
    best_score = (-1.0, -1.0, -1.0)

    for threshold in thresholds:
        metrics = _evaluate_split(
            val_samples,
            reference,
            threshold=threshold,
            min_area_fraction=min_area_fraction,
            dilate_kernel=dilate_kernel,
            dilate_iterations=dilate_iterations,
        )
        metrics["threshold"] = threshold
        sweep.append(metrics)
        score = (
            float(metrics["decision_match_rate"]),
            float(metrics["exact_count_match_rate"]),
            float(metrics["multi_detect_rate"] or 0.0),
        )
        if score > best_score:
            best_score = score
            best_threshold = threshold

    return sweep, best_threshold


def main() -> int:
    args = _parse_args()
    training_root = Path(args.training_root).resolve()
    output_root = Path(args.output_root).resolve()
    if not training_root.exists():
        raise SystemExit(f"Training root does not exist: {training_root}")

    accepted, skipped = collect_samples(training_root, limit=args.limit, seed=args.seed)
    if not accepted:
        raise SystemExit("No valid samples found.")

    splits = split_samples(
        accepted,
        val_fraction=args.val_fraction,
        test_fraction=args.test_fraction,
        seed=args.seed,
    )

    negative_samples = [s for s in splits["train"] if s.detection_count == 0]
    if not negative_samples:
        negative_samples = [s for s in accepted if s.detection_count == 0]
    reference = _build_reference_image(negative_samples)
    if reference is None:
        raise SystemExit(
            "No negative (empty-chamber) samples found to build a reference image. "
            "Classical CV frame differencing requires at least one empty reference."
        )

    run_dir = prepare_run_dir(output_root, args.name)

    ref_path = run_dir / "reference_image.jpg"
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(ref_path), reference)

    sweep, best_threshold = _sweep_thresholds(
        splits["val"],
        reference,
        min_area_fraction=args.min_area_fraction,
        dilate_kernel=args.dilate_kernel,
        dilate_iterations=args.dilate_iterations,
    )

    test_metrics = _evaluate_split(
        splits["test"],
        reference,
        threshold=best_threshold,
        min_area_fraction=args.min_area_fraction,
        dilate_kernel=args.dilate_kernel,
        dilate_iterations=args.dilate_iterations,
    )
    test_metrics["threshold"] = best_threshold

    val_best = next((s for s in sweep if s["threshold"] == best_threshold), sweep[0])

    payload = {
        "created_at": time.time(),
        "run_name": args.name,
        "runtime": "opencv_classical",
        "model_family": "classical_cv",
        "training_root": str(training_root),
        "sample_count": len(accepted),
        "skipped_samples": skipped,
        "splits": {name: dataset_stats(items) for name, items in splits.items()},
        "train_args": {
            "threshold": args.threshold,
            "min_area_fraction": args.min_area_fraction,
            "dilate_kernel": args.dilate_kernel,
            "dilate_iterations": args.dilate_iterations,
            "seed": args.seed,
            "val_fraction": args.val_fraction,
            "test_fraction": args.test_fraction,
            "limit": args.limit,
        },
        "inference": {
            "backend": "opencv",
            "family": "classical_cv",
            "method": "frame_differencing",
            "reference_image": str(ref_path),
            "negative_samples_used": len(negative_samples),
        },
        "training": {
            "framework": "opencv_classical_cv",
            "validation": {
                "best_validation_metrics": {
                    "decision_match_rate": val_best["decision_match_rate"],
                    "exact_count_match_rate": val_best["exact_count_match_rate"],
                    "single_mean_iou": val_best["single_mean_iou"],
                },
            },
            "benchmark": {
                "backend": "opencv_classical",
                "sweep_metric": "decision_match_rate",
                "selected_threshold": best_threshold,
                "selected_confidence_threshold": best_threshold,
                "validation_sweep": sweep,
                "test_metrics": test_metrics,
            },
        },
    }

    summary_path = run_dir / "run.json"
    summary_path.write_text(json.dumps(payload, indent=2))

    output = {
        "ok": True,
        "run_dir": str(run_dir),
        "run_summary": str(summary_path),
        "sample_count": len(accepted),
        "best_threshold": best_threshold,
        "test_metrics": test_metrics,
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
