"""Appearance embedding for track-identity preservation.

Wraps BoxMOT's OSNet_x0_25 ReID model so the polar tracker can distinguish
visually different pieces at the cost-matrix level. OSNet is a ~3 MB CNN
from the original ReID paper, pretrained on MSMT17 — works surprisingly
well on LEGO pieces despite being trained on pedestrians.

Cosine similarity on the 512-dim unit-normalized embedding replaces the
previous HSV-histogram check. Similarity 1.0 = identical; ~0.0 = unrelated.

Lazy singleton: one embedder per process. First call triggers the BoxMOT
weight download (~3 MB, cached to the venv). If BoxMOT is unavailable,
``get_embedder()`` returns ``None`` and callers fall back to position-only
matching.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass


_LOCK = threading.Lock()
_EMBEDDER: "_OsnetEmbedder | None | bool" = False  # False = not yet tried


class _OsnetEmbedder:
    """Thin wrapper around BoxMOT's OSNet model.

    Exposes a single ``extract(frame_bgr, bboxes) -> np.ndarray`` entry
    point that returns an ``(N, D)`` float32 matrix of L2-normalized
    embeddings. Pieces of size <= 4 px are filtered out upstream — the
    model can't produce anything useful from them.
    """

    def __init__(self) -> None:
        from boxmot.reid.core.reid import ReID

        self._reid = ReID(device="cpu")
        # Probe to determine embedding dimensionality.
        probe_frame = np.zeros((32, 32, 3), dtype=np.uint8)
        probe_boxes = np.array([[0.0, 0.0, 32.0, 32.0]], dtype=np.float32)
        probe = self._reid.model.get_features(probe_boxes, probe_frame)
        self._dim = int(probe.shape[-1]) if probe.ndim == 2 else 0

    @property
    def dim(self) -> int:
        return self._dim

    def extract(
        self,
        frame_bgr: "np.ndarray | None",
        bboxes: list[tuple[int, int, int, int]],
    ) -> "np.ndarray | None":
        """Return an ``(N, D)`` embedding matrix aligned to ``bboxes`` or
        ``None`` if the frame is missing or no bboxes are valid. Invalid
        bboxes yield a zero-row in the output.
        """
        if frame_bgr is None or not bboxes:
            return None
        h, w = frame_bgr.shape[:2]
        arr = np.zeros((len(bboxes), 4), dtype=np.float32)
        valid = np.zeros(len(bboxes), dtype=bool)
        for i, (x1, y1, x2, y2) in enumerate(bboxes):
            x1 = max(0.0, float(x1))
            y1 = max(0.0, float(y1))
            x2 = min(float(w), float(x2))
            y2 = min(float(h), float(y2))
            if x2 - x1 < 4.0 or y2 - y1 < 4.0:
                continue
            arr[i] = [x1, y1, x2, y2]
            valid[i] = True
        if not valid.any():
            return None
        feats = self._reid.model.get_features(arr[valid], frame_bgr)
        if feats is None or feats.size == 0:
            return None
        # Scatter back into full (N, D) array so index alignment with
        # ``bboxes`` is preserved — invalid rows stay as zero vectors that
        # never match anything (similarity always 0).
        out = np.zeros((len(bboxes), feats.shape[-1]), dtype=np.float32)
        out[valid] = feats.astype(np.float32)
        return out


def get_embedder() -> "_OsnetEmbedder | None":
    """Return the shared OSNet embedder, or ``None`` if unavailable.

    The first successful call instantiates the model (downloads weights
    if missing). Subsequent calls return the cached instance. A failed
    load (e.g. no boxmot installed, no network) caches ``None`` so we
    don't keep re-attempting.
    """
    global _EMBEDDER
    with _LOCK:
        if _EMBEDDER is False:
            try:
                _EMBEDDER = _OsnetEmbedder()
            except Exception:
                _EMBEDDER = None
        return _EMBEDDER if _EMBEDDER is not None else None


def cosine_similarity(a: "np.ndarray | None", b: "np.ndarray | None") -> float:
    """Cosine similarity between two L2-normalized vectors. Returns 1.0 if
    either is missing — callers treat missing evidence as neutral.
    """
    if a is None or b is None:
        return 1.0
    n1 = float(np.linalg.norm(a))
    n2 = float(np.linalg.norm(b))
    if n1 == 0.0 or n2 == 0.0:
        return 1.0
    return float(np.dot(a, b) / (n1 * n2))
