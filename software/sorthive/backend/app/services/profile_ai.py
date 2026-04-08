from __future__ import annotations

import copy
import json
import logging
import re
from time import perf_counter
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app.config import settings
from app.errors import APIError
from app.models.user import User
from app.services.openrouter import OpenRouterResponse, run_openrouter_chat
from app.services.profile_builder_compat import builder_sorting_profile
from app.services.profile_catalog import ProfileCatalogService
from app.services.secrets import decrypt_secret

logger = logging.getLogger("uvicorn.error").getChild("profile_ai")


VALID_FIELDS = {
    "name",
    "part_num",
    "category_id",
    "category_name",
    "color_id",
    "year_from",
    "year_to",
    "bricklink_id",
    "bricklink_item_count",
    "bricklink_primary_item_no",
    "bl_price_min",
    "bl_price_max",
    "bl_price_avg",
    "bl_price_qty_avg",
    "bl_price_lots",
    "bl_price_qty",
    "bl_catalog_name",
    "bl_catalog_category_id",
    "bl_category_id",
    "bl_category_name",
    "bl_catalog_year_released",
    "bl_catalog_weight",
    "bl_catalog_dim_x",
    "bl_catalog_dim_y",
    "bl_catalog_dim_z",
    "bl_catalog_is_obsolete",
}

VALID_OPS = {"eq", "neq", "in", "contains", "regex", "gte", "lte"}

FIELD_OPS = {
    "name": {"contains", "regex"},
    "part_num": {"eq", "neq", "in"},
    "category_id": {"eq", "neq", "in"},
    "category_name": {"contains", "regex"},
    "color_id": {"eq", "neq", "in"},
    "year_from": {"eq", "neq", "gte", "lte"},
    "year_to": {"eq", "neq", "gte", "lte"},
    "bricklink_id": {"eq", "neq", "in"},
    "bricklink_item_count": {"eq", "neq", "gte", "lte"},
    "bricklink_primary_item_no": {"eq", "neq", "contains", "regex"},
    "bl_price_min": {"eq", "neq", "gte", "lte"},
    "bl_price_max": {"eq", "neq", "gte", "lte"},
    "bl_price_avg": {"eq", "neq", "gte", "lte"},
    "bl_price_qty_avg": {"eq", "neq", "gte", "lte"},
    "bl_price_lots": {"eq", "neq", "gte", "lte"},
    "bl_price_qty": {"eq", "neq", "gte", "lte"},
    "bl_catalog_name": {"contains", "regex"},
    "bl_catalog_category_id": {"eq", "neq", "in"},
    "bl_category_id": {"eq", "neq", "in"},
    "bl_category_name": {"contains", "regex"},
    "bl_catalog_year_released": {"eq", "neq", "gte", "lte"},
    "bl_catalog_weight": {"eq", "neq", "gte", "lte"},
    "bl_catalog_dim_x": {"eq", "neq", "gte", "lte"},
    "bl_catalog_dim_y": {"eq", "neq", "gte", "lte"},
    "bl_catalog_dim_z": {"eq", "neq", "gte", "lte"},
    "bl_catalog_is_obsolete": {"eq", "neq"},
}

MAX_TOOL_ROUNDS = 5
CUSTOM_SET_INTENT_RE = re.compile(
    r"\b(custom\s+(set|kit|bundle|order|pack)|custom\s+kit[s]?|customer\s+order|not\s+a?\s*real\s+set|parts?\s+bundle|parts?\s+kit)\b",
    re.IGNORECASE,
)


# --- Tool definitions for the LLM ---

_SEARCH_PARTS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_parts",
        "description": (
            "Search the LEGO parts catalog by name, part number, or keyword. "
            "Returns matching parts with their category, BrickLink info, and year range. "
            "Only use this when you need to look up specific parts or verify part numbers. "
            "Category and color lists are already in your context."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term — part name, number, or keyword (e.g. 'technic beam', '32063', 'gear 20 tooth')",
                },
                "category_id": {
                    "type": "integer",
                    "description": "Optional Rebrickable category ID to filter results",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20, max 50)",
                },
            },
            "required": ["query"],
        },
    },
}

_SEARCH_SETS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_sets",
        "description": (
            "Search for LEGO sets by name, theme, or set number. "
            "Returns set name, number, year, part count, and image URL. "
            "Use this when the user wants to sort parts from specific LEGO sets. "
            "Use min_year/max_year to filter by release year. "
            "Results exclude books and non-brick items by default."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term — set name, number, or theme (e.g. 'Space Shuttle', '10283', 'Minecraft')",
                },
                "min_year": {
                    "type": "integer",
                    "description": "Minimum release year (e.g. 2020)",
                },
                "max_year": {
                    "type": "integer",
                    "description": "Maximum release year (e.g. 2023)",
                },
            },
            "required": ["query"],
        },
    },
}

_GET_SET_INVENTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "get_set_inventory",
        "description": (
            "Get the parts inventory for a specific LEGO set number. "
            "Returns the unique inventory lines with part number, part name, color, quantity, and spare flag. "
            "Use this after search_sets when the user wants to know what pieces are inside a specific set."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "set_num": {
                    "type": "string",
                    "description": "The Rebrickable set number, e.g. '10305-1'",
                },
                "include_spares": {
                    "type": "boolean",
                    "description": "Whether to include spare parts in the inventory (default false)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max inventory rows to return (default 200, max 500)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Inventory row offset for pagination (default 0)",
                },
            },
            "required": ["set_num"],
        },
    },
}

# search_sets is always available (only needs Rebrickable API key);
# get_set_inventory is always available too; search_parts requires synced parts data
CATALOG_TOOLS = [_SEARCH_PARTS_TOOL, _SEARCH_SETS_TOOL, _GET_SET_INVENTORY_TOOL]
SET_ONLY_TOOLS = [_SEARCH_SETS_TOOL, _GET_SET_INVENTORY_TOOL]

PROPOSAL_RESPONSE_FORMAT = {"type": "json_object"}


@dataclass
class AiToolTraceEntry:
    tool: str
    input: dict[str, Any]
    output_summary: str
    output: dict[str, Any] | None = None
    duration_ms: float | None = None


@dataclass
class AiToolExecutionResult:
    content: str
    trace_output: dict[str, Any] | None = None


@dataclass
class AiProgressEvent:
    """Yielded during streaming to inform the frontend of progress."""
    type: str  # "tool_call", "tool_result", "generating"
    data: dict[str, Any]


@dataclass
class AiProposalResult:
    content: str
    proposal: dict[str, Any] | None
    model: str
    usage: dict[str, Any] | None
    tool_trace: list[AiToolTraceEntry]
    performance: dict[str, Any] | None = None


def get_user_openrouter_key(user: User) -> str:
    api_key = decrypt_secret(user.openrouter_api_key_encrypted)
    if api_key:
        return api_key
    raise APIError(400, "No OpenRouter key configured for this account", "OPENROUTER_KEY_MISSING")


def _looks_like_custom_set_request(message: str) -> bool:
    return bool(CUSTOM_SET_INTENT_RE.search(message or ""))


def _custom_set_intent_note() -> str:
    return (
        "The user's request is about a custom part bundle or kit, not an official LEGO set. "
        "Prefer search_parts and create_custom_set. "
        "Do not use search_sets unless the user explicitly asks for real LEGO sets."
    )


def _custom_set_catalog_unavailable_result(model: str) -> AiProposalResult:
    return AiProposalResult(
        content=(
            "Custom kits use individual part numbers and quantities. "
            "The parts catalog is not synced on this SortHive instance yet, so I can't build a precise custom kit from chat right now.\n\n"
            "You can either sync the parts catalog first, or add a Custom Set manually and search for parts there."
        ),
        proposal=None,
        model=model,
        usage=None,
        tool_trace=[],
        performance=None,
    )


