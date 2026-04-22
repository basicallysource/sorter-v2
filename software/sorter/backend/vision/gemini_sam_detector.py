"""Minimal post-cutover shim for ``vision.gemini_sam_detector``.

The gemini_sam detector was a one-off OpenRouter-backed detector used as a
fallback when MOG2 couldn't find anything. The rt/ pipeline does not
currently wire it in. Keep just the two public constants / helper that the
detection admin router imports so module-level imports still succeed.
"""

from __future__ import annotations


DEFAULT_OPENROUTER_MODEL = "google/gemini-3-flash-preview"
SUPPORTED_OPENROUTER_MODELS: tuple[str, ...] = (DEFAULT_OPENROUTER_MODEL,)


def normalize_openrouter_model(model: str | None) -> str:
    if isinstance(model, str) and model.strip():
        value = model.strip()
        if value in SUPPORTED_OPENROUTER_MODELS:
            return value
    return DEFAULT_OPENROUTER_MODEL
