"""Score which upstream C2/C3 crops are the same piece, with a learned model.

The heuristic in channel_crop_lookup is the recall net: it picks every crop in a
time window around the piece's arrival at C4 and ranks by time/angle. This
module re-ranks that same candidate set with the piece_link matcher downloaded
from Hive — a siamese pair (a shared CropEncoder producing a 64-d embedding, and
a LinkHead scoring [emb_anchor, emb_candidate, |diff|, product, meta] -> P(same))
— which combines appearance with those same time/position features.

Model-first, heuristic-as-fallback: the model can only re-rank what
findPossibleCrops already returned, never recover a crop it dropped.

The 11-d meta vector must be built EXACTLY as it was during training or the
model scores nonsense rather than failing. The publisher bakes the ordered
feature list into the model's training_metadata as ``meta_features``; we
fingerprint our builder against it at load and refuse to run on a mismatch, so
a training-side change surfaces as a loud error instead of silent
mispredictions. See META_FEATURES below.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# Ordered meta features, copied from the training repo
# (color-model/piece_link/dataset.py :: candidateMeta). Kept as the literal
# string the exporter bakes into the ONNX so the two can be compared directly.
META_FEATURES = (
    "dt/30, log1p(max(dt,0))/4, ch==2, ch==3, zone==0, zone==1, zone==2, "
    "zone==3, deg/180, abs(deg)/180, at_exit; dt=arrival_ts-crop_ts, "
    "at_exit = zone in (2,3) or abs(deg)<20"
)
META_DIM = 11
ENCODER_MEMBER = "encoder.onnx"
HEAD_MEMBER = "head.onnx"
DEFAULT_PREDICT_THRESHOLD = 0.5
# Scoring every candidate costs one encoder pass each; the heuristic already
# caps its own list, this is a second belt so a pathological window can't stall
# the classify thread.
MAX_CANDIDATES = 64


@dataclass
class LoadedLinkModel:
    local_id: str
    name: str
    encoder: Any
    head: Any
    encoder_input: str
    head_inputs: tuple[str, str, str]
    input_size: int
    predict_threshold: float


_lock = threading.Lock()
_cache: dict[str, LoadedLinkModel] = {}
# A model that failed to load stays failed — retrying per piece would spam the
# classify thread with the same import error.
_failed: set[str] = set()


def _normalizeFeatures(text: str) -> str:
    return "".join(text.split()).lower()


def _readRunJson(model_dir: Path) -> dict[str, Any]:
    try:
        raw = json.loads((model_dir / "run.json").read_text())
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def loadModel(gc: Any, local_id: str, model_dir: Path) -> Optional[LoadedLinkModel]:
    with _lock:
        cached = _cache.get(local_id)
        if cached is not None:
            return cached
        if local_id in _failed:
            return None

    try:
        import onnxruntime as ort
    except Exception as exc:
        gc.logger.warning(f"[link] onnxruntime unavailable, matcher disabled: {exc}")
        with _lock:
            _failed.add(local_id)
        return None

    meta = _readRunJson(model_dir)
    exports = model_dir / "exports"
    encoder_path = exports / str(meta.get("encoder_member") or ENCODER_MEMBER)
    head_path = exports / str(meta.get("head_member") or HEAD_MEMBER)
    if not encoder_path.is_file() or not head_path.is_file():
        gc.logger.warning(
            f"[link] {local_id}: missing {ENCODER_MEMBER}/{HEAD_MEMBER} under exports/"
        )
        with _lock:
            _failed.add(local_id)
        return None

    # The meta contract check. A mismatch means our builder and the model's
    # training disagree, which scores garbage silently — refuse instead.
    baked = meta.get("meta_features")
    if isinstance(baked, str) and baked:
        if _normalizeFeatures(baked) != _normalizeFeatures(META_FEATURES):
            gc.logger.error(
                f"[link] {local_id}: meta_features mismatch — refusing to run.\n"
                f"  model expects: {baked}\n"
                f"  we build:      {META_FEATURES}"
            )
            with _lock:
                _failed.add(local_id)
            return None
    else:
        gc.logger.warning(
            f"[link] {local_id}: no meta_features in run.json; cannot verify the "
            f"feature contract, assuming it matches this build"
        )

    declared_dim = meta.get("meta_dim")
    if isinstance(declared_dim, int) and declared_dim != META_DIM:
        gc.logger.error(
            f"[link] {local_id}: meta_dim {declared_dim} != {META_DIM} — refusing to run"
        )
        with _lock:
            _failed.add(local_id)
        return None

    try:
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        encoder = ort.InferenceSession(
            str(encoder_path), sess_options=so, providers=["CPUExecutionProvider"]
        )
        head = ort.InferenceSession(
            str(head_path), sess_options=so, providers=["CPUExecutionProvider"]
        )
    except Exception as exc:
        gc.logger.warning(f"[link] {local_id}: failed to open onnx sessions: {exc}")
        with _lock:
            _failed.add(local_id)
        return None

    # Bind head inputs BY NAME — the exporter names them emb_anchor /
    # emb_candidate / meta. Feeding the anchor where the candidate belongs
    # produces plausible-looking probabilities rather than an error, so don't
    # trust positional order unless the model declines to name them.
    head_names = [i.name for i in head.get_inputs()]
    if len(head_names) != 3:
        gc.logger.error(f"[link] {local_id}: head expects {head_names}, want 3 inputs")
        with _lock:
            _failed.add(local_id)
        return None
    wanted = ("emb_anchor", "emb_candidate", "meta")
    if all(name in head_names for name in wanted):
        head_inputs = wanted
    else:
        gc.logger.warning(
            f"[link] {local_id}: head inputs {head_names} are not the expected "
            f"{list(wanted)}; falling back to declared order"
        )
        head_inputs = (head_names[0], head_names[1], head_names[2])

    input_size = int(meta.get("input_size") or 96)
    threshold = meta.get("predict_threshold")
    loaded = LoadedLinkModel(
        local_id=local_id,
        name=str(meta.get("name") or local_id),
        encoder=encoder,
        head=head,
        encoder_input=encoder.get_inputs()[0].name,
        head_inputs=head_inputs,
        input_size=input_size,
        predict_threshold=(
            float(threshold) if isinstance(threshold, (int, float)) else DEFAULT_PREDICT_THRESHOLD
        ),
    )
    with _lock:
        _cache[local_id] = loaded
    gc.logger.info(
        f"[link] loaded {loaded.name} ({local_id}) input={input_size}px "
        f"threshold={loaded.predict_threshold}"
    )
    return loaded


def invalidateCache() -> None:
    with _lock:
        _cache.clear()
        _failed.clear()


def resolveActiveModel(gc: Any) -> Optional[LoadedLinkModel]:
    """The configured piece_link model, or None when disabled/absent.

    Cheap enough to call per piece: the config read is a small TOML parse and
    the sessions are cached by local_id.
    """
    from toml_config import getLinkMatchingConfig

    cfg = getLinkMatchingConfig()
    if not cfg.get("enabled"):
        return None

    import server.hive_models as hive_models

    wanted = cfg.get("algorithm") or ""
    installed = [
        e
        for e in hive_models.list_installed_models()
        if e.get("purpose") == hive_models.PURPOSE_PIECE_LINK
    ]
    if not installed:
        return None
    entry = None
    if wanted:
        entry = next((e for e in installed if e.get("local_id") == wanted), None)
        if entry is None:
            gc.logger.warning(
                f"[link] configured model {wanted!r} is not installed; "
                f"falling back to {installed[0].get('local_id')!r}"
            )
    if entry is None:
        entry = installed[0]

    path = entry.get("path")
    if not path:
        return None
    return loadModel(gc, str(entry["local_id"]), Path(path))


def matchForPiece(
    gc: Any, piece_uuid: str, limit: int = 40
) -> Optional[dict[str, Any]]:
    """Full path: heuristic candidate set -> model re-rank. None when the
    matcher is off or unusable, so callers keep the heuristic ranking."""
    model = resolveActiveModel(gc)
    if model is None:
        return None

    import channel_crop_lookup

    found = channel_crop_lookup.findPossibleCrops(gc, piece_uuid, limit=limit)
    candidates = found.get("candidates") or []
    scored = scoreCandidates(gc, model, piece_uuid, candidates)
    if scored is None:
        return None
    return {
        "arrival_ts": found.get("arrival_ts"),
        "candidates": scored,
        "link_model": model.name,
        "link_model_local_id": model.local_id,
        "prediction_source": "model",
    }


def _preprocess(path: Path, size: int):
    import numpy as np
    from PIL import Image

    with Image.open(path) as img:
        rgb = img.convert("RGB").resize((size, size), Image.BILINEAR)
        arr = np.asarray(rgb, dtype="float32") / 255.0
    return arr.transpose(2, 0, 1)


def candidateMeta(candidate: dict[str, Any]):
    """The 11-d meta vector. Byte-for-byte port of the training repo's
    candidateMeta — see META_FEATURES. Do not reorder."""
    import numpy as np

    dt = float(candidate.get("dt") or 0.0)
    deg_raw = candidate.get("com_forward_to_exit_deg")
    deg = float(deg_raw) if isinstance(deg_raw, (int, float)) else 0.0
    zone_raw = candidate.get("zone_code")
    zone = int(zone_raw) if isinstance(zone_raw, int) else -1
    ch = int(candidate.get("channel") or 0)
    at_exit = 1.0 if (zone in (2, 3) or abs(deg) < 20) else 0.0
    return np.asarray(
        [
            dt / 30.0,
            math.log1p(max(dt, 0.0)) / 4.0,
            1.0 if ch == 2 else 0.0,
            1.0 if ch == 3 else 0.0,
            1.0 if zone == 0 else 0.0,
            1.0 if zone == 1 else 0.0,
            1.0 if zone == 2 else 0.0,
            1.0 if zone == 3 else 0.0,
            deg / 180.0,
            abs(deg) / 180.0,
            at_exit,
        ],
        dtype="float32",
    )


def _anchorPath(piece_uuid: str, classification_channel_id: int) -> Optional[Path]:
    import piece_image_store

    try:
        images = piece_image_store.listPieceImages(piece_uuid)
    except Exception:
        return None
    # Prefer a C4 burst frame that actually drove the classification, then any
    # C4 frame, then anything at all.
    ordered = sorted(
        images,
        key=lambda im: (
            0 if (im.get("channel") == classification_channel_id and im.get("used")) else
            1 if im.get("channel") == classification_channel_id else 2,
            im.get("ts") or 0.0,
        ),
    )
    for im in ordered:
        path = piece_image_store.getImageFileById(im["id"])
        if path is not None and path.is_file():
            return path
    return None


def scoreCandidates(
    gc: Any,
    model: LoadedLinkModel,
    piece_uuid: str,
    candidates: list[dict[str, Any]],
    classification_channel_id: int = 4,
) -> Optional[list[dict[str, Any]]]:
    """Attach ``model_score`` / ``model_same`` to each candidate, best-effort.

    Returns None when the model could not be run at all (no anchor pixels, no
    readable candidate crops) so the caller can fall back to the heuristic
    ranking rather than presenting an empty result as a confident 'no match'.
    """
    import numpy as np

    import channel_crop_store

    if not candidates:
        return []

    anchor_path = _anchorPath(piece_uuid, classification_channel_id)
    if anchor_path is None:
        gc.logger.debug(f"[link] {piece_uuid}: no anchor image available")
        return None

    usable: list[dict[str, Any]] = []
    crops = []
    for cand in candidates[:MAX_CANDIDATES]:
        path = channel_crop_store.getCropFileById(int(cand["id"]))
        # Retention evicts the JPEG but keeps the row, so an older candidate can
        # be metadata-only. Skip it rather than scoring a blank.
        if path is None or not path.is_file():
            continue
        try:
            crops.append(_preprocess(path, model.input_size))
        except Exception:
            continue
        usable.append(cand)

    if not usable:
        gc.logger.debug(f"[link] {piece_uuid}: no candidate crops with pixels on disk")
        return None

    try:
        anchor = _preprocess(anchor_path, model.input_size)
        emb_anchor = model.encoder.run(
            None, {model.encoder_input: anchor[None, ...]}
        )[0]
        emb_cand = model.encoder.run(
            None, {model.encoder_input: np.stack(crops).astype("float32")}
        )[0]
        meta = np.stack([candidateMeta(c) for c in usable]).astype("float32")
        a_name, c_name, m_name = model.head_inputs
        probs = model.head.run(
            None,
            {
                a_name: np.repeat(emb_anchor[:1], len(usable), axis=0),
                c_name: emb_cand,
                m_name: meta,
            },
        )[0]
    except Exception as exc:
        gc.logger.warning(f"[link] {piece_uuid}: inference failed: {exc}")
        return None

    flat = np.asarray(probs).reshape(-1)
    scored: list[dict[str, Any]] = []
    for cand, p in zip(usable, flat):
        entry = dict(cand)
        entry["model_score"] = round(float(p), 4)
        entry["model_same"] = bool(float(p) >= model.predict_threshold)
        scored.append(entry)
    scored.sort(key=lambda c: c["model_score"], reverse=True)
    return scored
