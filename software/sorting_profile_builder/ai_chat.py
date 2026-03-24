import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass

log = logging.getLogger("sorting_profile_builder.ai_chat")

from collections.abc import AsyncIterator
from pydantic import BaseModel, field_validator
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.usage import UsageLimits
from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent, ToolReturnPart
from pydantic_core import to_json

from db import PartsData
from rule_engine import previewRule


# --- valid fields and operators for conditions ---

VALID_FIELDS = {
    "name", "part_num", "category_id", "category_name", "color_id",
    "year_from", "year_to", "bricklink_id", "bricklink_item_count",
    "bricklink_primary_item_no",
    "bl_price_min", "bl_price_max", "bl_price_avg", "bl_price_qty_avg",
    "bl_price_lots", "bl_price_qty",
    "bl_catalog_name", "bl_catalog_category_id", "bl_category_id",
    "bl_category_name", "bl_catalog_year_released", "bl_catalog_weight",
    "bl_catalog_dim_x", "bl_catalog_dim_y", "bl_catalog_dim_z",
    "bl_catalog_is_obsolete",
}

VALID_OPS = {"eq", "neq", "in", "contains", "regex", "gte", "lte"}

FIELD_OPS = {
    "name":          {"contains", "regex"},
    "part_num":      {"eq", "neq", "in"},
    "category_id":   {"eq", "neq", "in"},
    "category_name": {"contains", "regex"},
    "color_id":      {"eq", "neq", "in"},
    "year_from":     {"eq", "neq", "gte", "lte"},
    "year_to":       {"eq", "neq", "gte", "lte"},
    "bricklink_id":  {"eq", "neq", "in"},
    "bl_category_id":    {"eq", "neq", "in"},
    "bl_category_name":  {"contains", "regex"},
    "bl_catalog_name":   {"contains", "regex"},
    "bl_price_min":  {"eq", "neq", "gte", "lte"},
    "bl_price_max":  {"eq", "neq", "gte", "lte"},
    "bl_price_avg":  {"eq", "neq", "gte", "lte"},
    "bl_price_qty_avg":  {"eq", "neq", "gte", "lte"},
    "bl_price_lots": {"eq", "neq", "gte", "lte"},
    "bl_price_qty":  {"eq", "neq", "gte", "lte"},
    "bl_catalog_year_released": {"eq", "neq", "gte", "lte"},
    "bl_catalog_weight": {"eq", "neq", "gte", "lte"},
    "bl_catalog_dim_x":  {"eq", "neq", "gte", "lte"},
    "bl_catalog_dim_y":  {"eq", "neq", "gte", "lte"},
    "bl_catalog_dim_z":  {"eq", "neq", "gte", "lte"},
    "bl_catalog_is_obsolete": {"eq", "neq"},
    "bricklink_item_count": {"eq", "neq", "gte", "lte"},
    "bricklink_primary_item_no": {"eq", "neq", "contains", "regex"},
}


# --- structured output ---

class ConditionProposal(BaseModel):
    field: str
    op: str
    value: str | int | float | list[str] | list[int]

    @field_validator("field")
    @classmethod
    def validateField(cls, v: str) -> str:
        if v not in VALID_FIELDS:
            raise ValueError(f"Invalid field '{v}'. Valid: {sorted(VALID_FIELDS)}")
        return v

    @field_validator("op")
    @classmethod
    def validateOp(cls, v: str) -> str:
        if v not in VALID_OPS:
            raise ValueError(f"Invalid op '{v}'. Valid: {sorted(VALID_OPS)}")
        return v


class RuleProposal(BaseModel):
    explanation: str
    name: str
    match_mode: str
    conditions: list[ConditionProposal]

    @field_validator("match_mode")
    @classmethod
    def validateMatchMode(cls, v: str) -> str:
        if v not in ("all", "any"):
            raise ValueError("match_mode must be 'all' or 'any'")
        return v


# --- context / deps ---

@dataclass
class AiChatDeps:
    current_rule: dict
    all_rules: list[dict]
    categories: dict[int, dict]
    bricklink_categories: dict[int, dict]
    colors: dict[int, dict]
    parts: dict[str, dict]


