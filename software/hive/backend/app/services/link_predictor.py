"""Serve piece_link "same physical piece" scores from an uploaded ONNX pair.

The active model (one global row in ``link_models``) replaces the time/angle
heuristic's pre-selection in the labeling view. Each model is TWO ``.onnx``
graphs living in ``LINK_MODEL_DIR`` and uploaded out of band: a shared
``CropEncoder`` (64×64 RGB crop → 64-d L2-normalized embedding, mean/std baked
in) and a ``LinkHead`` (emb_anchor, emb_candidate, 11-d meta → P(same),
sigmoid baked in). Both files carry a ``hive.*`` metadata block and are grouped
by their ``hive.name``; a dir scan needs no sidecar files.

Scoring path (per piece): take the heuristic's time-window candidate set (the
recall net, from ``find_possible_crops``), embed the piece's C4 anchor once and
every candidate crop, build each candidate's meta feature vector, and run the
head to get a same-piece probability per candidate. ``candidateMeta`` is copied
byte-for-byte from the training repo (color-model/piece_link/dataset.py) — the
model's meta inputs must match training exactly, so keep the two in sync.
"""

from __future__ import annotations

import hashlib
import io
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import numpy as np
import onnxruntime as ort
from PIL import Image
from sqlalchemy.orm import Session

from app.config import settings
from app.models.link_model import LinkModel
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_piece_image import MachinePieceImage
from app.services.channel_crop_lookup_params import DEFAULT_PARAMS
from app.services.storage_backend import get_backend

log = logging.getLogger(__name__)

_HIVE_KIND = "piece_link_matcher"
# sigmoid prob at/above which a candidate is the model's "same piece" pick.
PREDICT_THRESHOLD = 0.5
MAX_ANCHOR_VIEWS = 3


def model_dir() -> Path:
    return Path(settings.LINK_MODEL_DIR)


@dataclass
class _Loaded:
    encoder: ort.InferenceSession
    head: ort.InferenceSession
    enc_input: str
    input_size: int


_lock = threading.Lock()
_session_cache: dict[tuple[str, str], _Loaded] = {}


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_metadata(path: Path) -> dict[str, str] | None:
    """Read a file's ``hive.*`` metadata via a throwaway ort session. Returns
    None when the file isn't a readable piece_link_matcher graph."""
    try:
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        sess = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
    except Exception as exc:
        log.warning("link model %s failed to load: %s", path.name, exc)
        return None
    meta = sess.get_modelmeta().custom_metadata_map or {}
    if meta.get("hive.kind") != _HIVE_KIND:
        return None
    return dict(meta)


def _int(meta: dict[str, str], key: str) -> int:
    try:
        return int(meta.get(key, "0"))
    except ValueError:
        return 0


def scan_models() -> list[dict[str, Any]]:
    """Every piece_link matcher in LINK_MODEL_DIR, grouped by ``hive.name`` into
    encoder+head pairs. A name is only surfaced when both roles are present."""
    directory = model_dir()
    if not directory.exists():
        return []
    by_name: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.onnx")):
        meta = _read_metadata(path)
        if meta is None:
            continue
        name = meta.get("hive.name") or path.stem
        role = meta.get("hive.role")
        entry = by_name.setdefault(name, {"name": name, "meta": meta, "roles": {}})
        entry["roles"][role] = path
        # prefer head metadata for display fields (identical across the pair)
        if role == "head":
            entry["meta"] = meta

    found: list[dict[str, Any]] = []
    for name, entry in by_name.items():
        roles = entry["roles"]
        encoder = roles.get("encoder")
        head = roles.get("head")
        if encoder is None or head is None:
            log.warning("link model %s is missing its %s graph — skipping", name,
                        "head" if head is None else "encoder")
            continue
        meta = entry["meta"]
        combined = hashlib.sha256()
        for p in sorted([encoder, head], key=lambda p: p.name):
            combined.update(_sha256_of(p).encode())
        found.append(
            {
                "name": name,
                "description": meta.get("hive.description"),
                "kind": meta.get("hive.kind", _HIVE_KIND),
                "encoder_filename": encoder.name,
                "head_filename": head.name,
                "sha256": combined.hexdigest(),
                "input_size": _int(meta, "hive.input_size"),
                "embed_dim": _int(meta, "hive.embed_dim"),
                "meta_dim": _int(meta, "hive.meta_dim"),
                "file_size": encoder.stat().st_size + head.stat().st_size,
                "meta": meta,
            }
        )
    return sorted(found, key=lambda m: m["name"])


