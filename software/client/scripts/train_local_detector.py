from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from pathlib import Path
from typing import Any

from local_detector_dataset import (
    TRAINING_ROOT,
    PreparedSample,
    collect_samples,
    dataset_stats,
    materialize_split_images,
    parse_segmentation_label,
    polygon_to_bbox,
    polygon_to_detect_label,
    prepare_run_dir,
    split_samples,
    write_manifest,
)

CLIENT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = CLIENT_ROOT / "blob" / "local_detection_models"
BENCHMARK_CONFIDENCES = (0.10, 0.15, 0.20, 0.25, 0.30, 0.35)
BENCHMARK_IOU = 0.45


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a timestamped local classification-chamber detector run from the saved pseudo-labeled "
            "sample library. By default this prepares a YOLO-detect dataset and trains a model if "
            "Ultralytics is available."
        )
    )
    parser.add_argument(
        "--training-root",
        default=str(TRAINING_ROOT),
        help="Root directory containing classification_training sessions.",
    )
    parser.add_argument(
        "--output-root",
        default=str(OUTPUT_ROOT),
        help="Where to create timestamped detector run directories.",
    )
    parser.add_argument(
        "--name",
        default="classification-chamber-piece-detector",
        help="Human-readable run name suffix.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed used for dataset shuffling and split generation.",
    )
    parser.add_argument(
        "--val-fraction",
        type=float,
        default=0.15,
        help="Fraction of samples to place into the validation split.",
    )
    parser.add_argument(
        "--test-fraction",
        type=float,
        default=0.10,
        help="Fraction of samples to place into the test split.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on the number of accepted samples for smoke tests.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Only build the dataset and manifest; do not start training.",
    )
    parser.add_argument(
        "--model",
        default="yolo11n.pt",
        help="Ultralytics detector checkpoint or model name to fine-tune.",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=80,
        help="Training epochs when training is enabled.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="Training/export image size.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=16,
        help="Training batch size.",
    )
    parser.add_argument(
        "--patience",
        type=int,
        default=20,
        help="Early stopping patience for training.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of data loader workers for training.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Ultralytics training device, e.g. cpu, mps, 0.",
    )
    parser.add_argument(
        "--no-export-onnx",
        action="store_true",
        help="Skip ONNX export after training.",
    )
    args = parser.parse_args()
    if args.val_fraction < 0 or args.test_fraction < 0:
        parser.error("Split fractions must be non-negative.")
    if (args.val_fraction + args.test_fraction) >= 1.0:
        parser.error("Validation + test fraction must be below 1.0.")
    if args.limit < 0:
        parser.error("--limit must be >= 0.")
    return args


def _write_detect_label(src_label: Path, dst_label: Path) -> int:
    polygons = parse_segmentation_label(src_label)
    lines = [polygon_to_detect_label(polygon) for polygon in polygons]
    dst_label.parent.mkdir(parents=True, exist_ok=True)
    dst_label.write_text("\n".join(lines))
    return len(lines)


def _write_dataset_yaml(path: Path, dataset_root: Path) -> None:
    content = (
        f"path: {dataset_root}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        "names:\n"
        "  0: piece\n"
    )
    path.write_text(content)