def _collectAncestorChecks(rules: list[dict], rule_id: str) -> list[dict] | None:
    for rule in rules:
        if rule.get("id") == rule_id:
            return []
        children = rule.get("children", [])
        result = _collectAncestorChecks(children, rule_id)
        if result is not None:
            checks = [{"conditions": rule.get("conditions", []), "match_mode": rule.get("match_mode", "all")}]
            checks.extend(result)
            return checks
    return None


def _buildAncestorChecks(current_rule: dict, all_rules: list[dict]) -> list[dict]:
    rule_id = current_rule.get("id")
    if not rule_id:
        return []
    result = _collectAncestorChecks(all_rules, rule_id)
    return result or []


def _formatRuleSummary(rule: dict, indent: int = 0) -> str:
    prefix = "  " * indent
    conds = rule.get("conditions", [])
    mode = rule.get("match_mode", "all")
    disabled = " [DISABLED]" if rule.get("disabled") else ""
    lines = [f"{prefix}- {rule.get('name', '?')}{disabled} (match_mode={mode})"]
    for c in conds:
        lines.append(f"{prefix}    {c.get('field')} {c.get('op')} {json.dumps(c.get('value'))}")
    for child in rule.get("children", []):
        lines.append(_formatRuleSummary(child, indent + 1))
    return "\n".join(lines)


def _formatExistingRules(all_rules: list[dict]) -> str:
    if not all_rules:
        return "(no rules yet)"
    return "\n".join(_formatRuleSummary(r) for r in all_rules)


def _buildSystemPrompt(ctx: RunContext[AiChatDeps]) -> str:
    deps = ctx.deps
    rule = deps.current_rule

    # build compact category lists
    rb_cats = ", ".join(f"{cid}: {c['name']}" for cid, c in sorted(deps.categories.items()))
    bl_cats = ", ".join(
        f"{cid}: {c.get('category_name', '')}"
        for cid, c in sorted(deps.bricklink_categories.items())
    )
    colors = ", ".join(f"{cid}: {c['name']}" for cid, c in sorted(deps.colors.items()))

    field_ops_str = "\n".join(f"  {f}: {sorted(ops)}" for f, ops in sorted(FIELD_OPS.items()))

    existing_rules = _formatExistingRules(deps.all_rules)

    return f"""You edit sorting rules for a LEGO part sorting machine.

A rule matches LEGO parts based on conditions. Each condition has a field, operator, and value.
The rule's match_mode is "all" (AND - every condition must match) or "any" (OR - at least one must match).

CURRENT RULE STATE:
  name: {rule.get('name', 'New Rule')}
  match_mode: {rule.get('match_mode', 'all')}
  conditions: {json.dumps(rule.get('conditions', []), indent=2)}

AVAILABLE FIELDS AND THEIR OPERATORS:
{field_ops_str}

VALUE TYPES:
- category_id, bl_category_id: integer ID from the lists below
- color_id: integer ID from the color list below
- name, category_name, bl_category_name, bl_catalog_name: string (use contains or regex)
- part_num, bricklink_id: string
- year_from, year_to, bl_catalog_year_released: integer year
- price fields: float
- "in" operator: value must be a list

REBRICKABLE CATEGORIES:
{rb_cats}

BRICKLINK CATEGORIES:
{bl_cats}

COLORS:
{colors}

USER'S CURRENT SAVED RULES (for reference, to demonstrate the rule system's capabilities):
{existing_rules}

TESTING RULES:
You have two tools to test candidate rules against the real parts database BEFORE proposing them:
- tryRuleStandalone: tests the rule in isolation. "Standalone" means just this rule's conditions,
  ignoring all other rules. Use this to understand what the conditions match on their own.
- tryRuleInContext: tests the rule within the full rule hierarchy. "In context" means the rule is
  evaluated with its parent/ancestor conditions applied — a part only matches if it also passes
  all ancestor conditions. This shows what the rule would actually match in the real sorting profile.

Skip testing for trivial changes (renames, toggling a single value). For most edits, 2-5 test calls
is enough — sanity-check the match count and move on. Only go to 10+ calls if the user is insistent
that the rule is very complex, or if your test results are clearly not matching what you expected.

INSTRUCTIONS:
- Return a RuleProposal with the COMPLETE updated rule (not just changes).
- Include ALL conditions, not just new ones. If the user says "also add X", keep existing conditions and add the new one.
- If the user says "change" or "replace", modify accordingly.
- Give a short explanation of what you changed AND the match counts from your testing.
- Use the correct category/color IDs from the lists above.
- Make sure field+op combinations are valid per the table above."""