def generate_profile_ai_proposal(
    *,
    user: User,
    catalog: ProfileCatalogService,
    document: dict[str, Any],
    message: str,
    conversation_history: list[dict[str, str]] | None = None,
    selected_rule_id: str | None = None,
    ai_request_id: str | None = None,
) -> AiProposalResult:
    request_id = ai_request_id or uuid.uuid4().hex[:12]
    started_at = perf_counter()
    model = user.preferred_ai_model or settings.DEFAULT_AI_MODEL
    has_parts = bool(catalog.parts_data.parts)
    custom_set_request = _looks_like_custom_set_request(message)
    normalized_history = _normalize_conversation_history(conversation_history)
    tool_names = [tool["function"]["name"] for tool in (CATALOG_TOOLS if has_parts else SET_ONLY_TOOLS)]
    _log_ai_event(
        "start",
        {
            "request_id": request_id,
            "model": model,
            "has_parts_catalog": has_parts,
            "custom_set_request": custom_set_request,
            "tool_names": tool_names,
            "message_chars": len(message or ""),
            "conversation_messages": len(normalized_history),
            "selected_rule_id": selected_rule_id,
        },
    )

    if custom_set_request and not has_parts:
        result = _custom_set_catalog_unavailable_result(model)
        performance = {
            "request_id": request_id,
            "short_circuit": True,
            "round_count": 0,
            "tool_call_count": 0,
            "llm_ms": 0.0,
            "tool_ms": 0.0,
            "total_ms": _elapsed_ms(started_at),
        }
        _log_ai_event("short_circuit", performance)
        result.performance = performance
        return result

    try:
        api_key = get_user_openrouter_key(user)
        tools = CATALOG_TOOLS if has_parts else SET_ONLY_TOOLS
        cache_control = _profile_ai_cache_control(model)

        system_prompt = _build_system_prompt(catalog, document, selected_rule_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        if custom_set_request:
            messages.append({"role": "system", "content": _custom_set_intent_note()})
        messages.extend(normalized_history)
        messages.append({"role": "user", "content": message})

        total_usage: dict[str, int] = {}
        final_model = model
        tool_trace: list[AiToolTraceEntry] = []
        set_search_observations: list[dict[str, Any]] = []
        part_search_observations: list[dict[str, Any]] = []
        llm_total_ms = 0.0
        tool_total_ms = 0.0
        rounds: list[dict[str, Any]] = []

        for round_index in range(MAX_TOOL_ROUNDS + 1):
            llm_started_at = perf_counter()
            response = run_openrouter_chat(
                api_key=api_key,
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=8192,
                tools=tools,
                cache_control=cache_control,
            )
            llm_ms = _elapsed_ms(llm_started_at)
            llm_total_ms += llm_ms
            final_model = response.model
            _accumulate_usage(total_usage, response.usage)
            response_cache_metrics = _usage_cache_metrics(response.usage)
            aggregate_cache_metrics = _usage_cache_metrics(total_usage)

            round_summary = {
                "round": round_index + 1,
                "llm_ms": llm_ms,
                "finish_reason": response.finish_reason,
                "tool_call_count": len(response.tool_calls),
                "prompt_tokens": total_usage.get("prompt_tokens"),
                "completion_tokens": total_usage.get("completion_tokens"),
                "total_tokens": total_usage.get("total_tokens"),
                "cached_tokens": aggregate_cache_metrics.get("cached_tokens", 0),
                "cache_write_tokens": aggregate_cache_metrics.get("cache_write_tokens", 0),
            }
            rounds.append(round_summary)
            _log_ai_event(
                "round",
                {
                    "request_id": request_id,
                    "model": response.model,
                    "cache_control": cache_control,
                    **response_cache_metrics,
                    **round_summary,
                },
            )

            if not response.tool_calls:
                break

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": response.content or None}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in response.tool_calls
            ]
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                tool_started_at = perf_counter()
                try:
                    execution = _execute_tool(catalog, tc.name, tc.arguments)
                except Exception:
                    _log_ai_event(
                        "tool_failed",
                        {
                            "request_id": request_id,
                            "round": round_index + 1,
                            "tool": tc.name,
                            "duration_ms": _elapsed_ms(tool_started_at),
                        },
                    )
                    raise
                tool_ms = _elapsed_ms(tool_started_at)
                tool_total_ms += tool_ms

                output = execution.trace_output if execution.trace_output is not None else _parse_tool_output(execution.content)
                summary = _summarize_tool_result(tc.name, tc.arguments, output or execution.content)
                tool_trace.append(
                    AiToolTraceEntry(
                        tool=tc.name,
                        input=tc.arguments,
                        output_summary=summary,
                        output=output,
                        duration_ms=tool_ms,
                    )
                )
                if tc.name == "search_sets":
                    set_search_observations.append({
                        "input": tc.arguments,
                        "sets": _extract_search_sets_results(output or execution.content),
                    })
                if tc.name == "search_parts":
                    part_search_observations.append({
                        "input": tc.arguments,
                        "parts": _extract_search_parts_results(output or execution.content),
                    })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": execution.content,
                })
                _log_ai_event(
                    "tool",
                    {
                        "request_id": request_id,
                        "round": round_index + 1,
                        "tool": tc.name,
                        "duration_ms": tool_ms,
                        **_tool_output_metrics(tc.name, output),
                    },
                )
        else:
            raise APIError(502, "AI used too many tool calls without producing a result", "AI_TOO_MANY_ROUNDS")

        assistant_content, proposal = _finalize_ai_response(
            response=response,
            set_search_observations=set_search_observations,
            part_search_observations=part_search_observations,
            catalog=catalog,
        )
        performance = {
            "request_id": request_id,
            "round_count": len(rounds),
            "tool_call_count": len(tool_trace),
            "llm_ms": round(llm_total_ms, 1),
            "tool_ms": round(tool_total_ms, 1),
            "total_ms": _elapsed_ms(started_at),
            **_usage_cache_metrics(total_usage),
            "rounds": rounds,
        }
        _log_ai_event(
            "complete",
            {
                "request_id": request_id,
                "model": final_model,
                "proposal_count": len(proposal.get("proposals", [])) if proposal else 0,
                "summary_chars": len(assistant_content or ""),
                "usage": total_usage or None,
                **{key: performance[key] for key in ("round_count", "tool_call_count", "llm_ms", "tool_ms", "total_ms")},
            },
        )
        return AiProposalResult(
            content=assistant_content,
            proposal=proposal,
            model=final_model,
            usage=total_usage or None,
            tool_trace=tool_trace,
            performance=performance,
        )
    except Exception:
        _log_ai_event(
            "failed",
            {
                "request_id": request_id,
                "model": model,
                "elapsed_ms": _elapsed_ms(started_at),
            },
        )
        raise


