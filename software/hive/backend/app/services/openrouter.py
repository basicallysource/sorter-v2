from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings
from app.errors import APIError


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class OpenRouterResponse:
    content: str
    model: str
    usage: dict[str, Any] | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    generation_id: str | None = None


# OpenRouter answers 401/402/403/429 about the caller's own account: the key
# the user pasted into Settings is wrong, or its account has no credits, or it
# is being throttled. Those used to come back as a 502 "OpenRouter request
# failed: <upstream text>", which reads as a Hive outage and gets reported as
# one (2026-09-07: a user retried a no-credits key fifteen times and filed it as
# "I got a 502"). They are the user's to fix, so they get a 4xx, a stable code
# the frontend can point at Settings for, and a message that says what to do.
# Everything else really is upstream failing and stays a 502.
def _apiErrorForOpenRouterStatus(status: int, upstream_message: str | None) -> APIError:
    detail = f" (OpenRouter said: {upstream_message})" if upstream_message else ""
    if status == 402:
        return APIError(
            402,
            "Your OpenRouter account has no credits. Add credits at openrouter.ai, or switch to a key from a funded account in Settings."
            + detail,
            "OPENROUTER_NO_CREDITS",
        )
    if status in (401, 403):
        return APIError(
            400,
            "OpenRouter rejected your API key. Check the key in Settings." + detail,
            "OPENROUTER_KEY_REJECTED",
        )
    if status == 429:
        return APIError(
            429,
            "OpenRouter is rate limiting your key. Wait a moment and try again." + detail,
            "OPENROUTER_RATE_LIMITED",
        )
    return APIError(
        502,
        f"OpenRouter request failed: {upstream_message or f'HTTP {status}'}",
        "OPENROUTER_HTTP_ERROR",
    )


def run_openrouter_chat(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.2,
    max_tokens: int = 2400,
    response_format: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    cache_control: dict[str, Any] | None = None,
) -> OpenRouterResponse:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # Without this OpenRouter returns token counts but no price, and the
        # only other way to get the cost of a call is a follow-up request to
        # /generation with the generation id.
        "usage": {"include": True},
    }
    if response_format is not None:
        payload["response_format"] = response_format
    if tools:
        payload["tools"] = tools
    if cache_control is not None:
        payload["cache_control"] = cache_control

    body = json.dumps(payload).encode()
    request = Request(
        f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.public_app_url,
            "X-Title": "Hive",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=60) as response:  # noqa: S310
            data = json.loads(response.read().decode())
    except HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            error_payload = json.loads(raw)
        except json.JSONDecodeError:
            error_payload = None
        message = None
        if isinstance(error_payload, dict):
            error_obj = error_payload.get("error")
            if isinstance(error_obj, dict):
                message = error_obj.get("message")
            if not message:
                message = error_payload.get("message")
        raise _apiErrorForOpenRouterStatus(exc.code, message) from exc
    except URLError as exc:
        raise APIError(502, "OpenRouter could not be reached", "OPENROUTER_NETWORK_ERROR") from exc

    try:
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content") or ""
        finish_reason = choice.get("finish_reason")
    except (KeyError, IndexError, TypeError) as exc:
        raise APIError(502, "OpenRouter returned an unexpected response", "OPENROUTER_INVALID_RESPONSE") from exc

    parsed_tool_calls: list[ToolCall] = []
    raw_tool_calls = msg.get("tool_calls") or []
    for tc in raw_tool_calls:
        try:
            fn = tc["function"]
            args_str = fn.get("arguments", "{}")
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
            parsed_tool_calls.append(ToolCall(
                id=tc["id"],
                name=fn["name"],
                arguments=args if isinstance(args, dict) else {},
            ))
        except (KeyError, json.JSONDecodeError, TypeError):
            continue

    if not content and not parsed_tool_calls:
        raise APIError(502, "OpenRouter returned an empty response", "OPENROUTER_EMPTY_RESPONSE")

    return OpenRouterResponse(
        content=content,
        model=str(data.get("model") or model),
        usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
        tool_calls=parsed_tool_calls,
        finish_reason=finish_reason,
        generation_id=str(data["id"]) if data.get("id") else None,
    )
