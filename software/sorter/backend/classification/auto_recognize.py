"""Fire-and-forget auto-recognition for finalized feeder tracks.

When a c_channel_3 track dies with enough crops, this module runs a quick
OSNet-based consistency check — we've occasionally seen the polar tracker
hijack a global_id across two visually-distinct pieces, and Brickognize
fuses the resulting crops into a single nonsense prediction. The check:

1. Embed each ``piece_jpeg_b64`` crop with OSNet.
2. Pick the single crop whose embedding has the most near-neighbours
   above ``similarity_threshold`` — the "dominant" piece.
3. Keep only crops within that similarity threshold of the anchor.
4. If ``>= min_crops`` crops survive, send them to Brickognize as one
   multi-image query and stash the result on the ``TrackSegment``.

Runs in a background thread so the tracker's update loop never waits on
the network round-trip.
"""

from __future__ import annotations

import base64
import threading
from typing import Any

import cv2
import numpy as np


def _decode(b64: str) -> "np.ndarray | None":
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _dominant_cluster(
    embeddings: list[np.ndarray | None],
    similarity_threshold: float = 0.6,
) -> list[int]:
    """Return indices of the largest consistent cluster.

    Each embedding is scored by how many OTHER embeddings fall within
    ``similarity_threshold`` (cosine). The highest-scoring embedding
    becomes the anchor; everything within threshold of the anchor is
    kept.
    """
    valid: list[tuple[int, np.ndarray]] = [
        (i, e) for i, e in enumerate(embeddings) if e is not None
    ]
    if not valid:
        return []
    best_anchor_idx = -1
    best_count = -1
    for i, (_orig_i, emb_i) in enumerate(valid):
        count = 0
        for j, (_orig_j, emb_j) in enumerate(valid):
            if i == j:
                continue
            if _cosine(emb_i, emb_j) >= similarity_threshold:
                count += 1
        if count > best_count:
            best_count = count
            best_anchor_idx = i
    if best_anchor_idx < 0:
        return []
    anchor = valid[best_anchor_idx][1]
    inliers: list[int] = []
    for orig_i, emb in valid:
        if orig_i == valid[best_anchor_idx][0] or _cosine(emb, anchor) >= similarity_threshold:
            inliers.append(orig_i)
    return inliers


