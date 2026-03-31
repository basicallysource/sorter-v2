from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from model_identity import build_model_identity, compute_dataset_fingerprint, slugify


CLIENT_ROOT = Path(__file__).resolve().parents[1]
BLOB_DIR = CLIENT_ROOT / "blob"
LOCAL_DETECTION_ROOT = BLOB_DIR / "local_detection_models"
DEFAULT_SOURCE_ROOT = BLOB_DIR / "vastai_results" / "track_a-33834400" / "results"
DEFAULT_TRACK_RESULTS = DEFAULT_SOURCE_ROOT / "track_a_results.json"
DEFAULT_TRAINING_PLAN = BLOB_DIR / "vastai_upload" / "_staging" / "training_plan.json"
DEFAULT_DATASET_DIR = BLOB_DIR / "vastai_upload" / "_staging" / "dataset"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import successful Vast.ai Track A NCNN exports into local_detection_models.")
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT), help="Directory containing the copied Vast.ai Track A artifacts.")
    parser.add_argument("--track-results", default=str(DEFAULT_TRACK_RESULTS), help="Path to track_a_results.json.")
    parser.add_argument("--training-plan", default=str(DEFAULT_TRAINING_PLAN), help="Path to the generated training_plan.json.")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR), help="Prepared dataset directory used for the run.")
    parser.add_argument("--output-root", default=str(LOCAL_DETECTION_ROOT), help="Local detector catalog root.")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object at {path}")
    return payload


def _copy_if_exists(src: Path, dst: Path) -> str | None:
    if not src.exists() or not src.is_file():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst.resolve())


def _load_track_a_catalog(training_plan_path: Path, dataset_dir: Path) -> dict[str, dict[str, Any]]:
    if training_plan_path.exists():
        payload = _read_json(training_plan_path)
        tracks = payload.get("tracks")
        if isinstance(tracks, list):
            for track in tracks:
                if not isinstance(track, dict) or track.get("name") != "track_a":
                    continue
                models = track.get("models")
                if not isinstance(models, list):
                    break
                catalog: dict[str, dict[str, Any]] = {}
                for model in models:
                    if not isinstance(model, dict):
                        continue
                    model_id = model.get("model_id")
                    if isinstance(model_id, str) and model_id:
                        catalog[model_id] = model
                if catalog:
                    return catalog

    dataset_fingerprint = compute_dataset_fingerprint(dataset_dir) if dataset_dir.exists() else "unknown"
    fallback_specs = {
        "A1": ("yolo", "yolo26n", 320),
        "A2": ("yolo", "yolo26n", 416),
        "A3": ("yolo", "yolo11n", 320),
        "A4": ("yolo", "yolo11n", 416),
        "A5": ("yolo", "yolo11s", 320),
        "A6": ("yolo", "yolov8n", 320),
    }
    catalog = {}
    for model_id, (family, base_model, imgsz) in fallback_specs.items():
        catalog[model_id] = build_model_identity(
            model_id=model_id,
            family=family,
            base_model=base_model,
            dataset_fingerprint=dataset_fingerprint,
            imgsz=imgsz,
            epochs=300,
        ).to_dict()
    return catalog


def _build_run_id(identity: dict[str, Any], model_name: str) -> str:
    technical = slugify(str(identity.get("technical_name") or model_name))
    nickname = slugify(str(identity.get("nickname") or identity.get("primary_name") or "imported-model"))
    return f"20260330-vastai-{str(identity.get('model_id', 'model')).lower()}-{nickname}-{technical}-ncnn"


