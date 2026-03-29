from __future__ import annotations

import argparse
import csv
import json
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
    prepare_run_dir,
    split_samples,
    write_manifest,
)


CLIENT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = CLIENT_ROOT / "blob" / "litert_detection_models"
SPLIT_NAME_MAP = {
    "train": "TRAINING",
    "val": "VALIDATION",
    "test": "TEST",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a timestamped LiteRT/TFLite EfficientDet detector run from classification-chamber "
            "samples. By default this prepares a CSV dataset and trains a quantized TFLite model if "
            "TensorFlow Lite Model Maker is available."
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
        help="Where to create timestamped LiteRT detector run directories.",
    )
    parser.add_argument(
        "--name",
        default="classification-chamber-piece-detector-litert",
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
        help="Only build the dataset CSV/manifest; do not start training.",
    )
    parser.add_argument(
        "--model-spec",
        default="efficientdet_lite0",
        help="Model Maker EfficientDet spec name, e.g. efficientdet_lite0.",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=50,
        help="Training epochs when training is enabled.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Training batch size.",
    )
    parser.add_argument(
        "--steps-per-execution",
        type=int,
        default=1,
        help="Optional EfficientDet spec steps_per_execution override.",
    )
    parser.add_argument(
        "--tflite-max-detections",
        type=int,
        default=25,
        help="Maximum detections encoded into the exported TFLite model.",
    )
    parser.add_argument(
        "--head-only",
        action="store_true",
        help="Train only the detection head instead of fine-tuning the whole model.",
    )
    parser.add_argument(
        "--quantization",
        choices=("int8", "float16"),
        default="int8",
        help="Post-training quantization mode for the exported TFLite model.",
    )
    parser.add_argument(
        "--tflite-filename",
        default="model.tflite",
        help="Filename for the exported TFLite model.",
    )
    parser.add_argument(
        "--omit-negative-images",
        action="store_true",
        help="Do not include empty-tray images as CSV rows. Use if DataLoader.from_csv rejects them.",
    )
    parser.add_argument(
        "--no-export-saved-model",
        action="store_true",
        help="Skip SavedModel export and keep only the TFLite artifact.",
    )
    parser.add_argument(
        "--skip-tflite-eval",
        action="store_true",
        help="Skip evaluate_tflite() after export.",
    )
    args = parser.parse_args()
    if args.val_fraction < 0 or args.test_fraction < 0:
        parser.error("Split fractions must be non-negative.")
    if (args.val_fraction + args.test_fraction) >= 1.0:
        parser.error("Validation + test fraction must be below 1.0.")
    if args.limit < 0:
        parser.error("--limit must be >= 0.")
    if args.epochs <= 0:
        parser.error("--epochs must be > 0.")
    if args.batch_size <= 0:
        parser.error("--batch-size must be > 0.")
    if args.steps_per_execution <= 0:
        parser.error("--steps-per-execution must be > 0.")
    if args.tflite_max_detections <= 0:
        parser.error("--tflite-max-detections must be > 0.")
    return args


def _csv_row_for_bbox(split_name: str, image_path: str, bbox: tuple[float, float, float, float]) -> list[str]:
    x_min, y_min, x_max, y_max = bbox
    return [
        split_name,
        image_path,
        "piece",
        f"{x_min:.6f}",
        f"{y_min:.6f}",
        "",
        "",
        f"{x_max:.6f}",
        f"{y_max:.6f}",
        "",
        "",
    ]


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def _prepare_dataset(
    run_dir: Path,
    splits: dict[str, list[PreparedSample]],
    *,
    include_negative_images: bool,
) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.jsonl"
    dataset_root, manifest_records = materialize_split_images(run_dir, splits)
    all_rows: list[list[str]] = []
    rows_by_split: dict[str, list[list[str]]] = {
        "train": [],
        "val": [],
        "test": [],
    }
    negative_rows = 0

    for record in manifest_records:
        split_name = str(record["split"])
        csv_split_name = SPLIT_NAME_MAP[split_name]
        dataset_image = str(record["dataset_image"])
        polygons = parse_segmentation_label(Path(str(record["segmentation_label_path"])))
        if not polygons:
            record["csv_row_count"] = 0
            if include_negative_images:
                row = [csv_split_name, dataset_image]
                rows_by_split[split_name].append(row)
                all_rows.append(row)
                record["csv_row_count"] = 1
                negative_rows += 1
            continue

        rows = [_csv_row_for_bbox(csv_split_name, dataset_image, polygon_to_bbox(polygon)) for polygon in polygons]
        rows_by_split[split_name].extend(rows)
        all_rows.extend(rows)
        record["csv_row_count"] = len(rows)

    csv_path = dataset_root / "annotations.csv"
    split_csv_paths = {
        "train": dataset_root / "train.csv",
        "val": dataset_root / "val.csv",
        "test": dataset_root / "test.csv",
    }
    _write_csv(csv_path, all_rows)
    for split_name, split_path in split_csv_paths.items():
        _write_csv(split_path, rows_by_split[split_name])
    write_manifest(manifest_path, manifest_records)

    return {
        "dataset_root": str(dataset_root),
        "dataset_csv": str(csv_path),
        "train_csv": str(split_csv_paths["train"]),
        "val_csv": str(split_csv_paths["val"]),
        "test_csv": str(split_csv_paths["test"]),
        "manifest_path": str(manifest_path),
        "negative_csv_rows": negative_rows,
        "negative_images_included": bool(include_negative_images),
    }