def _prepare_dataset(
    run_dir: Path,
    splits: dict[str, list[PreparedSample]],
) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.jsonl"
    dataset_root, manifest_records = materialize_split_images(run_dir, splits)

    for record in manifest_records:
        split_name = str(record["split"])
        dataset_image = Path(str(record["dataset_image"]))
        labels_dir = dataset_root / "labels" / split_name
        labels_dir.mkdir(parents=True, exist_ok=True)
        label_dst = labels_dir / f"{dataset_image.stem}.txt"
        label_count = _write_detect_label(Path(str(record["segmentation_label_path"])), label_dst)
        record["dataset_label"] = str(label_dst)
        record["label_count"] = label_count

    _write_dataset_yaml(run_dir / "dataset.yaml", dataset_root)
    write_manifest(manifest_path, manifest_records)
    return {
        "dataset_root": str(dataset_root),
        "dataset_yaml": str(run_dir / "dataset.yaml"),
        "manifest_path": str(manifest_path),
    }


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
        "model_family": "yolo",
        "training_root": str(Path(args.training_root).resolve()),
        "sample_count": sample_count,
        "skipped_samples": skipped,
        "splits": {name: dataset_stats(items) for name, items in splits.items()},
        "dataset": dataset_paths,
        "train_args": {
            "prepare_only": args.prepare_only,
            "model": args.model,
            "epochs": args.epochs,
            "imgsz": args.imgsz,
            "batch": args.batch,
            "patience": args.patience,
            "workers": args.workers,
            "device": args.device,
            "seed": args.seed,
            "val_fraction": args.val_fraction,
            "test_fraction": args.test_fraction,
            "limit": args.limit,
            "export_onnx": not args.no_export_onnx,
        },
        "inference": {
            "backend": "ultralytics",
            "family": "yolo",
            "imgsz": args.imgsz,
        },
        "training": training,
    }
    summary_path.write_text(json.dumps(payload, indent=2))


def _copy_if_exists(src: Path, dst: Path) -> str | None:
    if not src.exists() or not src.is_file():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def _iou(box_a: list[float], box_b: list[float]) -> float:
    x_min = max(float(box_a[0]), float(box_b[0]))
    y_min = max(float(box_a[1]), float(box_b[1]))
    x_max = min(float(box_a[2]), float(box_b[2]))
    y_max = min(float(box_a[3]), float(box_b[3]))
    inter_w = max(0.0, x_max - x_min)
    inter_h = max(0.0, y_max - y_min)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0.0, float(box_a[2]) - float(box_a[0])) * max(0.0, float(box_a[3]) - float(box_a[1]))
    area_b = max(0.0, float(box_b[2]) - float(box_b[0])) * max(0.0, float(box_b[3]) - float(box_b[1]))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _load_manifest_rows(run_dir: Path, split_name: str) -> list[dict[str, Any]]:
    manifest_path = run_dir / "manifest.jsonl"
    if not manifest_path.exists():
        return []
    rows = [json.loads(line) for line in manifest_path.read_text().splitlines() if line.strip()]
    return [row for row in rows if row.get("split") == split_name]


