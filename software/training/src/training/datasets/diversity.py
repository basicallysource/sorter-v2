"""Visual-diversity sampling for training datasets.

Picks a subset of images that are as visually dissimilar as possible using
farthest-point sampling (FPS) on YOLO-backbone embeddings. Analogous to
Levenshtein-style spread for text — broad coverage instead of many near-copies.

Workflow:
    1. ``embed_images(paths)`` runs a pretrained YOLO (default ``yolo11n.pt``)
       as a feature extractor and returns L2-normalized embeddings ``[N, D]``.
    2. ``farthest_point_sample(embeddings, k)`` returns indices of ``k`` samples
       picked greedily to maximize minimum pairwise distance to the selection.

Skipped for tiny datasets (``N < MIN_FOR_FPS``) — overhead without benefit.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np


log = logging.getLogger(__name__)

MIN_FOR_FPS = 200
DEFAULT_EMBED_MODEL = "yolo11n.pt"


def embed_images(
    image_paths: list[Path],
    *,
    model_weights: str = DEFAULT_EMBED_MODEL,
    imgsz: int = 320,
    batch: int = 16,
) -> np.ndarray:
    """Return ``[N, D]`` L2-normalized embeddings for the given images.

    Uses Ultralytics YOLO's built-in ``.embed()`` which runs the backbone and
    returns a pooled feature vector per image. Falls back to per-image calls if
    batched embedding is not supported by the installed ultralytics version.
    """
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "ultralytics is required for diversity sampling. Install with "
            "`pip install ultralytics` or skip the --target-size flag."
        ) from exc

    model = YOLO(model_weights)
    paths = [str(p) for p in image_paths]
    embeddings: list[np.ndarray] = []
    total = len(paths)
    print(f"  embedding {total} images with {model_weights} (imgsz={imgsz})…", file=sys.stderr)
    for start in range(0, total, batch):
        chunk = paths[start : start + batch]
        results = model.embed(chunk, imgsz=imgsz, verbose=False)
        for tensor in results:
            array = np.asarray(tensor, dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(array))
            if norm > 0:
                array = array / norm
            embeddings.append(array)
        done = min(total, start + batch)
        if done == total or start == 0 or done % (batch * 8) == 0:
            print(f"    embedded {done}/{total}", file=sys.stderr)
    if not embeddings:
        return np.zeros((0, 0), dtype=np.float32)
    max_dim = max(e.shape[0] for e in embeddings)
    # Some ultralytics versions pool differently for different sizes; pad / trim.
    stacked = np.zeros((len(embeddings), max_dim), dtype=np.float32)
    for i, emb in enumerate(embeddings):
        stacked[i, : emb.shape[0]] = emb
    return stacked


def farthest_point_sample(
    embeddings: np.ndarray,
    k: int,
    *,
    seed_index: int | None = None,
) -> list[int]:
    """Greedy farthest-point sampling.

    Returns ``k`` indices into ``embeddings`` maximizing the minimum L2 distance
    to the already-selected set. First index is either ``seed_index`` or the
    sample furthest from the mean embedding.
    """
    n = embeddings.shape[0]
    if n == 0 or k <= 0:
        return []
    if k >= n:
        return list(range(n))

    if seed_index is None:
        centroid = embeddings.mean(axis=0, keepdims=True)
        dists_from_centroid = np.linalg.norm(embeddings - centroid, axis=1)
        seed_index = int(np.argmax(dists_from_centroid))

    selected = [seed_index]
    min_dist = np.linalg.norm(embeddings - embeddings[seed_index], axis=1)
    for _ in range(1, k):
        next_index = int(np.argmax(min_dist))
        selected.append(next_index)
        new_dist = np.linalg.norm(embeddings - embeddings[next_index], axis=1)
        min_dist = np.minimum(min_dist, new_dist)
    return selected


def summarize_selection(
    embeddings: np.ndarray,
    selected: list[int],
) -> dict[str, Any]:
    """Return spread stats for a chosen subset (min/mean pairwise distances)."""
    if len(selected) < 2:
        return {"count": len(selected), "min_pairwise": None, "mean_pairwise": None}
    subset = embeddings[selected]
    diffs = subset[:, None, :] - subset[None, :, :]
    distances = np.linalg.norm(diffs, axis=-1)
    iu = np.triu_indices(len(selected), k=1)
    pair_dists = distances[iu]
    return {
        "count": len(selected),
        "min_pairwise": float(pair_dists.min()),
        "mean_pairwise": float(pair_dists.mean()),
        "max_pairwise": float(pair_dists.max()),
    }
