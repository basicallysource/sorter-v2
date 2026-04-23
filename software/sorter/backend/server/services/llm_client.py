"""Project-local LLM client facade on top of LiteLLM.

All LLM calls in the sorter funnel through this module. It pins:

- **the allow-list of usable models** — the UI and detection-config
  surface already assume a small set of Gemini variants on OpenRouter;
- **OpenRouter auth** — reads ``OPENROUTER_API_KEY`` once per call and
  raises a 400 HTTPException if missing, so routers can let it bubble;
- **provider routing** — every model gets the ``openrouter/`` prefix so
  LiteLLM hits OpenRouter regardless of which camera/pipeline called;
- **retry + JSON-mode fallback** for the one-shot JSON advisor path
  (camera-calibration final review, future judge-style calls) — tries
  ``response_format={"type": "json_object"}`` first, falls back to
  plain completion if the provider rejects it, and retries once on an
  unparseable reply with an explicit "give me JSON only" nudge.

Multi-turn flows (e.g. the agentic calibration loop) call
:func:`chat_completion` directly and own their own message bookkeeping —
the client deliberately does not hide the message list.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import litellm
from fastapi import HTTPException


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model allow-list
# ---------------------------------------------------------------------------

DEFAULT_OPENROUTER_MODEL = "google/gemini-3-flash-preview"
SUPPORTED_OPENROUTER_MODELS: tuple[str, ...] = (
    "google/gemini-3-flash-preview",
    "google/gemini-3.1-flash-lite-preview",
    "google/gemini-3.1-pro-preview",
)


def normalize_openrouter_model(model: str | None) -> str:
    """Return a supported model slug, falling back to the default."""
    if isinstance(model, str) and model.strip():
        value = model.strip()
        if value in SUPPORTED_OPENROUTER_MODELS:
            return value
    return DEFAULT_OPENROUTER_MODEL


def _litellm_model(model: str) -> str:
    """Prefix the slug so LiteLLM routes the call to OpenRouter."""
    return f"openrouter/{model}"


def _ensure_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise HTTPException(
            status_code=400,
            detail="OpenRouter API key is not configured for LLM-guided calibration.",
        )
    return key


# ---------------------------------------------------------------------------
# Low-level chat completion
# ---------------------------------------------------------------------------


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    model: str,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
    response_format: dict[str, Any] | None = None,
    temperature: float = 0.1,
    max_tokens: int = 1400,
    timeout: float = 30.0,
) -> Any:
    """Thin LiteLLM ``completion()`` wrapper.

    Returns the raw LiteLLM response object (OpenAI-compatible shape:
    ``response.choices[0].message`` has ``content`` and ``tool_calls``).
    """
    api_key = _ensure_api_key()
    normalized = normalize_openrouter_model(model)

    kwargs: dict[str, Any] = {
        "model": _litellm_model(normalized),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": timeout,
        "api_key": api_key,
    }
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if response_format is not None:
        kwargs["response_format"] = response_format

    return litellm.completion(**kwargs)


# ---------------------------------------------------------------------------
# Chat-content helpers
# ---------------------------------------------------------------------------


def message_text(content: Any) -> str:
    """Flatten a chat-completion ``content`` (str or list of parts) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return str(content or "")


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object embedded in ``text``.

    Tolerates trailing commas (some models still emit those) and raises
    ``RuntimeError`` with a truncated response excerpt if no JSON object
    can be found or parsed. Callers typically wrap this in their own
    try/except and surface the error to the UI trace.
    """
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        excerpt = re.sub(r"\s+", " ", text or "").strip()
        if len(excerpt) > 220:
            excerpt = excerpt[:217] + "..."
        raise RuntimeError(
            "Model response did not contain JSON."
            + (f" Response excerpt: {excerpt}" if excerpt else "")
        )
    raw = match.group()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise RuntimeError("Model response did not contain a JSON object.")
    return parsed


# ---------------------------------------------------------------------------
# One-shot JSON advisor with retry
# ---------------------------------------------------------------------------


def call_json_advisor(
    prompt_text: str,
    image_b64: str,
    *,
    model: str,
    reference_image_b64: str | None = None,
    timeout: float = 25.0,
) -> dict[str, Any]:
    """Ask the advisor for a JSON object, retrying once on bad JSON.

    Builds a two-image content payload (primary + optional reference),
    requests ``response_format={"type":"json_object"}`` on the first
    attempt, falls back to plain completion if the provider rejects JSON
    mode, and retries with an explicit "reply with JSON only" nudge if
    the first parsed reply is unusable. Used for the final sign-off in
    the camera-calibration flow and any future judge-style calls.
    """
    user_content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt_text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
        },
    ]
    if reference_image_b64:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{reference_image_b64}"},
            }
        )

    base_messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "Return only a valid JSON object. "
                "Do not include markdown, explanation, code fences, or any text before or after the JSON."
            ),
        },
        {"role": "user", "content": user_content},
    ]
    retry_messages: list[dict[str, Any]] = [
        *base_messages,
        {
            "role": "user",
            "content": (
                "Your previous reply was not valid JSON. "
                "Reply again using only a single raw JSON object with keys status, summary, and changes."
            ),
        },
    ]

    last_error: Exception | None = None
    last_text = ""

    for messages in (base_messages, retry_messages):
        try:
            try:
                response = chat_completion(
                    messages,
                    model=model,
                    response_format={"type": "json_object"},
                    timeout=timeout,
                )
            except Exception:
                # Some providers reject JSON mode — retry without it.
                response = chat_completion(messages, model=model, timeout=timeout)
            last_text = message_text(response.choices[0].message.content)
            return extract_json_object(last_text)
        except Exception as exc:
            last_error = exc
            continue

    excerpt = re.sub(r"\s+", " ", last_text or "").strip()
    if len(excerpt) > 220:
        excerpt = excerpt[:217] + "..."
    if last_error is None:
        raise RuntimeError("LLM advisor call failed without an error.")
    raise RuntimeError(
        f"LLM advisor call failed after retry: {last_error}"
        + (f" Response excerpt: {excerpt}" if excerpt else "")
    )


__all__ = [
    "DEFAULT_OPENROUTER_MODEL",
    "SUPPORTED_OPENROUTER_MODELS",
    "call_json_advisor",
    "chat_completion",
    "extract_json_object",
    "message_text",
    "normalize_openrouter_model",
]
