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
            "X-Title": "SortHive",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=60) as response:  # noqa: S310
            data = json.loads(response.read().decode())
    except HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        message = None
        if isinstance(payload, dict):
            error_obj = payload.get("error")
            if isinstance(error_obj, dict):
                message = error_obj.get("message")
            if not message:
                message = payload.get("message")
        raise APIError(
            502,
            f"OpenRouter request failed: {message or f'HTTP {exc.code}'}",
            "OPENROUTER_HTTP_ERROR",
        ) from exc
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
    )
