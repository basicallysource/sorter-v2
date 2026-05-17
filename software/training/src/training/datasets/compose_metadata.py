"""Compose the standard Hive-shaped training_metadata for a publish run.

Reads:
  - <dataset_dir>/build.json
  - <run_dir>/track_a_results.json (or first matching) for best metrics
  - optional benchmark JSON in the format produced by
    scripts/benchmark_v6_local.py (a list with CPU/CoreML providers)

Writes the structured payload into <run_dir>/run.json under
``training_metadata`` so ``train publish`` ships it directly.

The structure matches what
``software/hive/frontend/src/lib/components/ModelTrainingReport.svelte``
reads (``metadata.model.*``, ``metadata.dataset.selection.*``,
``metadata.benchmarks.local_mac.*``, ``metadata.variant_sizes_bytes``).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _pick_track_results(run_dir: Path, model_key: str | None) -> tuple[str, dict[str, Any]]:
    """Pick the (model_id, results) tuple from a track_*_results.json file."""
    candidates = sorted(run_dir.glob("track_*_results.json"))
    if not candidates:
        raise SystemExit(f"no track_*_results.json under {run_dir}")
    payload = _read_json(candidates[0])
    if not isinstance(payload, dict) or not payload:
        raise SystemExit(f"empty track results: {candidates[0]}")
    if model_key:
        if model_key not in payload:
            raise SystemExit(f"model_key {model_key} not present in {candidates[0]}")
        return model_key, payload[model_key]
    # Default: first entry (usually the only model when the run targeted one id)
    first_key = next(iter(payload))
    return first_key, payload[first_key]


def _variant_sizes(run_dir: Path) -> dict[str, int]:
    sizes: dict[str, int] = {}
    onnx = next(run_dir.rglob("*best.onnx"), None) or next((run_dir / "exports").glob("best.onnx"), None) if (run_dir / "exports").exists() else next(run_dir.rglob("*best.onnx"), None)
    pt = next(run_dir.rglob("*best.pt"), None)
    if onnx and onnx.exists():
        sizes["onnx"] = onnx.stat().st_size
    if pt and pt.exists():
        sizes["pytorch"] = pt.stat().st_size
    # NCNN bundle is a directory; sum file sizes inside
    for candidate in run_dir.rglob("*ncnn*"):
        if candidate.is_dir():
            total = sum(p.stat().st_size for p in candidate.glob("*") if p.is_file())
            if total > 0:
                sizes["ncnn"] = total
                break
    return sizes


def _benchmark_block(benchmark_json: Path | None) -> dict[str, Any] | None:
    if not benchmark_json or not benchmark_json.exists():
        return None
    payload = _read_json(benchmark_json)
    entry = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(entry, dict):
        return None
    cpu = entry.get("CPUExecutionProvider") or {}
    coreml = entry.get("CoreMLExecutionProvider") or {}
    if not cpu and not coreml:
        return None
    keep = ("mean_ms", "p95_ms", "median_ms", "fps_mean")

    def trim(src: dict[str, Any]) -> dict[str, Any]:
        return {k: src[k] for k in keep if k in src}

    block: dict[str, Any] = {
        "host": entry.get("host"),
        "benchmarked_at": entry.get("benchmarked_at"),
        "input_shape": (cpu or coreml).get("input_shape"),
        "iterations": (cpu or coreml).get("iterations"),
    }
    if cpu:
        block["cpu_onnxruntime"] = trim(cpu)
    if coreml:
        block["coreml_onnxruntime"] = trim(coreml)
    return {"local_mac": block}


def compose(
    *,
    run_dir: Path,
    dataset_dir: Path,
    benchmark_json: Path | None = None,
    model_key: str | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    dataset_dir = dataset_dir.resolve()
    build = _read_json(dataset_dir / "build.json")
    model_id, track = _pick_track_results(run_dir, model_key)
    best = track.get("best_metrics") or {}

    metadata: dict[str, Any] = {
        "schema_version": 1,
        "report_type": "sorter_detection_model_training_report",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "name": track.get("name") or model_id,
            "family": "yolo",
            "imgsz": track.get("imgsz"),
            "source_model": track.get("model"),
            "best_metrics": best,
            "training": {
                "elapsed_min": track.get("train_elapsed_min"),
                "total_epochs": track.get("total_epochs"),
                "best_epoch": best.get("epoch") if isinstance(best, dict) else None,
            },
            "artifacts": {
                "onnx_size_kb": track.get("best.onnx_size_kb"),
                "pt_size_kb": track.get("best.pt_size_kb"),
                "ncnn_exported": track.get("ncnn_exported"),
            },
        },
        "dataset": {
            "name": build.get("dataset_name"),
            "zone": build.get("zone"),
            "sample_fingerprint": build.get("sample_fingerprint"),
            "train_samples": build.get("train_samples"),
            "val_samples": build.get("val_samples"),
            "train_ratio": build.get("train_ratio"),
            "classes": build.get("classes"),
            "min_detection_score": build.get("min_detection_score"),
            "kept_empty_samples": (build.get("piece_count_counts") or {}).get("selected", {}).get("0"),
            "max_empty_fraction": build.get("max_empty_fraction"),
            "empty_cap": build.get("empty_cap"),
            "selection": {
                "target_size": (build.get("train_samples") or 0) + (build.get("val_samples") or 0),
                "seed": build.get("seed"),
                "balance_source_role": build.get("balance_source_role"),
                "balance_piece_count": build.get("balance_piece_count"),
                "piece_count_bins": build.get("piece_count_bins"),
                "strict_balance": build.get("strict_balance") or build.get("strict_source_role_balance"),
                "skipped_low_score": build.get("skipped_low_score"),
                "skipped_missing_score": build.get("skipped_missing_score"),
                "skipped_no_boxes": build.get("skipped_no_boxes"),
                "source_role_counts": build.get("source_role_counts"),
                "piece_count_counts": build.get("piece_count_counts"),
                "balance_group_counts": build.get("balance_group_counts"),
                "diversity": build.get("diversity"),
            },
        },
        "precheck": {},
        "audit": {"manifest": None, "summaries": []},
        "count_spectrum": [],
        "variant_sizes_bytes": _variant_sizes(run_dir),
    }

    benchmarks = _benchmark_block(benchmark_json)
    if benchmarks:
        metadata["benchmarks"] = benchmarks

    run_json_path = run_dir / "run.json"
    if not run_json_path.exists():
        raise SystemExit(f"missing {run_json_path}; create the run dir layout first")
    run = json.loads(run_json_path.read_text())
    run["training_metadata"] = metadata
    if not run.get("model_family"):
        run["model_family"] = "yolo"
    if not run.get("run_name"):
        run["run_name"] = track.get("name") or model_id
    run_json_path.write_text(json.dumps(run, indent=2))
    return metadata