def generate_profile_ai_proposal_streaming(
    *,
    user: User,
    catalog: ProfileCatalogService,
    document: dict[str, Any],
    message: str,
    conversation_history: list[dict[str, str]] | None = None,
    selected_rule_id: str | None = None,
    ai_request_id: str | None = None,
) -> Generator[AiProgressEvent | AiProposalResult, None, None]:
    """Like generate_profile_ai_proposal but yields progress events during tool use."""
    request_id = ai_request_id or uuid.uuid4().hex[:12]
    started_at = perf_counter()
    model = user.preferred_ai_model or settings.DEFAULT_AI_MODEL
    has_parts = bool(catalog.parts_data.parts)
    custom_set_request = _looks_like_custom_set_request(message)
    normalized_history = _normalize_conversation_history(conversation_history)
    tool_names = [tool["function"]["name"] for tool in (CATALOG_TOOLS if has_parts else SET_ONLY_TOOLS)]
    _log_ai_event(
        "start",
        {
            "request_id": request_id,
            "model": model,
            "has_parts_catalog": has_parts,
            "custom_set_request": custom_set_request,
            "tool_names": tool_names,
            "message_chars": len(message or ""),
            "conversation_messages": len(normalized_history),
            "selected_rule_id": selected_rule_id,
            "streaming": True,
        },
    )

    if custom_set_request and not has_parts:
        result = _custom_set_catalog_unavailable_result(model)
        performance = {
            "request_id": request_id,
            "short_circuit": True,
            "round_count": 0,
            "tool_call_count": 0,
            "llm_ms": 0.0,
            "tool_ms": 0.0,
            "total_ms": _elapsed_ms(started_at),
        }
        _log_ai_event("short_circuit", {**performance, "streaming": True})
        result.performance = performance
        yield result
        return

    try:
        api_key = get_user_openrouter_key(user)
        tools = CATALOG_TOOLS if has_parts else SET_ONLY_TOOLS
        cache_control = _profile_ai_cache_control(model)

        system_prompt = _build_system_prompt(catalog, document, selected_rule_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        if custom_set_request:
            messages.append({"role": "system", "content": _custom_set_intent_note()})
        messages.extend(normalized_history)
        messages.append({"role": "user", "content": message})

        total_usage: dict[str, int] = {}
        final_model = model
        tool_trace: list[AiToolTraceEntry] = []
        set_search_observations: list[dict[str, Any]] = []
        part_search_observations: list[dict[str, Any]] = []
        llm_total_ms = 0.0
        tool_total_ms = 0.0
        rounds: list[dict[str, Any]] = []

        for round_index in range(MAX_TOOL_ROUNDS + 1):
            yield AiProgressEvent(type="thinking", data={"round": round_index + 1})

            llm_started_at = perf_counter()
            response = run_openrouter_chat(
                api_key=api_key,
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=8192,
                tools=tools,
                cache_control=cache_control,
            )
            llm_ms = _elapsed_ms(llm_started_at)
            llm_total_ms += llm_ms
            final_model = response.model
            _accumulate_usage(total_usage, response.usage)
            response_cache_metrics = _usage_cache_metrics(response.usage)
            aggregate_cache_metrics = _usage_cache_metrics(total_usage)

            round_summary = {
                "round": round_index + 1,
                "llm_ms": llm_ms,
                "finish_reason": response.finish_reason,
                "tool_call_count": len(response.tool_calls),
                "prompt_tokens": total_usage.get("prompt_tokens"),
                "completion_tokens": total_usage.get("completion_tokens"),
                "total_tokens": total_usage.get("total_tokens"),
                "cached_tokens": aggregate_cache_metrics.get("cached_tokens", 0),
                "cache_write_tokens": aggregate_cache_metrics.get("cache_write_tokens", 0),
            }
            rounds.append(round_summary)
            _log_ai_event(
                "round",
                {
                    "request_id": request_id,
                    "model": response.model,
                    "streaming": True,
                    "cache_control": cache_control,
                    **response_cache_metrics,
                    **round_summary,
                },
            )

            if not response.tool_calls:
                break

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": response.content or None}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in response.tool_calls
            ]
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                yield AiProgressEvent(type="tool_call", data={"tool": tc.name, "input": tc.arguments})

                tool_started_at = perf_counter()
                try:
                    execution = _execute_tool(catalog, tc.name, tc.arguments)
                except Exception:
                    _log_ai_event(
                        "tool_failed",
                        {
                            "request_id": request_id,
                            "round": round_index + 1,
                            "tool": tc.name,
                            "duration_ms": _elapsed_ms(tool_started_at),
                            "streaming": True,
                        },
                    )
                    raise
                tool_ms = _elapsed_ms(tool_started_at)
                tool_total_ms += tool_ms

                output = execution.trace_output if execution.trace_output is not None else _parse_tool_output(execution.content)
                summary = _summarize_tool_result(tc.name, tc.arguments, output or execution.content)
                trace_entry = AiToolTraceEntry(
                    tool=tc.name,
                    input=tc.arguments,
                    output_summary=summary,
                    output=output,
                    duration_ms=tool_ms,
                )
                tool_trace.append(trace_entry)
                if tc.name == "search_sets":
                    set_search_observations.append({
                        "input": tc.arguments,
                        "sets": _extract_search_sets_results(output or execution.content),
                    })
                if tc.name == "search_parts":
                    part_search_observations.append({
                        "input": tc.arguments,
                        "parts": _extract_search_parts_results(output or execution.content),
                    })

                yield AiProgressEvent(type="tool_result", data={
                    "tool": tc.name,
                    "input": tc.arguments,
                    "output_summary": summary,
                    "output": output,
                    "duration_ms": tool_ms,
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": execution.content,
                })
                _log_ai_event(
                    "tool",
                    {
                        "request_id": request_id,
                        "round": round_index + 1,
                        "tool": tc.name,
                        "duration_ms": tool_ms,
                        "streaming": True,
                        **_tool_output_metrics(tc.name, output),
                    },
                )
        else:
            raise APIError(502, "AI used too many tool calls without producing a result", "AI_TOO_MANY_ROUNDS")

        yield AiProgressEvent(type="generating", data={})

        assistant_content, proposal = _finalize_ai_response(
            response=response,
            set_search_observations=set_search_observations,
            part_search_observations=part_search_observations,
            catalog=catalog,
        )
        performance = {
            "request_id": request_id,
            "round_count": len(rounds),
            "tool_call_count": len(tool_trace),
            "llm_ms": round(llm_total_ms, 1),
            "tool_ms": round(tool_total_ms, 1),
            "total_ms": _elapsed_ms(started_at),
            **_usage_cache_metrics(total_usage),
            "rounds": rounds,
        }
        _log_ai_event(
            "complete",
            {
                "request_id": request_id,
                "model": final_model,
                "proposal_count": len(proposal.get("proposals", [])) if proposal else 0,
                "summary_chars": len(assistant_content or ""),
                "usage": total_usage or None,
                "streaming": True,
                **{key: performance[key] for key in ("round_count", "tool_call_count", "llm_ms", "tool_ms", "total_ms")},
            },
        )
        yield AiProposalResult(
            content=assistant_content,
            proposal=proposal,
            model=final_model,
            usage=total_usage or None,
            tool_trace=tool_trace,
            performance=performance,
        )
    except Exception:
        _log_ai_event(
            "failed",
            {
                "request_id": request_id,
                "model": model,
                "elapsed_ms": _elapsed_ms(started_at),
                "streaming": True,
            },
        )
        raise


def _accumulate_usage(total: dict[str, Any], usage: dict[str, Any] | None) -> None:
    if not usage:
        return
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in usage:
            total[key] = total.get(key, 0) + int(usage[key])
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        total_details = total.setdefault("prompt_tokens_details", {})
        if isinstance(total_details, dict):
            for key in ("cached_tokens", "cache_write_tokens"):
                if key in details:
                    total_details[key] = int(total_details.get(key, 0)) + int(details[key])


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 1)


def _profile_ai_cache_control(model: str) -> dict[str, Any] | None:
    if not settings.PROFILE_AI_PROMPT_CACHE_ENABLED:
        return None
    if not str(model).startswith("anthropic/claude"):
        return None
    payload: dict[str, Any] = {"type": "ephemeral"}
    ttl = (settings.PROFILE_AI_PROMPT_CACHE_TTL or "").strip()
    if ttl:
        payload["ttl"] = ttl
    return payload


def _usage_cache_metrics(usage: dict[str, Any] | None) -> dict[str, int]:
    if not usage:
        return {}
    details = usage.get("prompt_tokens_details")
    if not isinstance(details, dict):
        return {}
    metrics: dict[str, int] = {}
    for key in ("cached_tokens", "cache_write_tokens"):
        if key in details:
            metrics[key] = int(details[key])
    return metrics


def _log_ai_event(event: str, payload: dict[str, Any]) -> None:
    logger.info("profile_ai.%s %s", event, json.dumps(payload, sort_keys=True, default=str))


def _tool_output_metrics(tool_name: str, output: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}

    metrics: dict[str, Any] = {}
    total = output.get("total")
    if isinstance(total, int):
        metrics["result_total"] = total
    showing = output.get("showing")
    if isinstance(showing, int):
        metrics["result_showing"] = showing

    if tool_name == "get_set_inventory":
        set_meta = output.get("set")
        if isinstance(set_meta, dict):
            set_num = set_meta.get("set_num")
            if isinstance(set_num, str) and set_num:
                metrics["set_num"] = set_num
    return metrics


