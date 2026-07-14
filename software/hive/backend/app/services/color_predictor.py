"""Serve piece-color predictions from an uploaded ONNX color classifier.

The active model (one global row in ``color_models``) replaces nothing on disk —
its bytes live in ``COLOR_MODEL_DIR`` and are uploaded out of band. Each ``.onnx``
is self-describing: a ``hive.*`` metadata block (baked in at export time) carries
the display name, input size, preprocess recipe, and the class-index → BrickLink
color-id map, so a dir scan needs no sidecar files.

Prediction path (per piece): read up to N crops from storage, resize to the model's
input size, scale to [0,1] (mean/std normalization is baked into the graph), run the
session, average the per-crop softmax, and map argmax → BrickLink color. Cheap: one
indexed DB lookup for the active row plus a cached session; no dir scan.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from PIL import Image
from sqlalchemy.orm import Session

from app.config import settings
from app.models.color_model import ColorModel
from app.services.profile_catalog import get_profile_catalog_service
from app.services.storage_backend import get_backend

log = logging.getLogger(__name__)

MAX_SAMPLES = 5
_HIVE_KIND = "color_classifier"


def model_dir() -> Path:
    return Path(settings.COLOR_MODEL_DIR)


@dataclass
class _Loaded:
    session: ort.InferenceSession
    input_name: str
    output_name: str
    input_size: int
    class_ids: list[int]


_lock = threading.Lock()
_session_cache: dict[tuple[str, str], _Loaded] = {}


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_metadata(path: Path) -> dict[str, str] | None:
    """Read the model's ``hive.*`` metadata via a throwaway ort session. Returns
    None when the file isn't a readable color classifier."""
    try:
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        sess = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
    except Exception as exc:
        log.warning("color model %s failed to load: %s", path.name, exc)
        return None
    meta = sess.get_modelmeta().custom_metadata_map or {}
    if meta.get("hive.kind") != _HIVE_KIND:
        log.warning("color model %s is not a %s (kind=%r)", path.name, _HIVE_KIND, meta.get("hive.kind"))
        return None
    return dict(meta)


def _parse_class_ids(meta: dict[str, str]) -> list[int]:
    try:
        return [int(x) for x in json.loads(meta.get("hive.classes", "[]"))]
    except (ValueError, TypeError):
        return []


def scan_models() -> list[dict[str, Any]]:
    """Every readable color classifier in COLOR_MODEL_DIR, with its metadata."""
    directory = model_dir()
    if not directory.exists():
        return []
    found: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.onnx")):
        meta = _read_metadata(path)
        if meta is None:
            continue
        class_ids = _parse_class_ids(meta)
        try:
            input_size = int(meta.get("hive.input_size", "0"))
        except ValueError:
            input_size = 0
        found.append(
            {
                "filename": path.name,
                "name": meta.get("hive.name") or path.stem,
                "description": meta.get("hive.description"),
                "kind": meta.get("hive.kind", _HIVE_KIND),
                "sha256": _sha256_of(path),
                "class_count": len(class_ids),
                "input_size": input_size,
                "file_size": path.stat().st_size,
                "meta": meta,
            }
        )
    return found


def reconcile(db: Session) -> list[ColorModel]:
    """Sync color_models rows to the files on disk: insert new, refresh changed
    (sha differs), drop vanished. Returns all rows after reconciliation."""
    scanned = {m["filename"]: m for m in scan_models()}
    existing = {row.filename: row for row in db.query(ColorModel).all()}

    for filename, m in scanned.items():
        row = existing.get(filename)
        if row is None:
            db.add(
                ColorModel(
                    filename=filename,
                    name=m["name"],
                    description=m["description"],
                    kind=m["kind"],
                    sha256=m["sha256"],
                    class_count=m["class_count"],
                    input_size=m["input_size"],
                    file_size=m["file_size"],
                    meta=m["meta"],
                )
            )
        elif row.sha256 != m["sha256"]:
            row.name = m["name"]
            row.description = m["description"]
            row.kind = m["kind"]
            row.sha256 = m["sha256"]
            row.class_count = m["class_count"]
            row.input_size = m["input_size"]
            row.file_size = m["file_size"]
            row.meta = m["meta"]

    for filename, row in existing.items():
        if filename not in scanned:
            db.delete(row)

    db.commit()
    return db.query(ColorModel).order_by(ColorModel.name.asc()).all()