def reconcile(db: Session) -> list[LinkModel]:
    """Sync link_models rows to the pairs on disk: insert new, refresh changed
    (sha differs), drop vanished. Returns all rows after reconciliation."""
    scanned = {m["name"]: m for m in scan_models()}
    existing = {row.name: row for row in db.query(LinkModel).all()}

    for name, m in scanned.items():
        row = existing.get(name)
        if row is None:
            db.add(
                LinkModel(
                    name=name,
                    description=m["description"],
                    kind=m["kind"],
                    encoder_filename=m["encoder_filename"],
                    head_filename=m["head_filename"],
                    sha256=m["sha256"],
                    input_size=m["input_size"],
                    embed_dim=m["embed_dim"],
                    meta_dim=m["meta_dim"],
                    file_size=m["file_size"],
                    meta=m["meta"],
                )
            )
        elif row.sha256 != m["sha256"] or row.encoder_filename != m["encoder_filename"] or row.head_filename != m["head_filename"]:
            row.description = m["description"]
            row.kind = m["kind"]
            row.encoder_filename = m["encoder_filename"]
            row.head_filename = m["head_filename"]
            row.sha256 = m["sha256"]
            row.input_size = m["input_size"]
            row.embed_dim = m["embed_dim"]
            row.meta_dim = m["meta_dim"]
            row.file_size = m["file_size"]
            row.meta = m["meta"]

    for name, row in existing.items():
        if name not in scanned:
            db.delete(row)

    db.commit()
    return db.query(LinkModel).order_by(LinkModel.name.asc()).all()


def get_active(db: Session) -> LinkModel | None:
    return db.query(LinkModel).filter(LinkModel.is_active.is_(True)).first()


def set_active(db: Session, model_id, active: bool) -> LinkModel | None:
    row = db.query(LinkModel).filter(LinkModel.id == model_id).first()
    if row is None:
        return None
    if active:
        db.query(LinkModel).filter(LinkModel.id != model_id, LinkModel.is_active.is_(True)).update(
            {LinkModel.is_active: False}
        )
        row.is_active = True
    else:
        row.is_active = False
    db.commit()
    db.refresh(row)
    return row


def _load(row: LinkModel) -> _Loaded | None:
    directory = model_dir()
    enc_path = directory / row.encoder_filename
    head_path = directory / row.head_filename
    if not enc_path.exists() or not head_path.exists():
        return None
    key = (row.name, row.sha256)
    with _lock:
        cached = _session_cache.get(key)
        if cached is not None:
            return cached
    if row.input_size <= 0:
        log.warning("link model %s has no usable input_size", row.name)
        return None
    try:
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        encoder = ort.InferenceSession(str(enc_path), sess_options=so, providers=["CPUExecutionProvider"])
        head = ort.InferenceSession(str(head_path), sess_options=so, providers=["CPUExecutionProvider"])
    except Exception as exc:
        log.warning("link model %s failed to load for inference: %s", row.name, exc)
        return None
    loaded = _Loaded(
        encoder=encoder,
        head=head,
        enc_input=encoder.get_inputs()[0].name,
        input_size=row.input_size,
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


def _candidate_meta(dt: float, channel: Optional[int], zone_code: Optional[int], deg: Optional[float]) -> np.ndarray:
    """Port of color-model/piece_link/dataset.py::candidateMeta — keep in sync."""
    deg_v = deg if deg is not None else 0.0
    zone = zone_code if zone_code is not None else -1
    at_exit = zone in (2, 3) or (deg is not None and abs(deg) < 20.0)
    return np.array(
        [
            dt / 30.0,
            math.log1p(max(dt, 0.0)) / 4.0,
            1.0 if channel == 2 else 0.0,
            1.0 if channel == 3 else 0.0,
            1.0 if zone == 0 else 0.0,
            1.0 if zone == 1 else 0.0,
            1.0 if zone == 2 else 0.0,
            1.0 if zone == 3 else 0.0,
            deg_v / 180.0,
            abs(deg_v) / 180.0,
            1.0 if at_exit else 0.0,
        ],
        dtype=np.float32,
    )


def _anchor_keys(db: Session, machine_id: UUID, piece_uuid: str) -> list[str]:
    rows = (
        db.query(MachinePieceImage.channel, MachinePieceImage.seq, MachinePieceImage.image_key)
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid == piece_uuid,
            MachinePieceImage.image_key.isnot(None),
        )
        .order_by(MachinePieceImage.seq.asc())
        .all()
    )
    c4 = [r.image_key for r in rows if r.channel == DEFAULT_PARAMS.classification_channel_id]
    keys = c4 if c4 else [r.image_key for r in rows]
    return keys[:MAX_ANCHOR_VIEWS]