def _summarize_tool_result(tool_name: str, args: dict[str, Any], raw_result: str | dict[str, Any]) -> str:
    if isinstance(raw_result, dict):
        data = raw_result
    else:
        try:
            data = json.loads(raw_result)
        except json.JSONDecodeError:
            return raw_result[:200]

    if tool_name == "search_parts":
        query = args.get("query", "")
        total = data.get("total", 0)
        parts = data.get("parts", [])
        if total == 0:
            return f'No parts found for "{query}"'
        lines = [f'Found {total} parts for "{query}":', ""]
        shown = min(len(parts), 5)
        for part in parts[:shown]:
            name = part.get("name", "?")
            part_num = part.get("part_num", "?")
            lines.append(f"- {name} ({part_num})")
        if total > shown:
            lines.append(f"- ...and {total - shown} more")
        return "\n".join(lines)

    if tool_name == "search_sets":
        query = args.get("query", "")
        sets = data.get("sets", [])
        total = data.get("total", 0)
        if total == 0:
            return f'No sets found for "{query}"'
        lines = [f'Found {total} sets for "{query}":', ""]
        shown = min(len(sets), 5)
        for lego_set in sets[:5]:
            lines.append(f'- {lego_set.get("name", "?")} ({lego_set.get("set_num", "?")})')
        if total > shown:
            lines.append(f"- ...and {total - shown} more")
        return "\n".join(lines)

    if tool_name == "get_set_inventory":
        set_meta = data.get("set", {})
        inventory = data.get("inventory", [])
        total = data.get("total", 0)
        set_num = set_meta.get("set_num") or args.get("set_num") or "unknown set"
        set_name = set_meta.get("name") or set_num
        if total == 0:
            return f'No inventory entries found for "{set_name}" ({set_num})'
        lines = [f'Found {total} inventory entries in "{set_name}" ({set_num}):', ""]
        shown = min(len(inventory), 5)
        for item in inventory[:shown]:
            name = item.get("part_name") or item.get("part_num") or "Unknown part"
            part_num = item.get("part_num") or "?"
            color = item.get("color_name") or item.get("color_id") or "Unknown color"
            quantity = item.get("quantity") or 0
            suffix = " · spare" if item.get("is_spare") else ""
            lines.append(f"- {name} ({part_num}) · {color} · qty {quantity}{suffix}")
        if total > shown:
            lines.append(f"- ...and {total - shown} more")
        return "\n".join(lines)

    return json.dumps(data)[:200]


def _normalize_conversation_history(
    conversation_history: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    if not conversation_history:
        return []

    normalized: list[dict[str, str]] = []
    for item in conversation_history:
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str):
            continue
        stripped = content.strip()
        if not stripped:
            continue
        normalized.append({"role": role, "content": stripped})
    return normalized


