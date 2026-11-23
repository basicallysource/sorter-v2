"""The link model: a small transformer over one question's tokens, as ONNX.

A model directory holds `run.json` and `exports/linker.onnx`. `run.json` names
the layout of the question it was trained on (`format`); a model made for
another layout would answer nonsense rather than fail, so it is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .nodes import FORMAT, N_CAND

KIND = "journey"
MEMBER = "linker.onnx"
DEFAULT_THRESHOLD = 0.9
BATCH = 128


def readRunJson(model_dir: Path) -> dict[str, Any]:
    try:
        raw = json.loads((model_dir / "run.json").read_text())
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def isJourneyModel(model_dir: Path) -> bool:
    return readRunJson(model_dir).get("kind") == KIND


def formatMismatch(meta: dict[str, Any]) -> Optional[str]:
    theirs = meta.get("format")
    if not isinstance(theirs, dict):
        return "run.json has no format"
    for key, ours in FORMAT.items():
        if theirs.get(key) != ours:
            return f"format.{key} is {theirs.get(key)!r}, this build asks {ours!r}"
    return None


class LinkModel:
    def __init__(self, model_dir: Path, threads: int = 1) -> None:
        import onnxruntime as ort

        meta = readRunJson(model_dir)
        problem = formatMismatch(meta)
        if problem is not None:
            raise ValueError(f"{model_dir.name}: {problem}")
        path = model_dir / "exports" / str(meta.get("member") or MEMBER)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        self.name = str(meta.get("name") or model_dir.name)
        threshold = meta.get("predict_threshold")
        self.threshold = float(threshold) if isinstance(threshold, (int, float)) else DEFAULT_THRESHOLD

    def run(self, tokens: np.ndarray, mask: np.ndarray, ctx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """tokens (B, tokens, features), mask (B, tokens) true where a token
        is there, ctx (3, summary). Returns each question's probabilities over
        "none" (slot 0) and its candidate slots, and the probability that its
        anchor is two or more pieces boxed as one."""
        probs = np.zeros((len(tokens), 1 + N_CAND), dtype=np.float32)
        multi = np.zeros(len(tokens), dtype=np.float32)
        ctx32 = np.asarray(ctx, dtype=np.float32)[None]
        for i in range(0, len(tokens), BATCH):
            part = np.asarray(tokens[i : i + BATCH], dtype=np.float32)
            logits, multi_logit = self._session.run(
                None,
                {
                    "tokens": part,
                    "mask": np.asarray(mask[i : i + BATCH], dtype=np.float32),
                    "ctx": np.repeat(ctx32, len(part), axis=0),
                },
            )
            z = logits.astype(np.float64)
            z = np.exp(z - z.max(axis=1, keepdims=True))
            probs[i : i + BATCH] = z / z.sum(axis=1, keepdims=True)
            multi[i : i + BATCH] = 1.0 / (1.0 + np.exp(-multi_logit.astype(np.float64)))
        return probs, multi