def _benchmark_predictions(results: list[Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    import cv2

    samples = 0
    exact_count_match = 0
    decision_match = 0
    empty_correct = 0
    single_exact_count = 0
    multi_exact_count = 0
    multi_detect = 0
    multi_samples = 0
    single_ious: list[float] = []

    for row, result in zip(rows, results):
        gt_polygons = parse_segmentation_label(Path(str(row["segmentation_label_path"])))
        gt_count = len(gt_polygons)
        gt_decision = "empty" if gt_count == 0 else "single" if gt_count == 1 else "multi"
        image = cv2.imread(str(row["image_path"]), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"Could not read benchmark image: {row['image_path']}")
        height, width = image.shape[:2]
        gt_boxes = []
        for polygon in gt_polygons:
            x_min, y_min, x_max, y_max = polygon_to_bbox(polygon)
            gt_boxes.append([x_min * width, y_min * height, x_max * width, y_max * height])

        pred_boxes: list[list[float]] = []
        if result.boxes is not None and result.boxes.xyxy is not None:
            for bbox in result.boxes.xyxy.cpu().numpy().tolist():
                pred_boxes.append([float(value) for value in bbox[:4]])

        pred_count = len(pred_boxes)
        pred_decision = "empty" if pred_count == 0 else "single" if pred_count == 1 else "multi"
        samples += 1
        if pred_count == gt_count:
            exact_count_match += 1
        if pred_decision == gt_decision:
            decision_match += 1
        if gt_count == 0 and pred_count == 0:
            empty_correct += 1
        elif gt_count == 1 and pred_count == 1:
            single_exact_count += 1
            single_ious.append(_iou(pred_boxes[0], gt_boxes[0]))
        elif gt_count > 1:
            multi_samples += 1
            if pred_count == gt_count:
                multi_exact_count += 1
            if pred_count > 1:
                multi_detect += 1

    return {
        "samples": samples,
        "exact_count_match_rate": (exact_count_match / samples) if samples else 0.0,
        "decision_match_rate": (decision_match / samples) if samples else 0.0,
        "empty_correct": empty_correct,
        "single_exact_count": single_exact_count,
        "multi_exact_count": multi_exact_count,
        "multi_detect_rate": (multi_detect / multi_samples) if multi_samples else None,
        "single_mean_iou": (sum(single_ious) / len(single_ious)) if single_ious else None,
    }


def _benchmark_model(run_dir: Path, *, model_path: Path, imgsz: int) -> dict[str, Any] | None:
    try:
        from ultralytics import YOLO
    except ImportError:
        return None

    val_rows = _load_manifest_rows(run_dir, "val")
    test_rows = _load_manifest_rows(run_dir, "test")
    if not val_rows or not test_rows:
        return None

    model = YOLO(str(model_path), task="detect")

    def predict_rows(rows: list[dict[str, Any]], conf: float) -> tuple[list[Any], float]:
        collected: list[Any] = []
        started = time.perf_counter()
        for row in rows:
            results = model.predict(
                source=str(row["image_path"]),
                imgsz=imgsz,
                conf=conf,
                iou=BENCHMARK_IOU,
                device="cpu",
                verbose=False,
            )
            collected.extend(list(results))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return collected, elapsed_ms

    sweep: list[dict[str, Any]] = []
    best_conf = BENCHMARK_CONFIDENCES[0]
    best_score: tuple[float, float, float] = (-1.0, -1.0, -1.0)
    for conf in BENCHMARK_CONFIDENCES:
        val_results, val_elapsed_ms = predict_rows(val_rows, conf)
        metrics = _benchmark_predictions(val_results, val_rows)
        metrics["confidence_threshold"] = conf
        metrics["avg_latency_ms"] = val_elapsed_ms / len(val_rows)
        sweep.append(metrics)
        score = (
            float(metrics["decision_match_rate"]),
            float(metrics["exact_count_match_rate"]),
            float(metrics["multi_detect_rate"] or 0.0),
        )
        if score > best_score:
            best_score = score
            best_conf = conf

    test_results, test_elapsed_ms = predict_rows(test_rows, best_conf)
    test_metrics = _benchmark_predictions(test_results, test_rows)
    test_metrics["confidence_threshold"] = best_conf
    test_metrics["avg_latency_ms"] = test_elapsed_ms / len(test_rows)
    return {
        "backend": "ultralytics",
        "sweep_metric": "decision_match_rate",
        "iou_threshold": BENCHMARK_IOU,
        "selected_confidence_threshold": best_conf,
        "validation_sweep": sweep,
        "test_metrics": test_metrics,
    }


def _read_training_results(project_dir: Path) -> dict[str, Any] | None:
    results_path = project_dir / "results.csv"
    if not results_path.exists():
        return None
    rows = list(csv.DictReader(results_path.open()))
    if not rows:
        return None
    best_row = max(rows, key=lambda row: float(row.get("metrics/mAP50-95(B)", 0.0)))
    last_row = rows[-1]
    return {
        "results_csv": str(results_path),
        "epochs_recorded": len(rows),
        "best_validation_epoch": int(float(best_row["epoch"])),
        "best_validation_metrics": {
            "precision": float(best_row["metrics/precision(B)"]),
            "recall": float(best_row["metrics/recall(B)"]),
            "mAP50": float(best_row["metrics/mAP50(B)"]),
            "mAP50_95": float(best_row["metrics/mAP50-95(B)"]),
        },
        "last_validation_epoch": int(float(last_row["epoch"])),
        "last_validation_metrics": {
            "precision": float(last_row["metrics/precision(B)"]),
            "recall": float(last_row["metrics/recall(B)"]),
            "mAP50": float(last_row["metrics/mAP50(B)"]),
            "mAP50_95": float(last_row["metrics/mAP50-95(B)"]),
        },
    }


def _train_model(run_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Ultralytics is not installed. Run this script with "
            "`uv run --with ultralytics --with onnx python scripts/train_local_detector.py ...` "
            "or use --prepare-only."
        ) from exc

    dataset_yaml = run_dir / "dataset.yaml"
    training_project = run_dir / "train"
    run_name = "detector"
    model = YOLO(args.model)

    model.train(
        data=str(dataset_yaml),
        project=str(training_project),
        name=run_name,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        workers=args.workers,
        device=args.device,
        seed=args.seed,
        exist_ok=True,
        verbose=True,
    )

    weights_dir = training_project / run_name / "weights"
    best_weights = weights_dir / "best.pt"
    last_weights = weights_dir / "last.pt"
    exports_dir = run_dir / "exports"
    training_summary: dict[str, Any] = {
        "project_dir": str(training_project / run_name),
        "best_weights": _copy_if_exists(best_weights, exports_dir / "best.pt"),
        "last_weights": _copy_if_exists(last_weights, exports_dir / "last.pt"),
    }
    training_summary["validation"] = _read_training_results(training_project / run_name)

    if not args.no_export_onnx and best_weights.exists():
        best_model = YOLO(str(best_weights))
        exported = best_model.export(format="onnx", imgsz=args.imgsz)
        exported_path = Path(str(exported))
        training_summary["onnx_model"] = _copy_if_exists(exported_path, exports_dir / "best.onnx")
    else:
        training_summary["onnx_model"] = None

    benchmark_model_path = Path(training_summary["onnx_model"]) if isinstance(training_summary.get("onnx_model"), str) else best_weights
    if benchmark_model_path.exists():
        training_summary["benchmark"] = _benchmark_model(run_dir, model_path=benchmark_model_path, imgsz=args.imgsz)
    else:
        training_summary["benchmark"] = None

    return training_summary


def main() -> int:
    args = _parse_args()
    training_root = Path(args.training_root).resolve()
    output_root = Path(args.output_root).resolve()
    if not training_root.exists():
        raise SystemExit(f"Training root does not exist: {training_root}")

    accepted, skipped = collect_samples(training_root, limit=args.limit, seed=args.seed)
    if not accepted:
        raise SystemExit("No valid classification-chamber samples with completed pseudo-labels were found.")

    run_dir = prepare_run_dir(output_root, args.name)
    splits = split_samples(
        accepted,
        val_fraction=args.val_fraction,
        test_fraction=args.test_fraction,
        seed=args.seed,
    )
    dataset_paths = _prepare_dataset(run_dir, splits)

    summary_path = run_dir / "run.json"
    training_summary: dict[str, Any] | None = None
    training_error: str | None = None
    if not args.prepare_only:
        try:
            training_summary = _train_model(run_dir, args)
        except Exception as exc:
            training_error = str(exc)

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
            else {
                "error": training_error,
                "partial": training_summary,
            }
        ),
    )

    if training_error is not None:
        raise SystemExit(
            f"Dataset prepared at {run_dir}, but training failed: {training_error}. "
            f"See {summary_path} for the run manifest."
        )

    output = {
        "ok": True,
        "run_dir": str(run_dir),
        "dataset_yaml": dataset_paths["dataset_yaml"],
        "run_summary": str(summary_path),
        "sample_count": len(accepted),
        "prepared_only": bool(args.prepare_only),
        "training": training_summary,
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