_rule_agent: Agent[AiChatDeps, RuleProposal] | None = None


def _getAgent() -> Agent[AiChatDeps, RuleProposal]:
    global _rule_agent
    if _rule_agent is not None:
        return _rule_agent
    _rule_agent = Agent(
        "anthropic:claude-sonnet-4-6",
        deps_type=AiChatDeps,
        output_type=RuleProposal,
        instructions=_buildSystemPrompt,
        retries=3,
    )

    @_rule_agent.output_validator
    def validateProposal(_ctx: RunContext[AiChatDeps], proposal: RuleProposal) -> RuleProposal:
        for i, cond in enumerate(proposal.conditions):
            allowed_ops = FIELD_OPS.get(cond.field)
            if allowed_ops and cond.op not in allowed_ops:
                raise ModelRetry(
                    f"Condition {i}: op '{cond.op}' not valid for field '{cond.field}'. "
                    f"Valid ops: {sorted(allowed_ops)}"
                )
            if cond.op == "in" and not isinstance(cond.value, list):
                raise ModelRetry(f"Condition {i}: op 'in' requires a list value, got {type(cond.value).__name__}")
        return proposal

    @_rule_agent.tool
    def tryRuleStandalone(ctx: RunContext[AiChatDeps], conditions_json: str, match_mode: str) -> str:
        """Test a rule in standalone mode against the parts database.
        Returns the total match count and a sample of up to 10 matched part names.
        Standalone means just this rule alone, ignoring all other rules in the profile.
        conditions_json: JSON array of condition objects, each with field, op, value.
        match_mode: "all" or "any"."""
        try:
            conditions = json.loads(conditions_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"
        rule = {"conditions": conditions, "match_mode": match_mode}
        deps = ctx.deps
        result = previewRule(
            rule, deps.parts,
            categories=deps.categories,
            bricklink_categories=deps.bricklink_categories,
            limit=10,
        )
        total = result["total"]
        sample = result["sample"]
        if total == 0:
            return "0 parts matched."
        names = [f"  - {p.get('name', p.get('part_num', '?'))}" for p in sample]
        more = f"\n  ... and {total - len(sample)} more" if total > len(sample) else ""
        return f"{total} parts matched. Sample:\n" + "\n".join(names) + more

    @_rule_agent.tool
    def tryRuleInContext(ctx: RunContext[AiChatDeps], conditions_json: str, match_mode: str) -> str:
        """Test a rule in-context against the parts database.
        Returns the total match count and a sample of up to 10 matched part names.
        In-context means this rule is evaluated within the full rule hierarchy — a part only
        matches if it ALSO satisfies all ancestor/parent rule conditions. Use this to see what
        the rule would actually match in the real sorting profile.
        conditions_json: JSON array of condition objects, each with field, op, value.
        match_mode: "all" or "any"."""
        try:
            conditions = json.loads(conditions_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"
        rule = {"conditions": conditions, "match_mode": match_mode}
        deps = ctx.deps
        # build ancestor checks from the current rule's position in the hierarchy
        ancestor_checks = _buildAncestorChecks(deps.current_rule, deps.all_rules)
        result = previewRule(
            rule, deps.parts,
            categories=deps.categories,
            bricklink_categories=deps.bricklink_categories,
            limit=10,
            ancestor_checks=ancestor_checks,
        )
        total = result["total"]
        sample = result["sample"]
        if total == 0:
            return "0 parts matched in context (with ancestor conditions applied)."
        names = [f"  - {p.get('name', p.get('part_num', '?'))}" for p in sample]
        more = f"\n  ... and {total - len(sample)} more" if total > len(sample) else ""
        return f"{total} parts matched in context. Sample:\n" + "\n".join(names) + more

    return _rule_agent


# --- chat persistence ---

def getOrCreateChat(conn: sqlite3.Connection, profile_id: str, rule_id: str) -> dict:
    row = conn.execute(
        "SELECT id, pydantic_messages, created_at, updated_at FROM ai_chats WHERE profile_id=? AND rule_id=?",
        (profile_id, rule_id),
    ).fetchone()
    if row:
        return {"id": row[0], "pydantic_messages": row[1], "created_at": row[2], "updated_at": row[3]}
    chat_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO ai_chats (id, profile_id, rule_id, pydantic_messages, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (chat_id, profile_id, rule_id, "[]", now, now),
    )
    conn.commit()
    return {"id": chat_id, "pydantic_messages": "[]", "created_at": now, "updated_at": now}


def saveChatMessages(conn: sqlite3.Connection, chat_id: str, pydantic_messages_json: str):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE ai_chats SET pydantic_messages=?, updated_at=? WHERE id=?",
        (pydantic_messages_json, now, chat_id),
    )
    conn.commit()


def addDisplayMessage(conn: sqlite3.Connection, chat_id: str, role: str, content: str, proposed_rule: dict | None = None, tool_calls: list[dict] | None = None) -> dict:
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    proposed_json = json.dumps(proposed_rule) if proposed_rule else None
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
    conn.execute(
        "INSERT INTO ai_chat_messages (id, chat_id, role, content, proposed_rule, accepted, tool_calls, created_at) VALUES (?,?,?,?,?,0,?,?)",
        (msg_id, chat_id, role, content, proposed_json, tool_calls_json, now),
    )
    conn.commit()
    return {"id": msg_id, "role": role, "content": content, "proposed_rule": proposed_rule, "tool_calls": tool_calls, "accepted": 0, "created_at": now}


def getChatHistory(conn: sqlite3.Connection, chat_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, role, content, proposed_rule, accepted, tool_calls, created_at FROM ai_chat_messages WHERE chat_id=? ORDER BY created_at",
        (chat_id,),
    ).fetchall()
    messages = []
    for r in rows:
        messages.append({
            "id": r[0], "role": r[1], "content": r[2],
            "proposed_rule": json.loads(r[3]) if r[3] else None,
            "accepted": r[4],
            "tool_calls": json.loads(r[5]) if r[5] else None,
            "created_at": r[6],
        })
    return messages


def acceptProposal(conn: sqlite3.Connection, message_id: str) -> dict | None:
    row = conn.execute(
        "SELECT id, proposed_rule FROM ai_chat_messages WHERE id=? AND role='assistant' AND proposed_rule IS NOT NULL",
        (message_id,),
    ).fetchone()
    if not row:
        return None
    conn.execute("UPDATE ai_chat_messages SET accepted=1 WHERE id=?", (message_id,))
    conn.commit()
    return json.loads(row[1])


def deleteChat(conn: sqlite3.Connection, profile_id: str, rule_id: str):
    row = conn.execute(
        "SELECT id FROM ai_chats WHERE profile_id=? AND rule_id=?",
        (profile_id, rule_id),
    ).fetchone()
    if not row:
        return
    chat_id = row[0]
    conn.execute("DELETE FROM ai_chat_messages WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM ai_chats WHERE id=?", (chat_id,))
    conn.commit()


def _trimDanglingToolCalls(messages: list) -> list:
    """Remove trailing ModelResponse with tool calls that have no matching tool return."""
    from pydantic_ai.messages import ModelResponse, ModelRequest, ToolCallPart, ToolReturnPart
    trimmed = list(messages)
    while trimmed:
        last = trimmed[-1]
        if isinstance(last, ModelResponse):
            has_tool_calls = any(isinstance(p, ToolCallPart) for p in last.parts)
            if has_tool_calls:
                trimmed.pop()
                continue
        break
    return trimmed


def _savePartialState(conn: sqlite3.Connection, chat_id: str, messages_snapshot: list, collected_tool_calls: list[dict]):
    try:
        clean_messages = _trimDanglingToolCalls(messages_snapshot)
        pydantic_json = to_json(clean_messages).decode()
        saveChatMessages(conn, chat_id, pydantic_json)
        if collected_tool_calls:
            addDisplayMessage(conn, chat_id, "assistant", "(stopped by user)", tool_calls=collected_tool_calls)
        log.info(f"saved partial state: {len(clean_messages)} pydantic messages (trimmed from {len(messages_snapshot)}), {len(collected_tool_calls)} tool calls")
    except Exception:
        log.exception("failed to save partial state")


# --- main chat function ---

async def chatWithRuleStream(
    conn: sqlite3.Connection,
    profile_id: str,
    rule_id: str,
    user_message: str,
    current_rule: dict,
    all_rules: list[dict],
    parts_data: PartsData,
) -> AsyncIterator[dict]:
    """Yields SSE-style event dicts as the agent works. Event types:
    - {"event": "tool_call", "tool": name, "args": {...}}
    - {"event": "tool_result", "tool": name, "result": "..."}
    - {"event": "text_delta", "delta": "..."}
    - {"event": "result", "chat_id": ..., "user_message": ..., "assistant_message": ...}
    - {"event": "error", "detail": "..."}
    """
    log.info(f"chatWithRuleStream profile={profile_id} rule={rule_id} msg={user_message!r}")
    chat = getOrCreateChat(conn, profile_id, rule_id)
    chat_id = chat["id"]

    user_msg = addDisplayMessage(conn, chat_id, "user", user_message)

    stored_json = chat["pydantic_messages"]
    history_count = 0
    if stored_json != "[]":
        message_history = ModelMessagesTypeAdapter.validate_json(stored_json)
        history_count = len(message_history)
    else:
        message_history = []
    log.info(f"restored {history_count} pydantic messages for chat {chat_id}")

    deps = AiChatDeps(
        current_rule=current_rule,
        all_rules=all_rules,
        categories=parts_data.categories,
        bricklink_categories=parts_data.bricklink_categories,
        colors=parts_data.colors,
        parts=parts_data.parts,
    )

    agent = _getAgent()
    log.info("calling pydantic-ai agent (streaming)...")

    collected_tool_calls: list[dict] = []
    current_tool_call: dict | None = None
    messages_snapshot: list = list(message_history)
    saved = False

    try:
        async with agent.iter(user_message, deps=deps, message_history=message_history, usage_limits=UsageLimits(request_limit=200)) as agent_run:
            async for node in agent_run:
                # snapshot after each node so we can save on cancel
                try:
                    messages_snapshot = agent_run.all_messages()
                except Exception:
                    pass
                if Agent.is_call_tools_node(node):
                    async with node.stream(agent_run.ctx) as handle_stream:
                        async for event in handle_stream:
                            if isinstance(event, FunctionToolCallEvent):
                                args = event.part.args
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except Exception:
                                        pass
                                current_tool_call = {"tool": event.part.tool_name, "args": args, "result": None}
                                yield {"event": "tool_call", "tool": event.part.tool_name, "args": args}
                            elif isinstance(event, FunctionToolResultEvent):
                                content = ""
                                if isinstance(event.result, ToolReturnPart):
                                    content = str(event.result.content)
                                if current_tool_call:
                                    current_tool_call["result"] = content
                                    collected_tool_calls.append(current_tool_call)
                                    current_tool_call = None
                                yield {"event": "tool_result", "tool": event.result.tool_name, "result": content}

            result = agent_run.result
            if result is None:
                yield {"event": "error", "detail": "Agent produced no result"}
                _savePartialState(conn, chat_id, messages_snapshot, collected_tool_calls)
                saved = True
                return

        proposal = result.output
        log.info(f"agent returned: name={proposal.name!r} conditions={len(proposal.conditions)} explanation={proposal.explanation!r}")
        proposed_rule = {
            "name": proposal.name,
            "match_mode": proposal.match_mode,
            "conditions": [{"field": c.field, "op": c.op, "value": c.value} for c in proposal.conditions],
        }

        assistant_msg = addDisplayMessage(
            conn, chat_id, "assistant", proposal.explanation, proposed_rule,
            tool_calls=collected_tool_calls if collected_tool_calls else None,
        )

        all_messages = result.all_messages()
        pydantic_json = to_json(all_messages).decode()
        saveChatMessages(conn, chat_id, pydantic_json)
        saved = True
        log.info(f"saved {len(all_messages)} pydantic messages, {len(collected_tool_calls)} tool calls")

        yield {
            "event": "result",
            "chat_id": chat_id,
            "user_message": user_msg,
            "assistant_message": assistant_msg,
        }

    except (asyncio.CancelledError, GeneratorExit):
        log.info("ai chat stream cancelled by client")
    except Exception as e:
        log.exception("pydantic-ai agent failed")
        yield {"event": "error", "detail": str(e)}
    finally:
        if not saved:
            log.info(f"saving partial state: {len(collected_tool_calls)} tool calls")
            _savePartialState(conn, chat_id, messages_snapshot, collected_tool_calls)