def _crop_keys(db: Session, machine_id: UUID, local_ids: list[int]) -> dict[int, str]:
    if not local_ids:
        return {}
    rows = (
        db.query(MachineChannelCrop.local_id, MachineChannelCrop.image_key)
        .filter(
            MachineChannelCrop.machine_id == machine_id,
            MachineChannelCrop.local_id.in_(local_ids),
            MachineChannelCrop.image_key.isnot(None),
        )
        .all()
    )
    return {r.local_id: r.image_key for r in rows}


def _embed(loaded: _Loaded, images: list[np.ndarray]) -> np.ndarray:
    x = np.stack(images, axis=0)
    return loaded.encoder.run(None, {loaded.enc_input: x})[0]


def predict(db: Session, machine_id: UUID, piece_uuid: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Score the heuristic's candidate set with the active link model.

    ``candidates`` are the dicts from ``find_possible_crops`` (need: local_id,
    channel, dt, zone_code, com_forward_to_exit_deg). Returns
    ``{model_name, threshold, scores: {local_id: prob}}`` or None when no model
    is active / the model can't be loaded / no anchor or crop is readable.
    """
    row = get_active(db)
    if row is None:
        return None
    loaded = _load(row)
    if loaded is None:
        return None

    anchor_imgs: list[np.ndarray] = []
    for key in _anchor_keys(db, machine_id, piece_uuid):
        try:
            arr = _preprocess(get_backend().read_bytes(key), loaded.input_size)
        except Exception:
            arr = None
        if arr is not None:
            anchor_imgs.append(arr)
            break  # training eval scores against a single anchor
    if not anchor_imgs:
        return None

    local_ids = [c["local_id"] for c in candidates]
    key_by_id = _crop_keys(db, machine_id, local_ids)

    crop_imgs: list[np.ndarray] = []
    metas: list[np.ndarray] = []
    scored_ids: list[int] = []
    for c in candidates:
        key = key_by_id.get(c["local_id"])
        if key is None:
            continue
        try:
            arr = _preprocess(get_backend().read_bytes(key), loaded.input_size)
        except Exception:
            arr = None
        if arr is None:
            continue
        crop_imgs.append(arr)
        metas.append(_candidate_meta(c.get("dt") or 0.0, c.get("channel"), c.get("zone_code"), c.get("com_forward_to_exit_deg")))
        scored_ids.append(c["local_id"])
    if not crop_imgs:
        return None

    emb_a = _embed(loaded, anchor_imgs)[:1]  # (1, embed_dim)
    emb_c = _embed(loaded, crop_imgs)  # (n, embed_dim)
    meta = np.stack(metas, axis=0)  # (n, meta_dim)
    emb_a_tiled = np.repeat(emb_a, len(crop_imgs), axis=0)
    probs = loaded.head.run(
        None,
        {"emb_anchor": emb_a_tiled.astype(np.float32), "emb_candidate": emb_c.astype(np.float32), "meta": meta},
    )[0]
    probs = np.asarray(probs).reshape(-1)

    return {
        "model_name": row.name,
        "threshold": PREDICT_THRESHOLD,
        "scores": {lid: float(p) for lid, p in zip(scored_ids, probs)},
    }


def clear_cache() -> None:
    with _lock:
        _session_cache.clear()
