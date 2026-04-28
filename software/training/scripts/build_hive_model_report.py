#!/usr/bin/env python3
"""Build Hive-ready training metadata for a detection model."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _label_ids(dataset_dir: Path, split: str) -> list[str]:
    return sorted(path.stem for path in (dataset_dir / "labels" / split).glob("*.txt"))


def _copy_optional(src: Path, dst: Path) -> str | None:
    if not src.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def _compact_progress(progress: dict[str, Any]) -> dict[str, Any]:
    return {
        "created_at": progress.get("created_at"),
        "min_detection_score": progress.get("min_detection_score"),
        "totals": progress.get("totals"),
        "role_status": progress.get("role_status"),
        "strict_positive_role_balanced_capacity": progress.get("strict_positive_role_balanced_capacity"),
        "missing_by_target": progress.get("missing_by_target"),
        "bucket_coverage_by_role": progress.get("bucket_coverage_by_role"),
        "image_coverage_by_role": progress.get("image_coverage_by_role"),
    }


def _best_model_summary(track_results: dict[str, Any], model_key: str | None) -> dict[str, Any]:
    if model_key and model_key in track_results:
        return track_results[model_key]
    if len(track_results) == 1:
        return next(iter(track_results.values()))
    return track_results


def _filter_audit(summary: dict[str, Any], model_name: str) -> dict[str, Any]:
    rows = [
        row
        for row in summary.get("summaries", [])
        if isinstance(row, dict) and row.get("model") == model_name
    ]
    return {
        "manifest": summary.get("manifest"),
        "summaries": rows,
    }


def _filter_spectrum(rows: list[dict[str, Any]], model_name: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("model") == model_name]


def _prepare_publish_run(
    *,
    output_dir: Path,
    source_run_dir: Path,
    model_name: str,
    family: str,
    dataset_dir: Path,
    report_path: Path,
    model_key: str | None,
    training_metadata: dict[str, Any],
) -> None:
    exports_dir = output_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    onnx_candidates = sorted(source_run_dir.glob("*best.onnx"))
    pt_candidates = sorted(source_run_dir.glob("*best.pt"))
    ncnn_candidates = [path for path in source_run_dir.iterdir() if path.is_dir() and "ncnn" in path.name.lower()]
    log_candidates = sorted(source_run_dir.glob("*.train.log"))

    if onnx_candidates:
        shutil.copy2(onnx_candidates[0], exports_dir / "best.onnx")
    if pt_candidates:
        shutil.copy2(pt_candidates[0], exports_dir / "best.pt")
    if ncnn_candidates:
        target_ncnn = exports_dir / ncnn_candidates[0].name
        if target_ncnn.exists():
            shutil.rmtree(target_ncnn)
        shutil.copytree(ncnn_candidates[0], target_ncnn)
    if log_candidates:
        shutil.copy2(log_candidates[0], output_dir / log_candidates[0].name)
    shutil.copy2(report_path, output_dir / "training_metadata.json")

    run_payload = {
        "run_name": model_name,
        "model_family": family,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "path": str(dataset_dir),
            "name": dataset_dir.name,
        },
        "source_run_dir": str(source_run_dir),
        "model_key": model_key,
        "training_metadata": training_metadata,
        "training": {
            "onnx_model": "exports/best.onnx" if (exports_dir / "best.onnx").exists() else None,
            "ncnn_model_dir": (
                f"exports/{ncnn_candidates[0].name}" if ncnn_candidates else None
            ),
            "pytorch_model": "exports/best.pt" if (exports_dir / "best.pt").exists() else None,
        },
        "inference": {
            "family": family,
            "imgsz": training_metadata.get("model", {}).get("imgsz"),
        },
    }
    _write_json(output_dir / "run.json", run_payload)


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    dataset_dir = args.dataset_dir.resolve()
    source_run_dir = args.source_run_dir.resolve()
    audit_dir = args.audit_dir.resolve()
    progress_path = args.progress_json.resolve()
    output_path = args.output.resolve()

    build_json = _read_json(dataset_dir / "build.json")
    progress = _read_json(progress_path) if progress_path.exists() else {}
    track_results = _read_json(source_run_dir / "track_a_results.json")
    audit_summary = _read_json(audit_dir / "summary.json")
    spectrum_rows = _read_json(audit_dir / "count_spectrum_summary.json")

    train_ids = _label_ids(dataset_dir, "train")
    val_ids = _label_ids(dataset_dir, "val")
    model_summary = _best_model_summary(track_results, args.model_key)
    model_name = args.model_name or str(model_summary.get("name") or source_run_dir.name)

    metadata = {
        "schema_version": 1,
        "report_type": "sorter_detection_model_training_report",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "name": model_name,
            "family": args.family,
            "imgsz": model_summary.get("imgsz"),
            "source_model": model_summary.get("model"),
            "best_metrics": model_summary.get("best_metrics"),
            "training": {
                "elapsed_min": model_summary.get("train_elapsed_min"),
                "total_epochs": model_summary.get("total_epochs"),
                "best_epoch": (model_summary.get("best_metrics") or {}).get("epoch")
                if isinstance(model_summary.get("best_metrics"), dict)
                else None,
            },
            "artifacts": {
                "onnx_size_kb": model_summary.get("best.onnx_size_kb"),
                "pt_size_kb": model_summary.get("best.pt_size_kb"),
                "ncnn_exported": model_summary.get("ncnn_exported"),
            },
        },
        "dataset": {
            "name": build_json.get("dataset_name"),
            "zone": build_json.get("zone"),
            "path": str(dataset_dir),
            "sample_fingerprint": build_json.get("sample_fingerprint"),
            "train_samples": build_json.get("train_samples"),
            "val_samples": build_json.get("val_samples"),
            "train_ratio": build_json.get("train_ratio"),
            "classes": build_json.get("classes"),
            "min_detection_score": build_json.get("min_detection_score"),
            "kept_empty_samples": build_json.get("piece_count_counts", {}).get("selected", {}).get("0")
            if isinstance(build_json.get("piece_count_counts"), dict)
            else None,
            "selected_sample_ids": {
                "train": train_ids,
                "val": val_ids,
            },
            "selection": {
                "target_size": len(train_ids) + len(val_ids),
                "seed": build_json.get("seed"),
                "balance_source_role": build_json.get("balance_source_role"),
                "balance_piece_count": build_json.get("balance_piece_count"),
                "piece_count_bins": build_json.get("piece_count_bins"),
                "strict_balance": build_json.get("strict_balance")
                or build_json.get("strict_source_role_balance"),
                "skipped_low_score": build_json.get("skipped_low_score"),
                "skipped_missing_score": build_json.get("skipped_missing_score"),
                "skipped_no_boxes": build_json.get("skipped_no_boxes"),
                "source_role_counts": build_json.get("source_role_counts"),
                "piece_count_counts": build_json.get("piece_count_counts"),
                "balance_group_counts": build_json.get("balance_group_counts"),
                "diversity": build_json.get("diversity"),
            },
        },
        "precheck": _compact_progress(progress),
        "audit": _filter_audit(audit_summary, model_name),
        "count_spectrum": _filter_spectrum(spectrum_rows, model_name),
        "source_files": {
            "dataset_build": str(dataset_dir / "build.json"),
            "progress_precheck": str(progress_path),
            "track_results": str(source_run_dir / "track_a_results.json"),
            "audit_summary": str(audit_dir / "summary.json"),
            "count_spectrum": str(audit_dir / "count_spectrum_summary.json"),
        },
    }
    _write_json(output_path, metadata)

    if args.publish_run_dir:
        _prepare_publish_run(
            output_dir=args.publish_run_dir.resolve(),
            source_run_dir=source_run_dir,
            model_name=model_name,
            family=args.family,
            dataset_dir=dataset_dir,
            report_path=output_path,
            model_key=args.model_key,
            training_metadata=metadata,
        )

    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--source-run-dir", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--progress-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publish-run-dir", type=Path)
    parser.add_argument("--model-key", default=None)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--family", default="yolo")
    args = parser.parse_args()
    metadata = build_report(args)
    print(json.dumps({
        "output": str(args.output),
        "model": metadata["model"]["name"],
        "selected_samples": len(metadata["dataset"]["selected_sample_ids"]["train"])
        + len(metadata["dataset"]["selected_sample_ids"]["val"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