def _parse_tool_output(raw_result: str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(raw_result, dict):
        return raw_result
    try:
        data = json.loads(raw_result)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _extract_search_sets_results(raw_result: str | dict[str, Any]) -> list[dict[str, Any]]:
    data = _parse_tool_output(raw_result)
    if not isinstance(data, dict):
        return []
    sets = data.get("sets")
    if not isinstance(sets, list):
        return []
    return [lego_set for lego_set in sets if isinstance(lego_set, dict)]


def _extract_search_parts_results(raw_result: str | dict[str, Any]) -> list[dict[str, Any]]:
    data = _parse_tool_output(raw_result)
    if not isinstance(data, dict):
        return []
    parts = data.get("parts")
    if not isinstance(parts, list):
        return []
    return [part for part in parts if isinstance(part, dict)]


def _format_search_sets_attempt(args: dict[str, Any]) -> str:
    query = str(args.get("query") or "").strip() or "that query"
    min_year = args.get("min_year")
    max_year = args.get("max_year")
    if min_year is not None and max_year is not None and min_year == max_year:
        return f'"{query}" from {min_year}'
    if min_year is not None and max_year is not None:
        return f'"{query}" from {min_year} to {max_year}'
    if min_year is not None:
        return f'"{query}" from {min_year} or newer'
    if max_year is not None:
        return f'"{query}" up to {max_year}'
    return f'"{query}"'


def _ground_create_set_proposals(
    proposal: dict[str, Any],
    set_search_observations: list[dict[str, Any]],
) -> None:
    catalog_sets: dict[str, dict[str, Any]] = {}
    for observation in set_search_observations:
        for lego_set in observation.get("sets", []):
            set_num = str(lego_set.get("set_num") or "")
            if set_num:
                catalog_sets[set_num] = lego_set

    for item in proposal.get("proposals", []):
        if item.get("action") != "create_set":
            continue
        set_num = str(item.get("set_num") or "")
        matched_set = catalog_sets.get(set_num)
        if matched_set is None:
            raise APIError(
                502,
                f"AI create_set proposal referenced '{set_num}', which was not returned by search_sets",
                "AI_SET_NOT_FROM_SEARCH",
            )
        item["name"] = matched_set.get("name") or item.get("name") or set_num
        item["set_meta"] = {
            "name": matched_set.get("name") or item.get("name") or set_num,
            "year": matched_set.get("year"),
            "num_parts": matched_set.get("num_parts"),
            "img_url": matched_set.get("img_url") or matched_set.get("set_img_url"),
        }


def _ground_custom_set_proposals(
    proposal: dict[str, Any],
    part_search_observations: list[dict[str, Any]],
    catalog: ProfileCatalogService | None = None,
) -> None:
    catalog_parts: dict[str, dict[str, Any]] = {}
    for observation in part_search_observations:
        for part in observation.get("parts", []):
            part_num = str(part.get("part_num") or "")
            if part_num:
                catalog_parts[part_num] = part

    for item in proposal.get("proposals", []):
        if item.get("action") != "create_custom_set":
            continue
        custom_parts = item.get("custom_parts")
        if not isinstance(custom_parts, list) or not custom_parts:
            raise APIError(502, "AI create_custom_set proposal missing custom_parts", "AI_CUSTOM_SET_PARTS_MISSING")

        normalized_parts: list[dict[str, Any]] = []
        total_quantity = 0
        for raw_part in custom_parts:
            if not isinstance(raw_part, dict):
                raise APIError(502, "AI custom set part entry is invalid", "AI_CUSTOM_SET_PARTS_INVALID")
            part_num = str(raw_part.get("part_num") or "").strip()
            matched_part = catalog_parts.get(part_num)
            if matched_part is None and catalog is not None:
                matched_part = _lookup_exact_catalog_part(catalog, part_num)
            if matched_part is None:
                raise APIError(
                    502,
                    f"AI custom set proposal referenced '{part_num}', which was not returned by search_parts",
                    "AI_CUSTOM_SET_PART_NOT_FROM_SEARCH",
                )
            try:
                quantity = int(raw_part.get("quantity") or 0)
            except (TypeError, ValueError) as exc:
                raise APIError(502, "AI custom set quantity is invalid", "AI_CUSTOM_SET_QUANTITY_INVALID") from exc
            if quantity <= 0:
                raise APIError(502, "AI custom set quantity must be positive", "AI_CUSTOM_SET_QUANTITY_INVALID")

            raw_color_id = raw_part.get("color_id", -1)
            if raw_color_id in (None, "", "any", "any_color"):
                color_id = -1
            else:
                try:
                    color_id = int(raw_color_id)
                except (TypeError, ValueError) as exc:
                    raise APIError(502, "AI custom set color_id is invalid", "AI_CUSTOM_SET_COLOR_INVALID") from exc

            color_name = raw_part.get("color_name") or ("Any color" if color_id == -1 else None)
            normalized_parts.append(
                {
                    "part_num": part_num,
                    "part_name": matched_part.get("name") or raw_part.get("part_name") or part_num,
                    "img_url": matched_part.get("img_url") or raw_part.get("img_url"),
                    "color_id": color_id,
                    "color_name": color_name,
                    "quantity": quantity,
                }
            )
            total_quantity += quantity

        item["custom_parts"] = normalized_parts
        item["name"] = item.get("name") or "Custom Set"
        item["set_meta"] = {
            "name": item["name"],
            "year": None,
            "num_parts": total_quantity,
            "img_url": None,
        }


def _lookup_exact_catalog_part(catalog: ProfileCatalogService, part_num: str) -> dict[str, Any] | None:
    normalized = str(part_num or "").strip()
    if not normalized:
        return None

    parts_data = getattr(catalog, "parts_data", None)
    parts = getattr(parts_data, "parts", {}) if parts_data is not None else {}
    if not isinstance(parts, dict):
        return None

    exact = parts.get(normalized)
    if isinstance(exact, dict):
        return {
            "part_num": normalized,
            "name": exact.get("name") or normalized,
            "img_url": exact.get("part_img_url"),
        }

    for rb_part_num, part in parts.items():
        if not isinstance(part, dict):
            continue
        external_ids = part.get("external_ids", {})
        bricklink_ids = external_ids.get("BrickLink", [])
        if isinstance(bricklink_ids, dict):
            bricklink_ids = bricklink_ids.get("ext_ids", [])
        if not isinstance(bricklink_ids, list):
            continue
        normalized_ids = {str(bricklink_id or "").strip() for bricklink_id in bricklink_ids}
        if normalized in normalized_ids:
            return {
                "part_num": str(rb_part_num),
                "name": part.get("name") or str(rb_part_num),
                "img_url": part.get("part_img_url"),
            }

    return None


def _ground_set_search_summary(
    summary: str,
    proposal: dict[str, Any] | None,
    set_search_observations: list[dict[str, Any]],
) -> str:
    if proposal is not None:
        return summary
    if not set_search_observations:
        return summary
    if any(observation.get("sets") for observation in set_search_observations):
        return summary

    attempts: list[str] = []
    seen_attempts: set[str] = set()
    for observation in set_search_observations:
        attempt = _format_search_sets_attempt(observation.get("input", {}))
        if attempt in seen_attempts:
            continue
        seen_attempts.add(attempt)
        attempts.append(attempt)

    if not attempts:
        return summary

    lines = ["I couldn't find matching LEGO sets in the catalog for:", ""]
    lines.extend(f"- {attempt}" for attempt in attempts)
    lines.extend([
        "",
        "Please try a different theme name, a specific set number, or a simpler query.",
    ])
    return "\n".join(lines)


def _finalize_ai_response(
    *,
    response: OpenRouterResponse,
    set_search_observations: list[dict[str, Any]],
    part_search_observations: list[dict[str, Any]],
    catalog: ProfileCatalogService | None = None,
) -> tuple[str, dict[str, Any] | None]:
    parsed_payload = _parse_proposal_payload(response)
    summary = (
        parsed_payload.get("summary")
        if isinstance(parsed_payload, dict) and isinstance(parsed_payload.get("summary"), str)
        else response.content
    )

    proposal = parsed_payload
    if proposal is not None:
        _validate_proposal(proposal)
        _ground_create_set_proposals(proposal, set_search_observations)
        _ground_custom_set_proposals(proposal, part_search_observations, catalog)
        if not proposal.get("proposals"):
            proposal = None

    summary = _ground_set_search_summary(summary, proposal, set_search_observations)
    return summary, proposal


def _execute_tool(catalog: ProfileCatalogService, name: str, arguments: dict[str, Any]) -> AiToolExecutionResult:
    if name == "search_parts":
        return _tool_search_parts(catalog, arguments)
    if name == "search_sets":
        return _tool_search_sets(catalog, arguments)
    if name == "get_set_inventory":
        return _tool_get_set_inventory(catalog, arguments)
    payload = {"error": f"Unknown tool '{name}'"}
    return AiToolExecutionResult(content=json.dumps(payload), trace_output=payload)


def _tool_search_parts(catalog: ProfileCatalogService, args: dict[str, Any]) -> AiToolExecutionResult:
    query = str(args.get("query") or "")
    cat_id = args.get("category_id")
    limit = min(int(args.get("limit") or 20), 50)

    result = catalog.search_parts(query=query, cat_id=cat_id, limit=limit, offset=0)
    parts = result.get("results", [])
    total = result.get("total", 0)

    compact: list[dict[str, Any]] = []
    for p in parts:
        entry: dict[str, Any] = {
            "part_num": p["part_num"],
            "name": p["name"],
            "category": p.get("_category_name", ""),
            "category_id": p.get("part_cat_id"),
            "years": f"{p.get('year_from', '?')}-{p.get('year_to', '?')}",
            "img_url": p.get("part_img_url"),
        }
        if p.get("_bl_name"):
            entry["bl_name"] = p["_bl_name"]
        if p.get("_bl_category_name"):
            entry["bl_category"] = p["_bl_category_name"]
        compact.append(entry)

    payload = {"total": total, "showing": len(compact), "parts": compact}
    return AiToolExecutionResult(content=json.dumps(payload), trace_output=payload)


def _tool_search_sets(catalog: ProfileCatalogService, args: dict[str, Any]) -> AiToolExecutionResult:
    query = str(args.get("query") or "")
    if not query:
        payload = {"error": "query is required"}
        return AiToolExecutionResult(content=json.dumps(payload), trace_output=payload)
    min_year = args.get("min_year")
    max_year = args.get("max_year")
    results = catalog.search_sets(
        query,
        min_year=int(min_year) if min_year is not None else None,
        max_year=int(max_year) if max_year is not None else None,
    )
    payload = {"total": len(results), "sets": results}
    return AiToolExecutionResult(content=json.dumps(payload), trace_output=payload)


def _tool_get_set_inventory(catalog: ProfileCatalogService, args: dict[str, Any]) -> AiToolExecutionResult:
    set_num = str(args.get("set_num") or "").strip()
    if not set_num:
        payload = {"error": "set_num is required"}
        return AiToolExecutionResult(content=json.dumps(payload), trace_output=payload)

    include_spares = bool(args.get("include_spares", False))
    try:
        limit = min(max(int(args.get("limit") or 200), 1), 500)
    except (TypeError, ValueError):
        limit = 200
    try:
        offset = max(int(args.get("offset") or 0), 0)
    except (TypeError, ValueError):
        offset = 0

    detail = catalog.get_set_inventory(set_num)
    inventory = detail.get("inventory", [])
    if not include_spares:
        inventory = [item for item in inventory if not item.get("is_spare")]

    sliced = inventory[offset : offset + limit]
    compact: list[dict[str, Any]] = []
    for item in sliced:
        compact.append(
            {
                "part_num": item.get("part_num"),
                "part_name": item.get("part_name"),
                "color_id": item.get("color_id"),
                "color_name": item.get("color_name"),
                "quantity": item.get("quantity"),
                "is_spare": bool(item.get("is_spare")),
            }
        )

    trace_payload = {
        "set": detail.get("set"),
        "total": len(inventory),
        "showing": len(compact),
        "offset": offset,
        "include_spares": include_spares,
        "inventory": compact,
    }
    return AiToolExecutionResult(content=json.dumps(trace_payload), trace_output=trace_payload)


def apply_profile_ai_proposal(
    *,
    rules: list[dict[str, Any]],
    selected_rule_id: str | None,
    proposal: dict[str, Any],
) -> list[dict[str, Any]]:
    next_rules = copy.deepcopy(rules)
    builder_sorting_profile._migrateRules(next_rules)
    profile_like = SimpleNamespace(rules=next_rules)

    for item in proposal.get("proposals", []):
        action = item["action"]
        target_rule_id = item.get("target_rule_id") or selected_rule_id
        parent_id = item.get("parent_id")
        position = item.get("position")

        if action == "create":
            conditions = _normalize_conditions(item.get("conditions", []))
            candidate_rule = {
                "name": item.get("name") or "New Rule",
                "match_mode": item.get("match_mode", "all"),
                "conditions": conditions,
            }
            if _has_duplicate_filter_rule(profile_like, candidate_rule, parent_id):
                continue
            created_rule_id = builder_sorting_profile.addRule(
                profile_like,
                candidate_rule["name"],
                conditions,
                match_mode=candidate_rule["match_mode"],
                parent_id=parent_id,
                position=position,
            )
            if created_rule_id is None:
                raise APIError(400, "AI proposal references an unknown parent rule", "AI_INVALID_PARENT")
            continue

        if action == "create_set":
            set_num = item.get("set_num", "")
            if _has_duplicate_set_rule(profile_like, set_num):
                continue
            set_name = item.get("name") or set_num
            include_spares = bool(item.get("include_spares", False))
            set_meta = item.get("set_meta")
            new_rule = {
                "id": str(uuid.uuid4()),
                "rule_type": "set",
                "set_source": "rebrickable",
                "name": set_name,
                "set_num": set_num,
                "include_spares": include_spares,
                "set_meta": set_meta,
                "match_mode": "all",
                "conditions": [],
                "children": [],
                "disabled": False,
            }
            # Set rules must always be top-level (they have no conditions,
            # so nesting them as children would act as always-true subchecks).
            if position is not None and 0 <= position <= len(profile_like.rules):
                profile_like.rules.insert(position, new_rule)
            else:
                profile_like.rules.append(new_rule)
            continue

        if action == "create_custom_set":
            set_name = item.get("name") or "Custom Set"
            set_meta = item.get("set_meta")
            custom_parts = item.get("custom_parts") if isinstance(item.get("custom_parts"), list) else []
            if _has_duplicate_custom_set_rule(profile_like, set_name, custom_parts):
                continue
            new_rule = {
                "id": str(uuid.uuid4()),
                "rule_type": "set",
                "set_source": "custom",
                "name": set_name,
                "set_num": f"custom:{uuid.uuid4()}",
                "include_spares": False,
                "set_meta": set_meta,
                "custom_parts": custom_parts,
                "match_mode": "all",
                "conditions": [],
                "children": [],
                "disabled": False,
            }
            if position is not None and 0 <= position <= len(profile_like.rules):
                profile_like.rules.insert(position, new_rule)
            else:
                profile_like.rules.append(new_rule)
            continue

        if not target_rule_id:
            raise APIError(400, "AI proposal did not specify a target rule", "AI_TARGET_RULE_MISSING")

        target_rule = builder_sorting_profile.getRule(profile_like, target_rule_id)
        if target_rule is None:
            raise APIError(400, "AI proposal references an unknown target rule", "AI_TARGET_RULE_INVALID")

        if action == "delete":
            builder_sorting_profile.removeRule(profile_like, target_rule_id)
            continue

        if action == "move":
            moving_rule = copy.deepcopy(target_rule)
            builder_sorting_profile.removeRule(profile_like, target_rule_id)
            _insert_existing_rule(profile_like, moving_rule, parent_id, position)
            continue

        if action != "edit":
            raise APIError(400, f"Unsupported AI action '{action}'", "AI_ACTION_INVALID")

        target_rule["name"] = item.get("name") or target_rule.get("name") or "Unnamed Rule"
        target_rule["match_mode"] = item.get("match_mode", "all")
        target_rule["conditions"] = _normalize_conditions(item.get("conditions", []))

        if parent_id is not None or position is not None:
            moved_rule = copy.deepcopy(target_rule)
            builder_sorting_profile.removeRule(profile_like, target_rule_id)
            _insert_existing_rule(profile_like, moved_rule, parent_id, position)

    return profile_like.rules


def _iter_rules(rules: list[dict[str, Any]]) -> Generator[dict[str, Any], None, None]:
    for rule in rules:
        yield rule
        children = rule.get("children")
        if isinstance(children, list):
            yield from _iter_rules(children)


def _parent_rule_id(profile_like: SimpleNamespace, target_rule_id: str) -> str | None:
    def walk(rules: list[dict[str, Any]], parent_id: str | None = None) -> str | None:
        for rule in rules:
            if str(rule.get("id")) == target_rule_id:
                return parent_id
            children = rule.get("children")
            if isinstance(children, list):
                found = walk(children, str(rule.get("id")))
                if found is not None or any(str(child.get("id")) == target_rule_id for child in children):
                    return found
        return None

    return walk(profile_like.rules)


def _canonical_condition_key(condition: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(condition.get("field") or ""),
        str(condition.get("op") or ""),
        json.dumps(condition.get("value"), sort_keys=True, default=str),
    )


def _canonical_custom_part_key(part: dict[str, Any]) -> tuple[str, int, int]:
    return (
        str(part.get("part_num") or "").strip(),
        int(part.get("color_id", -1) if part.get("color_id") not in (None, "", "any", "any_color") else -1),
        int(part.get("quantity") or 0),
    )


def _has_duplicate_filter_rule(profile_like: SimpleNamespace, candidate_rule: dict[str, Any], parent_id: str | None) -> bool:
    candidate_name = str(candidate_rule.get("name") or "").strip().lower()
    candidate_mode = str(candidate_rule.get("match_mode") or "all")
    candidate_conditions = sorted(
        _canonical_condition_key(condition)
        for condition in candidate_rule.get("conditions", [])
        if isinstance(condition, dict)
    )

    for existing in _iter_rules(profile_like.rules):
        if existing.get("rule_type") == "set":
            continue
        existing_parent_id = _parent_rule_id(profile_like, str(existing.get("id") or ""))
        if existing_parent_id != parent_id:
            continue
        existing_name = str(existing.get("name") or "").strip().lower()
        existing_mode = str(existing.get("match_mode") or "all")
        existing_conditions = sorted(
            _canonical_condition_key(condition)
            for condition in existing.get("conditions", [])
            if isinstance(condition, dict)
        )
        if existing_name == candidate_name and existing_mode == candidate_mode and existing_conditions == candidate_conditions:
            return True
    return False


def _has_duplicate_set_rule(profile_like: SimpleNamespace, set_num: str) -> bool:
    normalized = str(set_num or "").strip().lower()
    if not normalized:
        return False
    for existing in _iter_rules(profile_like.rules):
        if existing.get("rule_type") != "set":
            continue
        if str(existing.get("set_source") or "rebrickable") == "custom":
            continue
        if str(existing.get("set_num") or "").strip().lower() == normalized:
            return True
    return False


def _has_duplicate_custom_set_rule(profile_like: SimpleNamespace, name: str, custom_parts: list[dict[str, Any]]) -> bool:
    candidate_name = str(name or "").strip().lower()
    candidate_parts = sorted(
        _canonical_custom_part_key(part)
        for part in custom_parts
        if isinstance(part, dict)
    )
    for existing in _iter_rules(profile_like.rules):
        if existing.get("rule_type") != "set":
            continue
        if str(existing.get("set_source") or "") != "custom":
            continue
        existing_name = str(existing.get("name") or "").strip().lower()
        existing_parts = sorted(
            _canonical_custom_part_key(part)
            for part in existing.get("custom_parts", [])
            if isinstance(part, dict)
        )
        if existing_name == candidate_name and existing_parts == candidate_parts:
            return True
    return False


def _normalize_conditions(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for cond in conditions:
        normalized.append(
            {
                "id": str(uuid.uuid4()),
                "field": cond["field"],
                "op": cond["op"],
                "value": cond.get("value"),
            }
        )
    return normalized


def _insert_existing_rule(profile_like: SimpleNamespace, rule: dict[str, Any], parent_id: str | None, position: int | None) -> None:
    if parent_id:
        parent = builder_sorting_profile.getRule(profile_like, parent_id)
        if parent is None:
            raise APIError(400, "AI proposal references an unknown parent rule", "AI_INVALID_PARENT")
        children = parent.setdefault("children", [])
        if position is not None and 0 <= position <= len(children):
            children.insert(position, rule)
        else:
            children.append(rule)
        return

    if position is not None and 0 <= position <= len(profile_like.rules):
        profile_like.rules.insert(position, rule)
    else:
        profile_like.rules.append(rule)


def _parse_proposal_payload(response: OpenRouterResponse) -> dict[str, Any] | None:
    """Parse the AI response as a JSON proposal. Returns None for text-only responses."""
    if response.finish_reason == "length":
        raise APIError(502, "AI response was truncated (too long). Try a simpler request.", "AI_RESPONSE_TRUNCATED")
    content = response.content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", content, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Find the outermost balanced JSON object by tracking brace depth
    start = content.find("{")
    if start == -1:
        # No JSON found — this is a text-only response (e.g. answering a question)
        return None

    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(content)):
        ch = content[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(content[start : i + 1])
                except json.JSONDecodeError as exc:
                    raise APIError(502, f"AI response was not valid JSON: {exc}", "AI_INVALID_JSON") from exc

    raise APIError(502, "AI response contained unterminated JSON", "AI_INVALID_JSON")


def _validate_proposal(proposal: dict[str, Any]) -> None:
    if not isinstance(proposal, dict):
        raise APIError(502, "AI proposal must be a JSON object", "AI_INVALID_JSON")
    proposals = proposal.get("proposals")
    if not isinstance(proposals, list):
        raise APIError(502, "AI proposal did not contain any operations", "AI_NO_PROPOSALS")
    if not proposals:
        # Empty proposals with a summary is a valid conversational response
        # (e.g. the AI asks a clarifying question). Treat as no-op.
        return

    for index, item in enumerate(proposals):
        if not isinstance(item, dict):
            raise APIError(502, f"AI proposal {index + 1} is invalid", "AI_INVALID_JSON")
        action = item.get("action")
        if action not in {"edit", "create", "create_set", "create_custom_set", "move", "delete"}:
            raise APIError(502, f"AI proposal action '{action}' is invalid", "AI_ACTION_INVALID")
        if action in {"edit", "create"}:
            if item.get("match_mode") not in {"all", "any"}:
                raise APIError(502, "AI proposal contained an invalid match_mode", "AI_MATCH_MODE_INVALID")
            conditions = item.get("conditions")
            if not isinstance(conditions, list):
                raise APIError(502, "AI proposal conditions must be a list", "AI_CONDITIONS_INVALID")
            for condition in conditions:
                if not isinstance(condition, dict):
                    raise APIError(502, "AI proposal condition is invalid", "AI_CONDITIONS_INVALID")
                field = condition.get("field")
                op = condition.get("op")
                if field not in VALID_FIELDS:
                    raise APIError(502, f"AI proposal used unknown field '{field}'", "AI_FIELD_INVALID")
                if op not in VALID_OPS or op not in FIELD_OPS.get(field, VALID_OPS):
                    raise APIError(502, f"AI proposal used invalid operator '{op}' for '{field}'", "AI_OPERATOR_INVALID")
        if action == "create_set":
            if not item.get("set_num"):
                raise APIError(502, "AI create_set proposal missing set_num", "AI_SET_NUM_MISSING")
        if action == "create_custom_set":
            custom_parts = item.get("custom_parts")
            if not isinstance(custom_parts, list) or not custom_parts:
                raise APIError(502, "AI create_custom_set proposal missing custom_parts", "AI_CUSTOM_SET_PARTS_MISSING")


def _build_system_prompt(catalog: ProfileCatalogService, document: dict[str, Any], selected_rule_id: str | None) -> str:
    payload_rules = copy.deepcopy(document.get("rules") or [])
    builder_sorting_profile._migrateRules(payload_rules)
    selected_rule = _find_rule(payload_rules, selected_rule_id) if selected_rule_id else None
    prompt_rules = [_prompt_rule_snapshot(rule) for rule in payload_rules]
    prompt_selected_rule = _prompt_rule_snapshot(selected_rule, expand_custom_parts=True) if selected_rule else None

    field_ops_json = json.dumps(
        {key: sorted(value) for key, value in FIELD_OPS.items()}, indent=2
    )

    # Embed lightweight catalog data directly so the AI doesn't need tool calls for basic lookups
    categories = catalog.parts_data.categories
    colors = catalog.parts_data.colors
    bricklink_categories = catalog.parts_data.bricklink_categories

    catalog_section = ""
    if categories:
        rb_cats = ", ".join(f"{cid}: {c['name']}" for cid, c in sorted(categories.items()))
        catalog_section += f"\nRebrickable categories:\n{rb_cats}\n"
    if bricklink_categories:
        bl_cats = ", ".join(
            f"{cid}: {c.get('category_name', '')}"
            for cid, c in sorted(bricklink_categories.items())
        )
        catalog_section += f"\nBrickLink categories:\n{bl_cats}\n"
    if colors:
        color_list = ", ".join(f"{cid}: {c['name']}" for cid, c in sorted(colors.items()))
        catalog_section += f"\nColors:\n{color_list}\n"

    has_parts = bool(catalog.parts_data.parts)

    if has_parts:
        tool_section = """
You have tools to search the LEGO parts catalog and LEGO sets:
- **search_parts**: Search parts by name, number, or keyword. Returns matching parts with category, year range, and BrickLink info.
- **search_sets**: Search for LEGO sets by name, theme, or number. Returns set name, number, year, part count, and image.
- **get_set_inventory**: Get the parts inventory for a specific set number, including quantities and colors.

Only use search_parts when you need to look up specific parts or verify part numbers. For most requests, the category and color lists above are sufficient.
Use search_sets when the user wants to sort parts from specific official LEGO sets.
Use get_set_inventory after search_sets when the user asks what parts are inside a specific set.
Use search_parts when the user wants a custom kit, bundle, customer order, or any non-official set made from individual parts."""
    else:
        tool_section = """
Note: The parts catalog has not been synced yet, so no parts data is available for search. Use your built-in knowledge of LEGO categories, part types, and naming conventions to create rules. Do NOT use the search_parts tool — it will return no results.
You can still use search_sets to look up official LEGO sets by name, theme, or number, and get_set_inventory to inspect a specific set's part list.
Do NOT try to create precise custom kits from chat without a synced parts catalog. Instead, explain that the parts catalog must be synced first or that the user can add a Custom Set manually in the editor."""

    return f"""You help users create LEGO sorting profiles.

Profiles contain top-level categories and nested child rules. Child rules refine matching, but final parts still map to their top-level parent category.
{tool_section}

You MUST always respond with JSON matching this schema:
{{
  "summary": "human-readable message to the user",
  "proposals": [
    {{
      "action": "edit" | "create" | "create_set" | "create_custom_set" | "move" | "delete",
      "target_rule_id": "existing-rule-id-or-null",
      "parent_id": "parent-rule-id-or-null",
      "position": 0,
      "name": "Rule name",
      "match_mode": "all" | "any",
      "conditions": [{{"field": "name", "op": "contains", "value": "brick"}}],
      "set_num": "10283-1",
      "set_meta": {{"name": "Set Name", "year": 2021, "num_parts": 2354, "img_url": "https://..."}},
      "custom_parts": [{{"part_num": "2780", "color_id": -1, "color_name": "Any color", "quantity": 20}}]
    }}
  ]
}}

- If no rule changes are needed (e.g. the user asks a question), set proposals to an empty array [] and put your answer in summary.
- For delete actions, only target_rule_id is required (no name, conditions, or match_mode needed).
- For "create_set" action: you MUST first call search_sets to find the set, then provide set_num (Rebrickable set number like "10283-1"), name, and set_meta with {{name, year, num_parts, img_url}} from the search_sets results. Do NOT include conditions or match_mode for set rules. Set rules are always top-level — do not nest them as children.
- For "create_custom_set" action: you MUST first call search_parts to verify each distinct part you want to include, then provide name and custom_parts. Each custom_parts entry must include {{part_num, color_id, quantity}} and may include color_name. Use Rebrickable part numbers from search_parts. If the user did not specify a color, use color_id -1 and color_name "Any color". Do NOT include conditions or match_mode for custom set rules. Custom set rules are always top-level.
- For "create" and "edit" actions: provide name, match_mode, and conditions. Do NOT use create_set fields (set_num, set_meta).

Current rules:
{json.dumps(prompt_rules, indent=2, ensure_ascii=False)}

Selected rule:
{json.dumps(prompt_selected_rule, indent=2, ensure_ascii=False) if prompt_selected_rule else "null"}

Allowed fields: {sorted(VALID_FIELDS)}
Allowed operators by field:
{field_ops_json}
{catalog_section}
Guidelines:
- Distinguish carefully between official LEGO sets and custom sets. "Custom set", "custom kit", "bundle", "customer order", or "not a real set" means create_custom_set, not create_set.
- For edits and creates, always return COMPLETE conditions, not partial diffs.
- Before any create action, inspect Current rules carefully. If an equivalent rule, set, or custom set already exists, do NOT create a duplicate. Prefer edit when changing an existing rule, or return no proposal when nothing new is needed.
- Use category_name or name matching if you are unsure about numeric IDs.
- Keep proposals small and actionable.
- If the user asks to split a category into multiple child rules, return multiple proposals.
- Prefer 'contains' over complex regex unless the user explicitly asks for regex.
- Do NOT include emojis or special characters in rule names. Use plain text only (e.g. "Bricks" not "🧱 Bricks").
- When the user wants to add a LEGO set, use search_sets to find the correct set_num, then use action "create_set" with set_num and set_meta from the search results. Never use action "create" for sets.
- When the user asks which parts are inside an official LEGO set, first use search_sets to identify the exact set_num, then use get_set_inventory with that set_num.
- When the user wants a custom bundle, customer order, kit, or non-official set made from specific parts and quantities, use action "create_custom_set". Search the parts first, then build one custom_parts entry per requested part.
- Treat search_sets results as the source of truth for set existence and metadata. Never list, recommend, compare, or create specific LEGO sets unless they appeared in search_sets output.
- Treat search_parts results as the source of truth for custom set part numbers. Never invent specific part numbers that were not returned by search_parts in this turn.
- If search_sets returns no results, say that clearly and do not fall back to your built-in knowledge for specific set names.
- Put release years into min_year and max_year instead of embedding them in the query text. For example, for "Creator sets from 2024", use query "Creator" with min_year 2024 and max_year 2024.
- IMPORTANT: A single search_sets call returns ALL information needed to create set rules (set_num, name, year, num_parts, img_url). Do NOT search for individual set numbers after getting initial results — that is wasteful and slow. Create multiple create_set proposals directly from the search results.
- If the user wants multiple sets (e.g. "add all Minecraft sets"), call search_sets ONCE with the theme name, then create one create_set proposal per result. Never iterate through set numbers one by one."""


def generate_change_note(
    *,
    api_key: str,
    user_message: str,
    proposal: dict[str, Any],
) -> str:
    """Use Haiku to generate a concise change note from the user request and AI proposal."""
    summary = proposal.get("summary", "")

    # Build a detailed description of what changed
    change_details: list[str] = []
    for p in proposal.get("proposals", []):
        action = p.get("action", "?")
        name = p.get("name", "rule")
        conditions = p.get("conditions") or []
        cond_strs = [f"{c.get('field')} {c.get('op')} {c.get('value')}" for c in conditions]
        detail = f"{action} \"{name}\""
        if cond_strs:
            detail += f" ({', '.join(cond_strs[:3])})"
        change_details.append(detail)
    changes_str = "\n".join(f"- {d}" for d in change_details) if change_details else "no changes"

    resp = run_openrouter_chat(
        api_key=api_key,
        model="anthropic/claude-haiku-4-5",
        messages=[
            {
                "role": "system",
                "content": (
                    "Generate a short change note (1 sentence, max 100 chars) for a LEGO sorting profile version. "
                    "Describe WHAT changed, not who requested it. "
                    "Examples: 'Add Technic sub-categories for gears, beams and axles', "
                    "'Remove duplicate plate rules', 'Split Bricks into basic and decorative'. "
                    "Return ONLY the change note, no quotes, no prefix. "
                    "Write in the same language as the user message."
                ),
            },
            {
                "role": "user",
                "content": f"User request: {user_message}\nAI summary: {summary}\nChanges:\n{changes_str}",
            },
        ],
        temperature=0.0,
        max_tokens=120,
    )
    return resp.content.strip().strip('"')


def generate_change_note_from_diff(
    *,
    api_key: str,
    old_rules: list[dict[str, Any]],
    new_rules: list[dict[str, Any]],
) -> str:
    """Use Haiku to generate a concise change note by comparing old and new rule trees."""

    def _rule_names(rules: list[dict[str, Any]]) -> set[str]:
        names: set[str] = set()
        for r in rules:
            names.add(r.get("name", "?"))
            names |= _rule_names(r.get("children", []))
        return names

    def _rule_summary(rules: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        for r in rules:
            rt = r.get("rule_type", "category")
            name = r.get("name", "?")
            disabled = r.get("disabled", False)
            children = r.get("children", [])
            conditions = r.get("conditions", [])
            parts = f", {len(conditions)} conditions" if conditions else ""
            kids = f", {len(children)} children" if children else ""
            state = " [disabled]" if disabled else ""
            out.append(f"{rt}: \"{name}\"{parts}{kids}{state}")
            out.extend(f"  > {s}" for s in _rule_summary(children))
        return out

    old_summary = "\n".join(_rule_summary(old_rules)) or "(empty)"
    new_summary = "\n".join(_rule_summary(new_rules)) or "(empty)"

    old_names = _rule_names(old_rules)
    new_names = _rule_names(new_rules)
    added = new_names - old_names
    removed = old_names - new_names

    diff_hints: list[str] = []
    if added:
        diff_hints.append(f"Added: {', '.join(sorted(added))}")
    if removed:
        diff_hints.append(f"Removed: {', '.join(sorted(removed))}")
    if not added and not removed:
        diff_hints.append("Rules were modified (renamed, reordered, or conditions changed)")
    diff_str = "\n".join(diff_hints)

    resp = run_openrouter_chat(
        api_key=api_key,
        model="anthropic/claude-haiku-4-5",
        messages=[
            {
                "role": "system",
                "content": (
                    "Generate a short change note (1 sentence, max 100 chars) for a LEGO sorting profile version. "
                    "Describe WHAT changed, not who did it. "
                    "Examples: 'Add Technic sub-categories for gears, beams and axles', "
                    "'Remove duplicate plate rules', 'Split Bricks into basic and decorative'. "
                    "Return ONLY the change note, no quotes, no prefix."
                ),
            },
            {
                "role": "user",
                "content": f"BEFORE:\n{old_summary}\n\nAFTER:\n{new_summary}\n\nDIFF:\n{diff_str}",
            },
        ],
        temperature=0.0,
        max_tokens=120,
    )
    return resp.content.strip().strip('"')


def _prompt_rule_snapshot(rule: dict[str, Any] | None, *, expand_custom_parts: bool = False) -> dict[str, Any] | None:
    if not isinstance(rule, dict):
        return None

    snapshot: dict[str, Any] = {
        "id": str(rule.get("id") or ""),
        "name": str(rule.get("name") or "Unnamed Rule"),
    }
    if rule.get("disabled"):
        snapshot["disabled"] = True

    rule_type = str(rule.get("rule_type") or "filter")
    if rule_type == "set":
        set_source = str(rule.get("set_source") or ("custom" if rule.get("custom_parts") else "rebrickable"))
        snapshot["rule_type"] = "set"
        snapshot["set_source"] = set_source
        snapshot["set_num"] = str(rule.get("set_num") or "")
        if rule.get("include_spares"):
            snapshot["include_spares"] = True
        set_meta = rule.get("set_meta")
        if isinstance(set_meta, dict):
            meta_snapshot = {
                key: set_meta.get(key)
                for key in ("name", "year", "num_parts")
                if set_meta.get(key) not in (None, "", [])
            }
            if meta_snapshot:
                snapshot["set_meta"] = meta_snapshot
        custom_parts = rule.get("custom_parts")
        if set_source == "custom" and isinstance(custom_parts, list):
            if expand_custom_parts:
                snapshot["custom_parts"] = [
                    _prompt_custom_part_snapshot(part)
                    for part in custom_parts
                    if isinstance(part, dict)
                ]
            else:
                snapshot["custom_parts_summary"] = _prompt_custom_parts_summary(custom_parts)
    else:
        snapshot["rule_type"] = "filter"
        snapshot["match_mode"] = str(rule.get("match_mode") or "all")
        snapshot["conditions"] = [
            {
                "field": condition.get("field"),
                "op": condition.get("op"),
                "value": condition.get("value"),
            }
            for condition in rule.get("conditions", [])
            if isinstance(condition, dict)
        ]

    children = rule.get("children")
    if isinstance(children, list) and children:
        snapshot["children"] = [
            child_snapshot
            for child_snapshot in (_prompt_rule_snapshot(child) for child in children)
            if child_snapshot is not None
        ]

    return snapshot


def _prompt_custom_part_snapshot(part: dict[str, Any]) -> dict[str, Any]:
    raw_color_id = part.get("color_id")
    if raw_color_id in (None, "", "any", "any_color"):
        color_id = -1
    else:
        try:
            color_id = int(raw_color_id)
        except (TypeError, ValueError):
            color_id = -1

    raw_quantity = part.get("quantity")
    try:
        quantity = int(raw_quantity or 0)
    except (TypeError, ValueError):
        quantity = 0

    snapshot = {
        "part_num": str(part.get("part_num") or ""),
        "quantity": quantity,
        "color_id": color_id,
    }
    color_name = part.get("color_name")
    if color_name not in (None, ""):
        snapshot["color_name"] = color_name
    part_name = part.get("part_name")
    if part_name not in (None, ""):
        snapshot["part_name"] = part_name
    return snapshot


def _prompt_custom_parts_summary(custom_parts: list[dict[str, Any]]) -> dict[str, Any]:
    total_quantity = 0
    sample_parts: list[dict[str, Any]] = []
    for index, part in enumerate(custom_parts):
        if not isinstance(part, dict):
            continue
        try:
            quantity = int(part.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0
        total_quantity += max(quantity, 0)
        if len(sample_parts) < 5:
            sample_parts.append(_prompt_custom_part_snapshot(part))
    summary: dict[str, Any] = {
        "line_items": len([part for part in custom_parts if isinstance(part, dict)]),
        "total_quantity": total_quantity,
    }
    if sample_parts:
        summary["sample_parts"] = sample_parts
    remaining = max(len([part for part in custom_parts if isinstance(part, dict)]) - len(sample_parts), 0)
    if remaining:
        summary["remaining_line_items"] = remaining
    return summary


def _find_rule(rules: list[dict[str, Any]], rule_id: str | None) -> dict[str, Any] | None:
    if not rule_id:
        return None
    for rule in rules:
        if rule.get("id") == rule_id:
            return rule
        found = _find_rule(rule.get("children", []), rule_id)
        if found:
            return found
    return None