def _write_run_summary(
    path: Path,
    *,
    identity: dict[str, Any],
    result: dict[str, Any],
    source_root: Path,
    dest_model_dir: Path,
    dest_onnx_path: str | None,
    dest_weights_path: str | None,
) -> None:
    payload = {
        "created_at": time.time(),
        "run_name": str(identity.get("display_name") or identity.get("primary_name") or identity.get("model_id")),
        "runtime": "ncnn",
        "model_family": "yolo",
        "source": {
            "provider": "vastai",
            "track": "track_a",
            "source_root": str(source_root.resolve()),
        },
        "train_args": {
            "imgsz": int(result.get("imgsz", identity.get("imgsz") or 640)),
            "model": result.get("model") or identity.get("base_model"),
            "epochs": int(identity.get("epochs") or 300),
            "imported": True,
        },
        "inference": {
            "backend": "ultralytics",
            "family": "yolo",
            "imgsz": int(result.get("imgsz", identity.get("imgsz") or 640)),
        },
        "training": {
            "framework": "ultralytics",
            "runtime": "ncnn",
            "model_id": identity.get("model_id"),
            "base_model": identity.get("base_model"),
            "technical_name": identity.get("technical_name"),
            "technical_label": identity.get("technical_label"),
            "primary_name": identity.get("primary_name"),
            "nickname": identity.get("nickname"),
            "short_code": identity.get("short_code"),
            "display_name": identity.get("display_name"),
            "best_metrics": result.get("best_metrics"),
            "epochs_completed": result.get("total_epochs"),
            "train_elapsed_min": result.get("train_elapsed_min"),
            "ncnn_model_dir": str(dest_model_dir.resolve()),
            "onnx_model": dest_onnx_path,
            "best_weights": dest_weights_path,
            "source_results_json": str((source_root / "track_a_results.json").resolve()),
            "source_result_name": result.get("name"),
        },
    }
    path.write_text(json.dumps(payload, indent=2))


def main() -> int:
    args = _parse_args()
    source_root = Path(args.source_root).resolve()
    results_path = Path(args.track_results).resolve()
    training_plan_path = Path(args.training_plan).resolve()
    dataset_dir = Path(args.dataset_dir).resolve()
    output_root = Path(args.output_root).resolve()

    if not source_root.exists():
        raise FileNotFoundError(f"Source root not found: {source_root}")
    if not results_path.exists():
        raise FileNotFoundError(f"Track results file not found: {results_path}")

    results = _read_json(results_path)
    catalog = _load_track_a_catalog(training_plan_path, dataset_dir)

    imported: list[dict[str, str]] = []
    output_root.mkdir(parents=True, exist_ok=True)

    for model_id in sorted(results):
        result = results.get(model_id)
        if not isinstance(result, dict):
            continue
        if int(result.get("train_returncode", 1)) != 0 or not bool(result.get("ncnn_exported")):
            continue

        model_name = str(result.get("name") or "").strip()
        if not model_name:
            continue

        source_ncnn_dir = source_root / f"{model_id}-{model_name}-ncnn"
        if not source_ncnn_dir.exists() or not source_ncnn_dir.is_dir():
            continue

        identity = catalog.get(model_id) or {}
        run_id = _build_run_id(identity, model_name)
        run_dir = output_root / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir)

        exports_dir = run_dir / "exports"
        dest_model_dir = exports_dir / "best_ncnn_model"
        dest_model_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_ncnn_dir, dest_model_dir)

        dest_onnx_path = _copy_if_exists(source_root / f"{model_id}-{model_name}-best.onnx", exports_dir / "best.onnx")
        dest_weights_path = _copy_if_exists(source_root / f"{model_id}-{model_name}-best.pt", exports_dir / "best.pt")
        _write_run_summary(
            run_dir / "run.json",
            identity=identity,
            result=result,
            source_root=source_root,
            dest_model_dir=dest_model_dir,
            dest_onnx_path=dest_onnx_path,
            dest_weights_path=dest_weights_path,
        )
        imported.append(
            {
                "run_id": run_id,
                "label": str(identity.get("display_name") or model_name),
                "model_dir": str(dest_model_dir.resolve()),
            }
        )

    print(json.dumps({"imported_count": len(imported), "models": imported}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