def get_active(db: Session) -> ColorModel | None:
    return db.query(ColorModel).filter(ColorModel.is_active.is_(True)).first()


def set_active(db: Session, model_id, active: bool) -> ColorModel | None:
    row = db.query(ColorModel).filter(ColorModel.id == model_id).first()
    if row is None:
        return None
    if active:
        # Global single-active invariant: clear everyone else first.
        db.query(ColorModel).filter(ColorModel.id != model_id, ColorModel.is_active.is_(True)).update(
            {ColorModel.is_active: False}
        )
        row.is_active = True
    else:
        row.is_active = False
    db.commit()
    db.refresh(row)
    return row


def _load(row: ColorModel) -> _Loaded | None:
    path = model_dir() / row.filename
    if not path.exists():
        return None
    key = (row.filename, row.sha256)
    with _lock:
        cached = _session_cache.get(key)
        if cached is not None:
            return cached
    meta = _read_metadata(path)
    if meta is None:
        return None
    class_ids = _parse_class_ids(meta)
    try:
        input_size = int(meta.get("hive.input_size", "0"))
    except ValueError:
        input_size = 0
    if not class_ids or input_size <= 0:
        log.warning("color model %s has no usable classes/input_size", row.filename)
        return None
    try:
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        session = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
    except Exception as exc:
        log.warning("color model %s failed to load for inference: %s", row.filename, exc)
        return None
    loaded = _Loaded(
        session=session,
        input_name=meta.get("hive.input_name") or session.get_inputs()[0].name,
        output_name=meta.get("hive.output_name") or session.get_outputs()[0].name,
        input_size=input_size,
        class_ids=class_ids,
    )
    with _lock:
        _session_cache[key] = loaded
    return loaded


def _preprocess(data: bytes, size: int) -> np.ndarray | None:
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB").resize((size, size), Image.BILINEAR)
            arr = np.asarray(im, dtype=np.float32) / 255.0
    except Exception:
        return None
    return arr.transpose(2, 0, 1)


def _palette() -> dict[int, dict[str, Any]]:
    return {
        c["id"]: c
        for c in get_profile_catalog_service().list_bricklink_colors()
        if isinstance(c.get("id"), int)
    }


def predict(db: Session, images: list) -> dict[str, Any] | None:
    """Model color prediction for one piece's crops, or None when no model is
    active / the model can't be loaded / no crop is readable."""
    row = get_active(db)
    if row is None:
        return None
    loaded = _load(row)
    if loaded is None:
        return None

    with_key = [im for im in images if getattr(im, "image_key", None)]
    used = [im for im in with_key if getattr(im, "used", False)]
    chosen = (used or with_key)[:MAX_SAMPLES]

    batch: list[np.ndarray] = []
    for im in chosen:
        try:
            data = get_backend().read_bytes(im.image_key)
        except Exception:
            continue
        arr = _preprocess(data, loaded.input_size)
        if arr is not None:
            batch.append(arr)
    if not batch:
        return None

    x = np.stack(batch, axis=0)
    logits = loaded.session.run([loaded.output_name], {loaded.input_name: x})[0]
    logits = logits - logits.max(axis=1, keepdims=True)
    probs = np.exp(logits)
    probs /= probs.sum(axis=1, keepdims=True)
    mean_probs = probs.mean(axis=0)
    idx = int(np.argmax(mean_probs))
    if idx >= len(loaded.class_ids):
        return None
    color_id = loaded.class_ids[idx]
    confidence = float(mean_probs[idx])

    color = _palette().get(color_id)
    return {
        "method": "color_model",
        "model_name": row.name,
        "color_id": color_id,
        "color_name": color["name"] if color else None,
        "rgb": (color.get("rgb") or "").replace("#", "") if color else None,
        "confidence": confidence,
        "sample_count": len(batch),
    }


def clear_cache() -> None:
    with _lock:
        _session_cache.clear()