def _copy_tflite_artifacts(exports_dir: Path) -> dict[str, Any]:
    tflite_models = sorted(exports_dir.glob("*.tflite"))
    text_files = sorted(exports_dir.glob("*.txt"))
    saved_models = sorted(path for path in exports_dir.iterdir() if path.is_dir() and path.name.startswith("saved_model"))
    return {
        "tflite_model": str(tflite_models[0]) if tflite_models else None,
        "additional_tflite_models": [str(path) for path in tflite_models[1:]],
        "label_files": [str(path) for path in text_files],
        "saved_model_dir": str(saved_models[0]) if saved_models else None,
    }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return _jsonable(value.tolist())
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    return str(value)


def _train_model(run_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    try:
        from tflite_model_maker import model_spec, object_detector
        from tflite_model_maker.config import ExportFormat, QuantizationConfig
    except ImportError as exc:
        raise RuntimeError(
            "TensorFlow Lite Model Maker is not installed. Run this script with "
            "`uv run --with tflite-model-maker --with tensorflow python scripts/train_litert_detector.py ...` "
            "or use --prepare-only."
        ) from exc

    csv_path = run_dir / "dataset" / "annotations.csv"
    train_data, validation_data, test_data = object_detector.DataLoader.from_csv(str(csv_path))

    spec = model_spec.get(args.model_spec)
    spec.config.steps_per_execution = args.steps_per_execution
    spec.config.tflite_max_detections = args.tflite_max_detections

    model = object_detector.create(
        train_data,
        model_spec=spec,
        batch_size=args.batch_size,
        epochs=args.epochs,
        train_whole_model=not args.head_only,
        validation_data=validation_data,
    )

    exports_dir = run_dir / "exports"
    export_format = [ExportFormat.TFLITE, ExportFormat.LABEL]
    if not args.no_export_saved_model:
        export_format.append(ExportFormat.SAVED_MODEL)

    export_kwargs: dict[str, Any] = {
        "export_dir": str(exports_dir),
        "export_format": export_format,
        "tflite_filename": args.tflite_filename,
    }
    if args.quantization == "float16":
        export_kwargs["quantization_config"] = QuantizationConfig.for_float16()
    model.export(**export_kwargs)

    artifacts = _copy_tflite_artifacts(exports_dir)
    tflite_model = artifacts["tflite_model"]

    training_summary: dict[str, Any] = {
        "framework": "tflite_model_maker",
        "model_spec": args.model_spec,
        "quantization": args.quantization,
        "artifacts": artifacts,
        "eval": _jsonable(model.evaluate(test_data)),
    }

    if tflite_model is not None and not args.skip_tflite_eval:
        training_summary["eval_tflite"] = _jsonable(model.evaluate_tflite(tflite_model, test_data))
    else:
        training_summary["eval_tflite"] = None

    return training_summary


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
        "runtime": "litert_tflite",
        "training_root": str(Path(args.training_root).resolve()),
        "sample_count": sample_count,
        "skipped_samples": skipped,
        "splits": {name: dataset_stats(items) for name, items in splits.items()},
        "dataset": dataset_paths,
        "train_args": {
            "prepare_only": args.prepare_only,
            "model_spec": args.model_spec,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "steps_per_execution": args.steps_per_execution,
            "tflite_max_detections": args.tflite_max_detections,
            "train_whole_model": not args.head_only,
            "quantization": args.quantization,
            "tflite_filename": args.tflite_filename,
            "seed": args.seed,
            "val_fraction": args.val_fraction,
            "test_fraction": args.test_fraction,
            "limit": args.limit,
            "omit_negative_images": args.omit_negative_images,
            "export_saved_model": not args.no_export_saved_model,
            "skip_tflite_eval": args.skip_tflite_eval,
        },
        "training": training,
    }
    summary_path.write_text(json.dumps(payload, indent=2))


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
    dataset_paths = _prepare_dataset(
        run_dir,
        splits,
        include_negative_images=not args.omit_negative_images,
    )

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
        "dataset_csv": dataset_paths["dataset_csv"],
        "run_summary": str(summary_path),
        "sample_count": len(accepted),
        "prepared_only": bool(args.prepare_only),
        "training": training_summary,
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
