"""The registry of colour-reference palette finders (``swatch_models``).

Like the colour and link models: ONNX files are uploaded to ``SWATCH_MODEL_DIR``
out of band, each self-describing through its ``hive.*`` metadata
(``hive.kind`` = "swatch_finder", ``hive.name``, ``hive.colour_names``,
``hive.classes``, ``hive.net_long_side``, ...). A scan reconciles the table to
the files; an admin activates one. Only the active model's finder is ever
loaded, in one cached slot.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

import onnxruntime as ort
from sqlalchemy.orm import Session

from app.config import settings
from app.models.swatch_model import SwatchModel
from app.services.swatch_finder import SwatchFinder

log = logging.getLogger(__name__)

HIVE_KIND = "swatch_finder"


def model_dir() -> Path:
    return Path(settings.SWATCH_MODEL_DIR)


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_metadata(path: Path) -> dict[str, str] | None:
    """The model's ``hive.*`` metadata, read through a throwaway session. None
    when the file is not a readable swatch finder."""
    try:
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        sess = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
    except Exception as exc:
        log.warning("swatch model %s failed to load: %s", path.name, exc)
        return None
    meta = sess.get_modelmeta().custom_metadata_map or {}
    if meta.get("hive.kind") != HIVE_KIND:
        log.info("%s in the swatch model folder is not a %s (kind=%r)", path.name, HIVE_KIND, meta.get("hive.kind"))
        return None
    return dict(meta)


def _int(meta: dict[str, str], key: str) -> int:
    try:
        return int(meta.get(key, "0"))
    except ValueError:
        return 0


def _colour_count(meta: dict[str, str]) -> int:
    try:
        names = json.loads(meta.get("hive.colour_names", "[]"))
    except ValueError:
        return 0
    return max(0, len(names) - 1) if isinstance(names, list) else 0


def scan_models() -> list[dict[str, Any]]:
    """Every readable swatch finder in SWATCH_MODEL_DIR, with its metadata."""
    directory = model_dir()
    if not directory.exists():
        return []
    found: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.onnx")):
        meta = _read_metadata(path)
        if meta is None:
            continue
        found.append(
            {
                "filename": path.name,
                "name": meta.get("hive.name") or path.stem,
                "description": meta.get("hive.description"),
                "kind": HIVE_KIND,
                "sha256": _sha256_of(path),
                "colour_count": _colour_count(meta),
                "net_long_side": _int(meta, "hive.net_long_side"),
                "file_size": path.stat().st_size,
                "meta": meta,
            }
        )
    return found


def reconcile(db: Session) -> list[SwatchModel]:
    """Sync swatch_models rows to the files on disk: insert new, refresh
    changed (sha differs), drop vanished. Returns all rows after."""
    scanned = {m["filename"]: m for m in scan_models()}
    existing = {row.filename: row for row in db.query(SwatchModel).all()}
    fields = ("name", "description", "kind", "sha256", "colour_count", "net_long_side", "file_size", "meta")

    for filename, m in scanned.items():
        row = existing.get(filename)
        if row is None:
            db.add(SwatchModel(filename=filename, **{k: m[k] for k in fields}))
        elif row.sha256 != m["sha256"]:
            for k in fields:
                setattr(row, k, m[k])

    for filename, row in existing.items():
        if filename not in scanned:
            db.delete(row)

    db.commit()
    return db.query(SwatchModel).order_by(SwatchModel.name.asc()).all()


def get_active(db: Session) -> SwatchModel | None:
    return db.query(SwatchModel).filter(SwatchModel.is_active.is_(True)).first()


def has_active(db: Session) -> bool:
    return db.query(SwatchModel.id).filter(SwatchModel.is_active.is_(True)).first() is not None


def set_active(db: Session, model_id, active: bool) -> SwatchModel | None:
    row = db.query(SwatchModel).filter(SwatchModel.id == model_id).first()
    if row is None:
        return None
    if active:
        # One active model at a time: clear the others first.
        db.query(SwatchModel).filter(SwatchModel.id != model_id, SwatchModel.is_active.is_(True)).update(
            {SwatchModel.is_active: False}
        )
        row.is_active = True
    else:
        row.is_active = False
    db.commit()
    db.refresh(row)
    return row


_lock = threading.Lock()
# One slot: only the active model is ever run, so a newly activated one
# replaces the old session instead of keeping every version resident.
_loaded_key: tuple[str, str] | None = None
_loaded: SwatchFinder | None = None


def get_finder(filename: str, sha256: str) -> SwatchFinder | None:
    """The finder for a registry row's file, loaded once and cached. None when
    the file is gone or will not load."""
    global _loaded_key, _loaded
    key = (filename, sha256)
    with _lock:
        if key == _loaded_key and _loaded is not None:
            return _loaded
        path = model_dir() / filename
        if not path.exists():
            return None
        try:
            finder = SwatchFinder(path, threads=max(1, int(settings.SWATCH_FINDER_THREADS)))
        except Exception as exc:
            log.warning("swatch model %s failed to load for inference: %s", filename, exc)
            return None
        _loaded_key, _loaded = key, finder
        return finder
