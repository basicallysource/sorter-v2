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


# --- Tool definitions for the LLM ---

CATALOG_TOOLS = [
    {
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
    },
]


@dataclass
class AiToolTraceEntry:
    tool: str
    input: dict[str, Any]
    output_summary: str


@dataclass
class AiProgressEvent:
    """Yielded during streaming to inform the frontend of progress."""
    type: str  # "tool_call", "tool_result", "generating"
    data: dict[str, Any]


@dataclass
class AiProposalResult:
    content: str
    proposal: dict[str, Any]
    model: str
    usage: dict[str, Any] | None
    tool_trace: list[AiToolTraceEntry]


def get_user_openrouter_key(user: User) -> str:
    api_key = decrypt_secret(user.openrouter_api_key_encrypted)
    if api_key:
        return api_key
    raise APIError(400, "No OpenRouter key configured for this account", "OPENROUTER_KEY_MISSING")


def generate_profile_ai_proposal(
    *,
    user: User,
    catalog: ProfileCatalogService,
    document: dict[str, Any],
    message: str,
    selected_rule_id: str | None = None,
) -> AiProposalResult:
    api_key = get_user_openrouter_key(user)
    model = user.preferred_ai_model or settings.DEFAULT_AI_MODEL

    system_prompt = _build_system_prompt(catalog, document, selected_rule_id)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]

    total_usage: dict[str, int] = {}
    final_model = model
    tool_trace: list[AiToolTraceEntry] = []

    for _round in range(MAX_TOOL_ROUNDS + 1):
        response = run_openrouter_chat(
            api_key=api_key,
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=8192,
            tools=CATALOG_TOOLS,
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
            tool_trace.append(AiToolTraceEntry(tool=tc.name, input=tc.arguments, output_summary=summary))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
    else:
        raise APIError(502, "AI used too many tool calls without producing a result", "AI_TOO_MANY_ROUNDS")

    proposal = _parse_proposal_payload(response)
    _validate_proposal(proposal)
    assistant_content = proposal.get("summary") if isinstance(proposal.get("summary"), str) else response.content
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
    selected_rule_id: str | None = None,
) -> Generator[AiProgressEvent | AiProposalResult, None, None]:
    """Like generate_profile_ai_proposal but yields progress events during tool use."""
    api_key = get_user_openrouter_key(user)
    model = user.preferred_ai_model or settings.DEFAULT_AI_MODEL

    system_prompt = _build_system_prompt(catalog, document, selected_rule_id)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]

    total_usage: dict[str, int] = {}
    final_model = model
    tool_trace: list[AiToolTraceEntry] = []

    for _round in range(MAX_TOOL_ROUNDS + 1):
        yield AiProgressEvent(type="thinking", data={"round": _round + 1})

        response = run_openrouter_chat(
            api_key=api_key,
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=8192,
            tools=CATALOG_TOOLS,
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
            trace_entry = AiToolTraceEntry(tool=tc.name, input=tc.arguments, output_summary=summary)
            tool_trace.append(trace_entry)

            yield AiProgressEvent(type="tool_result", data={
                "tool": tc.name,
                "input": tc.arguments,
                "output_summary": summary,
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
    else:
        raise APIError(502, "AI used too many tool calls without producing a result", "AI_TOO_MANY_ROUNDS")

    yield AiProgressEvent(type="generating", data={})

    proposal = _parse_proposal_payload(response)
    _validate_proposal(proposal)
    assistant_content = proposal.get("summary") if isinstance(proposal.get("summary"), str) else response.content
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
        showing = data.get("showing", 0)
        parts = data.get("parts", [])
        if total == 0:
            return f'No parts found for "{query}"'
        names = [p.get("name", p.get("part_num", "?")) for p in parts[:5]]
        sample = ", ".join(names)
        if total > showing:
            return f'Found {total} parts for "{query}" (showing {showing}): {sample}, ...'
        return f'Found {total} parts for "{query}": {sample}'

    return raw_result[:200]


def _execute_tool(catalog: ProfileCatalogService, name: str, arguments: dict[str, Any]) -> str:
    if name == "search_parts":
        return _tool_search_parts(catalog, arguments)
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
        }
        if p.get("_bl_name"):
            entry["bl_name"] = p["_bl_name"]
        if p.get("_bl_category_name"):
            entry["bl_category"] = p["_bl_category_name"]
        compact.append(entry)

    return json.dumps({"total": total, "showing": len(compact), "parts": compact})



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


def _parse_proposal_payload(response: OpenRouterResponse) -> dict[str, Any]:
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
        raise APIError(502, "AI response did not contain valid JSON", "AI_INVALID_JSON")

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
    if not isinstance(proposals, list) or not proposals:
        raise APIError(502, "AI proposal did not contain any operations", "AI_NO_PROPOSALS")

    for index, item in enumerate(proposals):
        if not isinstance(item, dict):
            raise APIError(502, f"AI proposal {index + 1} is invalid", "AI_INVALID_JSON")
        action = item.get("action")
        if action not in {"edit", "create", "move", "delete"}:
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

    tool_section = """
You have a tool to search the LEGO parts catalog:
- **search_parts**: Search parts by name, number, or keyword. Returns matching parts with category, year range, and BrickLink info.

Only use this tool when you need to look up specific parts or verify part numbers. For most requests, the category and color lists above are sufficient."""

    return f"""You help users create LEGO sorting profiles.

Profiles contain top-level categories and nested child rules. Child rules refine matching, but final parts still map to their top-level parent category.
{tool_section}

When you are ready, return strict JSON only with this shape:
{{
  "summary": "short human summary of what you changed",
  "proposals": [
    {{
      "action": "edit" | "create" | "move" | "delete",
      "target_rule_id": "existing-rule-id-or-null",
      "parent_id": "parent-rule-id-or-null",
      "position": 0,
      "name": "Rule name",
      "match_mode": "all" | "any",
      "conditions": [{{"field": "name", "op": "contains", "value": "brick"}}]
    }}
  ]
}}

For delete actions, only target_rule_id is required (no name, conditions, or match_mode needed).

Current rules:
{json.dumps(payload_rules, indent=2)}

Selected rule:
{json.dumps(selected_rule, indent=2) if selected_rule else "null"}

Allowed fields: {sorted(VALID_FIELDS)}
Allowed operators by field:
{field_ops_json}
{catalog_section}
Guidelines:
- For edits and creates, always return COMPLETE conditions, not partial diffs.
- Use category_name or name matching if you are unsure about numeric IDs.
- Keep proposals small and actionable.
- If the user asks to split a category into multiple child rules, return multiple proposals.
- Prefer 'contains' over complex regex unless the user explicitly asks for regex.
- Do NOT include emojis or special characters in rule names. Use plain text only (e.g. "Bricks" not "🧱 Bricks").
- Your final message must be ONLY the JSON object. No markdown fences, no extra text."""


def generate_change_note(
    *,
    api_key: str,
    user_message: str,
    proposal: dict[str, Any],
) -> str:
    """Use Haiku to generate a concise change note from the user request and AI proposal."""
    summary = proposal.get("summary", "")
    actions = []
    for p in proposal.get("proposals", []):
        action = p.get("action", "?")
        name = p.get("name", "rule")
        actions.append(f"{action} \"{name}\"")
    actions_str = ", ".join(actions) if actions else "no actions"

    resp = run_openrouter_chat(
        api_key=api_key,
        model="anthropic/claude-haiku-4-5-20251001",
        messages=[
            {
                "role": "system",
                "content": (
                    "Generate a short git-commit-style change note (max 80 chars) for a LEGO sorting profile update. "
                    "Be concise and descriptive. Return ONLY the change note text, nothing else. "
                    "Write in the same language as the user message."
                ),
            },
            {
                "role": "user",
                "content": f"User request: {user_message}\nAI summary: {summary}\nActions: {actions_str}",
            },
        ],
        temperature=0.0,
        max_tokens=100,
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
