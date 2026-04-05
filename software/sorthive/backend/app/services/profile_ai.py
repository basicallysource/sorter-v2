from __future__ import annotations

import copy
import json
import re
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

# search_sets is always available (only needs Rebrickable API key);
# search_parts requires synced parts data
CATALOG_TOOLS = [_SEARCH_PARTS_TOOL, _SEARCH_SETS_TOOL]
SET_ONLY_TOOLS = [_SEARCH_SETS_TOOL]

PROPOSAL_RESPONSE_FORMAT = {"type": "json_object"}


@dataclass
class AiToolTraceEntry:
    tool: str
    input: dict[str, Any]
    output_summary: str
    output: dict[str, Any] | None = None


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
    )


def generate_profile_ai_proposal(
    *,
    user: User,
    catalog: ProfileCatalogService,
    document: dict[str, Any],
    message: str,
    conversation_history: list[dict[str, str]] | None = None,
    selected_rule_id: str | None = None,
) -> AiProposalResult:
    model = user.preferred_ai_model or settings.DEFAULT_AI_MODEL
    has_parts = bool(catalog.parts_data.parts)
    custom_set_request = _looks_like_custom_set_request(message)
    if custom_set_request and not has_parts:
        return _custom_set_catalog_unavailable_result(model)

    api_key = get_user_openrouter_key(user)
    tools = CATALOG_TOOLS if has_parts else SET_ONLY_TOOLS

    system_prompt = _build_system_prompt(catalog, document, selected_rule_id)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if custom_set_request:
        messages.append({"role": "system", "content": _custom_set_intent_note()})
    messages.extend(_normalize_conversation_history(conversation_history))
    messages.append({"role": "user", "content": message})

    total_usage: dict[str, int] = {}
    final_model = model
    tool_trace: list[AiToolTraceEntry] = []
    set_search_observations: list[dict[str, Any]] = []
    part_search_observations: list[dict[str, Any]] = []

    for _round in range(MAX_TOOL_ROUNDS + 1):
        response = run_openrouter_chat(
            api_key=api_key,
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=8192,
            tools=tools,
        )
        final_model = response.model
        _accumulate_usage(total_usage, response.usage)

        if not response.tool_calls:
            break

        # Append assistant message with tool calls
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

        # Execute each tool call, build trace, and append results
        for tc in response.tool_calls:
            result = _execute_tool(catalog, tc.name, tc.arguments)
            summary = _summarize_tool_result(tc.name, tc.arguments, result)
            output = _parse_tool_output(result)
            tool_trace.append(
                AiToolTraceEntry(
                    tool=tc.name,
                    input=tc.arguments,
                    output_summary=summary,
                    output=output,
                )
            )
            if tc.name == "search_sets":
                set_search_observations.append({
                    "input": tc.arguments,
                    "sets": _extract_search_sets_results(result),
                })
            if tc.name == "search_parts":
                part_search_observations.append({
                    "input": tc.arguments,
                    "parts": _extract_search_parts_results(result),
                })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
    else:
        raise APIError(502, "AI used too many tool calls without producing a result", "AI_TOO_MANY_ROUNDS")

    assistant_content, proposal = _finalize_ai_response(
        response=response,
        set_search_observations=set_search_observations,
        part_search_observations=part_search_observations,
    )
    return AiProposalResult(
        content=assistant_content,
        proposal=proposal,
        model=final_model,
        usage=total_usage or None,
        tool_trace=tool_trace,
    )