def _quality_score(img: np.ndarray) -> dict:
    """Sharpness + exposure stats used to gate low-quality crops.

    Sharpness = variance of a Laplacian response (standard OpenCV blur
    detector). Over/under = fraction of pixels near saturation or pure
    black, catches blown-out highlights from the ring light and dead
    shadow regions outside the lit area.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return {
        "sharpness": float(lap.var()),
        "mean": float(gray.mean()),
        "over": float((gray >= 245).mean()),
        "under": float((gray <= 10).mean()),
    }


def _passes_quality(
    q: dict,
    *,
    min_sharpness: float = 30.0,
    max_overexposed: float = 0.5,
    max_underexposed: float = 0.5,
) -> bool:
    if q["sharpness"] < min_sharpness:
        return False
    if q["over"] > max_overexposed:
        return False
    if q["under"] > max_underexposed:
        return False
    return True


def _store_result(target: Any, result: dict) -> None:
    """Write ``result`` onto ``target.auto_recognition`` via mutation when
    possible so any shared references (e.g. a TrackSegment that copied
    the live track's dict) stay in sync with the final state.
    """
    existing = getattr(target, "auto_recognition", None)
    if isinstance(existing, dict):
        existing.clear()
        existing.update(result)
    else:
        target.auto_recognition = dict(result)


def run_async(
    target: Any,
    crops_b64: list[str],
    *,
    min_crops: int = 5,
    similarity_threshold: float = 0.6,
    on_complete: "Any | None" = None,
) -> None:
    """Spawn a background thread that runs quality gate + consistency
    check + Brickognize.

    Writes the result onto ``target.auto_recognition`` — works for both
    a live ``_LiveTrack`` and an archived ``TrackSegment``. Updates in
    place so callers that copy the dict ref stay in sync once the
    thread finishes.

    Idempotent: if the target already has a non-``None``
    ``auto_recognition``, this is a no-op. Prevents double-fire on the
    same global_id when the exit-trigger races with track-death.
    """
    if getattr(target, "auto_recognition", None) is not None:
        return
    if not crops_b64 or len(crops_b64) < min_crops:
        return
    target.auto_recognition = {"status": "pending", "queued_count": len(crops_b64)}
    thread = threading.Thread(
        target=_run,
        args=(target, list(crops_b64), min_crops, similarity_threshold, on_complete),
        daemon=True,
    )
    thread.start()


def _run(
    segment: Any,
    crops_b64: list[str],
    min_crops: int,
    similarity_threshold: float,
    on_complete: "Any | None" = None,
) -> None:
    try:
        imgs: list[np.ndarray | None] = [_decode(b) for b in crops_b64]
        valid_idx = [i for i, im in enumerate(imgs) if im is not None]
        if len(valid_idx) < min_crops:
            _store_result(segment, {
                "status": "error",
                "error": f"only {len(valid_idx)} crops decoded, need {min_crops}",
            })
            return

        # Quality gate — drop motion-blurred / blown-out / near-black crops
        # before we bother with embeddings and network.
        quality_idx: list[int] = []
        rejected_for_quality = 0
        for i in valid_idx:
            img = imgs[i]
            if img is None:
                continue
            q = _quality_score(img)
            if _passes_quality(q):
                quality_idx.append(i)
            else:
                rejected_for_quality += 1
        if len(quality_idx) < min_crops:
            _store_result(segment, {
                "status": "insufficient_quality",
                "kept_count": len(quality_idx),
                "rejected_for_quality": rejected_for_quality,
                "total_crops": len(crops_b64),
            })
            return
        valid_idx = quality_idx

        # OSNet embedding per crop — the consistency gate. Gracefully skip
        # filtering when the embedder isn't available (e.g. weights missing).
        try:
            from vision.tracking.appearance import get_embedder

            embedder = get_embedder()
        except Exception:
            embedder = None

        inlier_indices: list[int]
        if embedder is not None:
            embeddings: list[np.ndarray | None] = [None] * len(imgs)
            for i in valid_idx:
                img = imgs[i]
                if img is None:
                    continue
                h, w = img.shape[:2]
                # Feed the crop as its own frame with a full-image bbox so
                # the embedder treats the whole piece crop as the subject.
                mat = embedder.extract(img, [(0, 0, w, h)])
                if mat is None or mat.size == 0:
                    continue
                vec = mat[0]
                if float(np.linalg.norm(vec)) > 0.0:
                    embeddings[i] = vec
            inlier_indices = _dominant_cluster(
                embeddings,
                similarity_threshold=similarity_threshold,
            )
        else:
            inlier_indices = valid_idx

        if len(inlier_indices) < min_crops:
            _store_result(segment, {
                "status": "insufficient_consistency",
                "inlier_count": len(inlier_indices),
                "total_crops": len(crops_b64),
            })
            return

        # Rank inliers by sharpness and take the top ``min_crops`` — there's
        # no point sending 15 crops to Brickognize when 8 sharp ones give
        # the same (or a better) prediction and cost less time.
        scored_inliers = []
        for i in inlier_indices:
            img = imgs[i]
            if img is None:
                continue
            q = _quality_score(img)
            scored_inliers.append((q["sharpness"], i, img))
        scored_inliers.sort(key=lambda t: t[0], reverse=True)
        # Cap at 8 top-sharpness images — Brickognize gets diminishing
        # returns past that and the multipart request stays snappy.
        inlier_imgs = [im for _s, _i, im in scored_inliers[:max(min_crops, 5)]]
        # But always allow up to 8 if we have more sharp ones.
        inlier_imgs = inlier_imgs[:8]

        from classification.brickognize import (
            _classifyImages,
            _pickBestColor,
            _pickBestItem,
        )

        result = _classifyImages(inlier_imgs)
        best_item, best_view = _pickBestItem(result, None)
        best_color = _pickBestColor(result, None)
        _store_result(segment, {
            "status": "ok",
            "image_count": len(inlier_imgs),
            "total_crops": len(crops_b64),
            "best_item": best_item,
            "best_view": best_view,
            "best_color": best_color,
        })
    except Exception as exc:
        _store_result(segment, {"status": "error", "error": str(exc)})
    finally:
        if on_complete is not None:
            try:
                on_complete()
            except Exception:
                pass
