"""Registry of all supported teacher adapters.

Adding a new model in this file (and only here) is enough to surface it in the worker, the
sync rerun endpoint, the compare page, and the supported-models allow-list.
"""

from __future__ import annotations

from .base import TeacherAdapter, TeacherDetectionResult, TeacherRateLimitError
from .openrouter_chat import OpenRouterChatAdapter
from .perceptron import PerceptronAdapter


# Note ordering: the first entry is the default if a user hasn't picked anything else.
# Roster trimmed to the four models we actually use in production after comparing the
# wider pool — Grok, Kimi, MiMo, Nemotron, and the Gemini 3.1 Flash Lite tier didn't
# justify keeping in the rotation (either weak bbox quality or duplicated coverage).
# GrokAdapter import is dropped along with its registration; restore both from git if a
# future evaluation brings it back.
_REGISTRY: dict[str, TeacherAdapter] = {}


def register(adapter: TeacherAdapter) -> None:
    _REGISTRY[adapter.model_id] = adapter


# --- Gemini family (Google) — the calibration baseline. -----------------------------------
register(OpenRouterChatAdapter(
    model_id="google/gemini-3-flash-preview",
    display_name="Gemini 3 Flash (preview)",
    notes="Default. Fast, cheap, strong on bbox coordinates.",
))
register(OpenRouterChatAdapter(
    model_id="google/gemini-3.1-pro-preview",
    display_name="Gemini 3.1 Pro (preview)",
    notes="Pro tier. More reliable on edge cases, ~10× cost.",
))
register(OpenRouterChatAdapter(
    model_id="google/gemini-3.5-flash",
    display_name="Gemini 3.5 Flash",
    notes="Newer Flash. ~5× input price of Gemini 3 Flash; check quality wins.",
))


# --- Purpose-built grounding model. -------------------------------------------------------
register(PerceptronAdapter())


def list_adapters() -> list[TeacherAdapter]:
    """Stable ordering — registration order matches the compare page's row order."""
    return list(_REGISTRY.values())


def get_adapter(model_id: str) -> TeacherAdapter | None:
    return _REGISTRY.get(model_id)


def supported_model_ids() -> tuple[str, ...]:
    return tuple(_REGISTRY.keys())


def default_model_id() -> str:
    # First registered entry is the default; today that's Gemini 3 Flash.
    return next(iter(_REGISTRY))


__all__ = [
    "TeacherAdapter",
    "TeacherDetectionResult",
    "TeacherRateLimitError",
    "default_model_id",
    "get_adapter",
    "list_adapters",
    "register",
    "supported_model_ids",
]
