from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from blob_manager import BLOB_DIR


LOCAL_DETECTION_ROOT = BLOB_DIR / "local_detection_models"
LOCAL_DETECTOR_PREFIX = "local_detector:"


@dataclass(frozen=True)
class LocalDetectorModel:
    id: str
    run_id: str
    label: str
    run_dir: Path
    onnx_path: Path
    imgsz: int
    created_at: float
    model_family: str


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text())
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _safe_float(value: Any, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _safe_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _model_id_for_run(run_id: str) -> str:
    return f"{LOCAL_DETECTOR_PREFIX}{run_id}"


def is_local_detector_model_id(model_id: str | None) -> bool:
    return isinstance(model_id, str) and model_id.startswith(LOCAL_DETECTOR_PREFIX)


def _model_family(payload: dict[str, Any]) -> str:
    family = payload.get("model_family")
    if isinstance(family, str) and family.strip():
        return family.strip()
    training = payload.get("training")
    if isinstance(training, dict):
        family = training.get("model_family")
        if isinstance(family, str) and family.strip():
            return family.strip()
    return "yolo"


def _display_label(run_id: str, payload: dict[str, Any]) -> str:
    run_name = payload.get("run_name")
    family_label = _model_family(payload).replace("_", " ").title()
    if isinstance(run_name, str) and run_name.strip():
        return f"Local Detector - {run_name.strip()} ({family_label})"
    return f"Local Detector - {run_id} ({family_label})"


def list_local_detector_models() -> list[LocalDetectorModel]:
    if not LOCAL_DETECTION_ROOT.exists():
        return []

    models: list[LocalDetectorModel] = []
    for run_dir in sorted(
        (path for path in LOCAL_DETECTION_ROOT.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    ):
        run_json = _read_json(run_dir / "run.json")
        if run_json is None:
            continue

        training = run_json.get("training")
        if not isinstance(training, dict):
            continue

        onnx_value = training.get("onnx_model")
        onnx_path = Path(onnx_value) if isinstance(onnx_value, str) and onnx_value else (run_dir / "exports" / "best.onnx")
        if not onnx_path.exists() or not onnx_path.is_file():
            continue

        train_args = run_json.get("train_args")
        created_at = _safe_float(run_json.get("created_at"), default=run_dir.stat().st_mtime if run_dir.exists() else time.time())
        imgsz = _safe_int(train_args.get("imgsz") if isinstance(train_args, dict) else None, default=640)
        run_id = run_dir.name
        model_family = _model_family(run_json)

        models.append(
            LocalDetectorModel(
                id=_model_id_for_run(run_id),
                run_id=run_id,
                label=_display_label(run_id, run_json),
                run_dir=run_dir,
                onnx_path=onnx_path,
                imgsz=imgsz,
                created_at=created_at,
                model_family=model_family,
            )
        )
    return models


def get_local_detector_model(model_id: str | None) -> LocalDetectorModel | None:
    if not is_local_detector_model_id(model_id):
        return None
    for model in list_local_detector_models():
        if model.id == model_id:
            return model
    return None


def local_detector_model_options() -> list[dict[str, str]]:
    return [
        {
            "id": model.id,
            "label": model.label,
        }
        for model in list_local_detector_models()
    ]
