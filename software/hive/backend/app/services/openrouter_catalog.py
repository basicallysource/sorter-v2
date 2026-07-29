from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from app.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Cost baseline. Every model's cost factor is expressed relative to this one, so
# "~1x" always means "about as expensive as Sonnet".
BASELINE_MODEL_ID = "anthropic/claude-sonnet-5"

# A blended price weights output tokens more than input because the profile
# prompts are long but the completions are what actually vary between models.
# Nothing depends on the exact split; it just keeps the factor honest for models
# that are cheap to prompt and expensive to generate.
INPUT_WEIGHT = 0.75
OUTPUT_WEIGHT = 0.25

CACHE_TTL_SECONDS = 6 * 60 * 60

# Curated roster. Order within a group is the order shown. Every id must exist on
# OpenRouter; ids that 404 out of the catalog are dropped at serve time rather
# than shown as broken options.
CURATED_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Recommended",
        (
            "z-ai/glm-5.2",
            "anthropic/claude-sonnet-5",
            "openai/gpt-5.4",
            "deepseek/deepseek-v4-pro",
            "google/gemini-3.6-flash",
        ),
    ),
    (
        "Anthropic",
        (
            "anthropic/claude-fable-5",
            "anthropic/claude-opus-4.7",
            "anthropic/claude-sonnet-5",
            "anthropic/claude-sonnet-4.6",
            "anthropic/claude-haiku-4.5",
        ),
    ),
    (
        "OpenAI",
        (
            "openai/gpt-5.5-pro",
            "openai/gpt-5.5",
            "openai/gpt-5.4-pro",
            "openai/gpt-5.4",
            "openai/gpt-5.4-mini",
            "openai/gpt-5.6-terra",
            "openai/gpt-5.6-luna",
        ),
    ),
    (
        "Google",
        (
            "google/gemini-3.6-flash",
            "google/gemini-3.5-flash",
            "google/gemini-3.1-pro-preview",
            "google/gemini-3-flash-preview",
            "google/gemini-3.1-flash-lite",
        ),
    ),
    (
        "Z.ai (GLM)",
        (
            "z-ai/glm-5.2",
            "z-ai/glm-5.1",
            "z-ai/glm-5",
            "z-ai/glm-5-turbo",
            "z-ai/glm-4.7",
            "z-ai/glm-4.7-flash",
        ),
    ),
    (
        "DeepSeek",
        (
            "deepseek/deepseek-v4-pro",
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v3.2",
        ),
    ),
    (
        "Qwen",
        (
            "qwen/qwen3.7-max",
            "qwen/qwen3.6-max-preview",
            "qwen/qwen3-max",
            "qwen/qwen3-vl-235b-a22b-instruct",
        ),
    ),
    (
        "Moonshot (Kimi)",
        (
            "moonshotai/kimi-k3",
            "moonshotai/kimi-k2.6",
            "moonshotai/kimi-k2-thinking",
        ),
    ),
    (
        "MiniMax",
        (
            "minimax/minimax-m3",
            "minimax/minimax-m2.7",
            "minimax/minimax-m2.5",
        ),
    ),
    (
        "xAI (Grok)",
        (
            "x-ai/grok-4.5",
            "x-ai/grok-4.3",
        ),
    ),
)

_cache_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_fetched_at: float = 0.0


def _perMillion(price: Any) -> float | None:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value * 1_000_000


def _blendedPrice(input_price: float | None, output_price: float | None) -> float | None:
    if input_price is None or output_price is None:
        return None
    return INPUT_WEIGHT * input_price + OUTPUT_WEIGHT * output_price


def _factorLabel(factor: float | None) -> str | None:
    if factor is None:
        return None
    if factor >= 10:
        return f"~{factor:.0f}x"
    if factor >= 1:
        return f"~{round(factor, 1):g}x"
    return f"~{round(factor, 2):g}x"


def _fetchCatalog(api_key: str | None) -> dict[str, dict]:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = requests.get(OPENROUTER_MODELS_URL, headers=headers, timeout=15)
    response.raise_for_status()
    payload = response.json()
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return {}
    catalog: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str):
            continue
        raw_pricing = entry.get("pricing")
        pricing: dict[str, Any] = raw_pricing if isinstance(raw_pricing, dict) else {}
        catalog[model_id] = {
            "name": entry.get("name") if isinstance(entry.get("name"), str) else model_id,
            "input_per_million": _perMillion(pricing.get("prompt")),
            "output_per_million": _perMillion(pricing.get("completion")),
            "context_length": entry.get("context_length"),
        }
    return catalog


def _cachedCatalog(api_key: str | None, force: bool = False) -> dict[str, dict]:
    global _cache, _cache_fetched_at
    with _cache_lock:
        fresh = _cache is not None and (time.time() - _cache_fetched_at) < CACHE_TTL_SECONDS
        if fresh and not force:
            return _cache  # type: ignore[return-value]
    try:
        catalog = _fetchCatalog(api_key)
    except Exception as exc:
        logger.warning("openrouter catalog fetch failed: %s", exc)
        with _cache_lock:
            # A stale catalog beats no pricing at all; only a cold cache gives up.
            return _cache or {}
    with _cache_lock:
        _cache = catalog
        _cache_fetched_at = time.time()
    return catalog


def listCuratedModels(api_key: str | None = None, force_refresh: bool = False) -> dict[str, Any]:
    catalog = _cachedCatalog(api_key, force=force_refresh)

    baseline = catalog.get(BASELINE_MODEL_ID) or {}
    baseline_blended = _blendedPrice(
        baseline.get("input_per_million"), baseline.get("output_per_million")
    )

    groups: list[dict[str, Any]] = []
    for label, model_ids in CURATED_GROUPS:
        models: list[dict[str, Any]] = []
        for model_id in model_ids:
            entry = catalog.get(model_id)
            if entry is None:
                continue
            blended = _blendedPrice(entry["input_per_million"], entry["output_per_million"])
            factor = (
                blended / baseline_blended
                if blended is not None and baseline_blended
                else None
            )
            models.append(
                {
                    "id": model_id,
                    "name": entry["name"],
                    "input_per_million": entry["input_per_million"],
                    "output_per_million": entry["output_per_million"],
                    "cost_factor": round(factor, 4) if factor is not None else None,
                    "cost_factor_label": _factorLabel(factor),
                    "context_length": entry.get("context_length"),
                }
            )
        if models:
            groups.append({"label": label, "models": models})

    return {
        "default_model": settings.DEFAULT_AI_MODEL,
        "baseline_model": BASELINE_MODEL_ID,
        "pricing_available": bool(catalog),
        "groups": groups,
    }
