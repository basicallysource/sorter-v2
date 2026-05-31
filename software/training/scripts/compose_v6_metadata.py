"""Compose Hive-shaped training_metadata for the v6 run without audit/precheck.

The full build_hive_model_report.py needs holdout audit + sample progress data
which we don't have for this run. This composes the same structure with the
parts we *do* have (dataset/model/selection) so the Hive UI cards render.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "runs" / "20260517-092535-c_channel_full-yolo-v6_maxout_score095"
DATASET_DIR = ROOT / "datasets" / "c_channel_full" / "v6_maxout_score095"
BENCH_PATH = ROOT / "reports_out" / "device_benchmarks" / "local_v6_yolo26s_20260517.json"


def main() -> None:
    build = json.loads((DATASET_DIR / "build.json").read_text())
    track = json.loads((RUN_DIR / "track_a_results.json").read_text())["A7"]
    bench = json.loads(BENCH_PATH.read_text())[0]

    selected_ids = (
        sorted(p.stem for p in (DATASET_DIR / "labels" / "train").glob("*.txt"))
        + sorted(p.stem for p in (DATASET_DIR / "labels" / "val").glob("*.txt"))
    )

    metadata = {
        "schema_version": 1,
        "report_type": "sorter_detection_model_training_report",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "name": track["name"],
            "family": "yolo",
            "imgsz": track["imgsz"],
            "source_model": track["model"],
            "best_metrics": track["best_metrics"],
            "training": {
                "elapsed_min": track["train_elapsed_min"],
                "total_epochs": track["total_epochs"],
                "best_epoch": track["best_metrics"]["epoch"],
            },
            "artifacts": {
                "onnx_size_kb": track["best.onnx_size_kb"],
                "pt_size_kb": track["best.pt_size_kb"],
                "ncnn_exported": track["ncnn_exported"],
            },
        },
        "dataset": {
            "name": build["dataset_name"],
            "zone": build["zone"],
            "sample_fingerprint": build.get("sample_fingerprint"),
            "train_samples": build["train_samples"],
            "val_samples": build["val_samples"],
            "train_ratio": build["train_ratio"],
            "classes": build["classes"],
            "min_detection_score": build["min_detection_score"],
            "kept_empty_samples": build.get("piece_count_counts", {}).get("selected", {}).get("0"),
            "max_empty_fraction": build.get("max_empty_fraction"),
            "empty_cap": build.get("empty_cap"),
            "selection": {
                "target_size": build["train_samples"] + build["val_samples"],
                "seed": build["seed"],
                "balance_source_role": build["balance_source_role"],
                "balance_piece_count": build["balance_piece_count"],
                "piece_count_bins": build.get("piece_count_bins"),
                "strict_balance": build.get("strict_balance"),
                "skipped_low_score": build["skipped_low_score"],
                "skipped_missing_score": build["skipped_missing_score"],
                "skipped_no_boxes": build["skipped_no_boxes"],
                "source_role_counts": build["source_role_counts"],
                "piece_count_counts": build["piece_count_counts"],
                "balance_group_counts": build.get("balance_group_counts"),
                "diversity": build.get("diversity"),
            },
        },
        "precheck": {},
        "audit": {"manifest": None, "summaries": []},
        "count_spectrum": [],
        "benchmarks": {
            "local_mac": {
                "host": bench["host"],
                "benchmarked_at": bench["benchmarked_at"],
                "input_shape": bench["CPUExecutionProvider"]["input_shape"],
                "iterations": bench["CPUExecutionProvider"]["iterations"],
                "cpu_onnxruntime": {
                    k: bench["CPUExecutionProvider"][k]
                    for k in ("mean_ms", "p95_ms", "median_ms", "fps_mean")
                },
                "coreml_onnxruntime": {
                    k: bench["CoreMLExecutionProvider"][k]
                    for k in ("mean_ms", "p95_ms", "median_ms", "fps_mean")
                },
            }
        },
        "variant_sizes_bytes": bench["variant_sizes_bytes"],
    }

    # Update run.json: top-level training_metadata is what publish.py sends.
    run_json_path = RUN_DIR / "run.json"
    run = json.loads(run_json_path.read_text())
    run["training_metadata"] = metadata
    run_json_path.write_text(json.dumps(run, indent=2))
    print(f"updated {run_json_path}")
    print(f"selection.target_size={metadata['dataset']['selection']['target_size']}")
    print(f"source roles: {list(metadata['dataset']['selection']['source_role_counts']['selected'].keys())}")
    print(f"piece buckets: {list(metadata['dataset']['selection']['piece_count_counts']['selected'].keys())}")


if __name__ == "__main__":
    main()