def generate_profile_ai_proposal_streaming(
    *,
    user: User,
    catalog: ProfileCatalogService,
    document: dict[str, Any],
    message: str,
    conversation_history: list[dict[str, str]] | None = None,
    selected_rule_id: str | None = None,
) -> Generator[AiProgressEvent | AiProposalResult, None, None]:
    """Like generate_profile_ai_proposal but yields progress events during tool use."""
    model = user.preferred_ai_model or settings.DEFAULT_AI_MODEL
    has_parts = bool(catalog.parts_data.parts)
    custom_set_request = _looks_like_custom_set_request(message)
    if custom_set_request and not has_parts:
        yield _custom_set_catalog_unavailable_result(model)
        return

    api_key = get_user_openrouter_key(user)
    tools = CATALOG_TOOLS if has_parts else SET_ONLY_TOOLS

    system_prompt = _build_system_prompt(catalog, document, selected_rule_id)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if custom_set_request:
        messages.append({"role": "system", "content": _custom_set_intent_note()})
    messages.extend(_normalize_conversation_history(conversation_history))
    messages.append({"role": "user", "content": message})

    total_usage: dict[str, int] = {}
    final_model = model
    tool_trace: list[AiToolTraceEntry] = []
    set_search_observations: list[dict[str, Any]] = []
    part_search_observations: list[dict[str, Any]] = []

    for _round in range(MAX_TOOL_ROUNDS + 1):
        yield AiProgressEvent(type="thinking", data={"round": _round + 1})

        response = run_openrouter_chat(
            api_key=api_key,
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=8192,
            tools=tools,
        )
        final_model = response.model
        _accumulate_usage(total_usage, response.usage)

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

            result = _execute_tool(catalog, tc.name, tc.arguments)
            summary = _summarize_tool_result(tc.name, tc.arguments, result)
            output = _parse_tool_output(result)
            trace_entry = AiToolTraceEntry(
                tool=tc.name,
                input=tc.arguments,
                output_summary=summary,
                output=output,
            )
            tool_trace.append(trace_entry)
            if tc.name == "search_sets":
                set_search_observations.append({
                    "input": tc.arguments,
                    "sets": _extract_search_sets_results(result),
                })
            if tc.name == "search_parts":
                part_search_observations.append({
                    "input": tc.arguments,
                    "parts": _extract_search_parts_results(result),
                })

            yield AiProgressEvent(type="tool_result", data={
                "tool": tc.name,
                "input": tc.arguments,
                "output_summary": summary,
                "output": output,
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
    else:
        raise APIError(502, "AI used too many tool calls without producing a result", "AI_TOO_MANY_ROUNDS")

    yield AiProgressEvent(type="generating", data={})

    assistant_content, proposal = _finalize_ai_response(
        response=response,
        set_search_observations=set_search_observations,
        part_search_observations=part_search_observations,
    )
    yield AiProposalResult(
        content=assistant_content,
        proposal=proposal,
        model=final_model,
        usage=total_usage or None,
        tool_trace=tool_trace,
    )


def _accumulate_usage(total: dict[str, int], usage: dict[str, Any] | None) -> None:
    if not usage:
        return
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in usage:
            total[key] = total.get(key, 0) + int(usage[key])


def _summarize_tool_result(tool_name: str, args: dict[str, Any], raw_result: str) -> str:
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

    return raw_result[:200]


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


def _parse_tool_output(raw_result: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw_result)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _extract_search_sets_results(raw_result: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw_result)
    except json.JSONDecodeError:
        return []

    sets = data.get("sets")
    if not isinstance(sets, list):
        return []
    return [lego_set for lego_set in sets if isinstance(lego_set, dict)]


def _extract_search_parts_results(raw_result: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw_result)
    except json.JSONDecodeError:
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
        _ground_custom_set_proposals(proposal, part_search_observations)
        if not proposal.get("proposals"):
            proposal = None

    summary = _ground_set_search_summary(summary, proposal, set_search_observations)
    return summary, proposal


def _execute_tool(catalog: ProfileCatalogService, name: str, arguments: dict[str, Any]) -> str:
    if name == "search_parts":
        return _tool_search_parts(catalog, arguments)
    if name == "search_sets":
        return _tool_search_sets(catalog, arguments)
    return json.dumps({"error": f"Unknown tool '{name}'"})


def _tool_search_parts(catalog: ProfileCatalogService, args: dict[str, Any]) -> str:
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

    return json.dumps({"total": total, "showing": len(compact), "parts": compact})


def _tool_search_sets(catalog: ProfileCatalogService, args: dict[str, Any]) -> str:
    query = str(args.get("query") or "")
    if not query:
        return json.dumps({"error": "query is required"})
    min_year = args.get("min_year")
    max_year = args.get("max_year")
    results = catalog.search_sets(
        query,
        min_year=int(min_year) if min_year is not None else None,
        max_year=int(max_year) if max_year is not None else None,
    )
    return json.dumps({"total": len(results), "sets": results})


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
            created_rule_id = builder_sorting_profile.addRule(
                profile_like,
                item.get("name") or "New Rule",
                conditions,
                match_mode=item.get("match_mode", "all"),
                parent_id=parent_id,
                position=position,
            )
            if created_rule_id is None:
                raise APIError(400, "AI proposal references an unknown parent rule", "AI_INVALID_PARENT")
            continue

        if action == "create_set":
            set_num = item.get("set_num", "")
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

Only use search_parts when you need to look up specific parts or verify part numbers. For most requests, the category and color lists above are sufficient.
Use search_sets when the user wants to sort parts from specific official LEGO sets.
Use search_parts when the user wants a custom kit, bundle, customer order, or any non-official set made from individual parts."""
    else:
        tool_section = """
Note: The parts catalog has not been synced yet, so no parts data is available for search. Use your built-in knowledge of LEGO categories, part types, and naming conventions to create rules. Do NOT use the search_parts tool — it will return no results.
You can still use search_sets to look up official LEGO sets by name, theme, or number.
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
{json.dumps(payload_rules, indent=2)}

Selected rule:
{json.dumps(selected_rule, indent=2) if selected_rule else "null"}

Allowed fields: {sorted(VALID_FIELDS)}
Allowed operators by field:
{field_ops_json}
{catalog_section}
Guidelines:
- Distinguish carefully between official LEGO sets and custom sets. "Custom set", "custom kit", "bundle", "customer order", or "not a real set" means create_custom_set, not create_set.
- For edits and creates, always return COMPLETE conditions, not partial diffs.
- Use category_name or name matching if you are unsure about numeric IDs.
- Keep proposals small and actionable.
- If the user asks to split a category into multiple child rules, return multiple proposals.
- Prefer 'contains' over complex regex unless the user explicitly asks for regex.
- Do NOT include emojis or special characters in rule names. Use plain text only (e.g. "Bricks" not "🧱 Bricks").
- When the user wants to add a LEGO set, use search_sets to find the correct set_num, then use action "create_set" with set_num and set_meta from the search results. Never use action "create" for sets.
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
