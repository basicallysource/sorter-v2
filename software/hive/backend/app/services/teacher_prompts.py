"""Resolve teacher prompts at detection time.

Two layers:
- Default templates live in code (``gemini_prompt_template`` for chat-style adapters,
  ``perceptron_zone_instruction`` for Perceptron). Always available even with an empty
  DB — the feature is purely additive.
- A persisted DB override per (zone, kind) lets the admin edit those templates in
  /settings without redeploys. When a row exists in ``teacher_prompts`` it wins.

Call sites (preview, sync rerun, batch worker) ask :func:`resolve_prompt` for the
ready-to-send instruction once per call and forward it through the existing
``override_prompt`` channel on the adapter. That keeps the adapter code blissfully
unaware of where its prompt came from — same path the compare-page ad-hoc edit uses.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.teacher_prompt import TeacherPrompt
from app.services.teacher_adapters.perceptron import _zone_instruction as _perceptron_default_instruction
from app.services.teacher_detector import gemini_prompt_template


# Keep these tuples in sync with teacher_detector.ZONE_PROMPTS / _zone_instruction.
SUPPORTED_PROMPT_ZONES: tuple[str, ...] = (
    "classification_channel",
    "c_channel",
    "classification_chamber",
    "carousel",
)
SUPPORTED_PROMPT_KINDS: tuple[str, ...] = ("chat", "perceptron")


@dataclass(frozen=True)
class ResolvedPrompt:
    content: str          # ready-to-send (chat: width/height substituted; perceptron: raw)
    is_custom: bool       # True if a DB override exists for (zone, kind)
    raw_template: str     # the template before substitution — what the editor shows


def default_template(zone: str, kind: str) -> str:
    """Hardcoded default template (chat: with {width}/{height} placeholders intact)."""
    if kind == "perceptron":
        return _perceptron_default_instruction(zone)
    if kind == "chat":
        return gemini_prompt_template(zone)
    raise ValueError(f"unknown teacher prompt kind: {kind!r}")


def _render(template: str, kind: str, *, width: int, height: int) -> str:
    """Substitute {width}/{height} placeholders for chat prompts only."""
    if kind == "chat":
        try:
            return template.format(width=width, height=height)
        except (KeyError, IndexError, ValueError):
            # Admin-edited template with malformed placeholders — send as-is rather
            # than crash the detection call. The compare page surfaces the literal
            # bracketed text in raw response so the issue is debuggable.
            return template
    return template


def resolve_prompt(
    db: Session,
    zone: str,
    kind: str,
    *,
    width: int = 1024,
    height: int = 1024,
) -> ResolvedPrompt:
    """Return the prompt to send to the adapter for ``(zone, kind)``.

    Falls back to the hardcoded default when no DB override is present, so deletion
    of a row in ``teacher_prompts`` cleanly reverts to baseline behaviour.
    """
    row = (
        db.query(TeacherPrompt)
        .filter(TeacherPrompt.zone == zone, TeacherPrompt.kind == kind)
        .first()
    )
    if row is None:
        tmpl = default_template(zone, kind)
        return ResolvedPrompt(
            content=_render(tmpl, kind, width=width, height=height),
            is_custom=False,
            raw_template=tmpl,
        )
    return ResolvedPrompt(
        content=_render(row.content, kind, width=width, height=height),
        is_custom=True,
        raw_template=row.content,
    )


def adapter_kind_for(adapter_kind: str) -> str:
    """Translate the adapter's ``adapter_kind`` attribute to a prompt ``kind``.

    Chat-shaped adapters (openrouter_chat, grok) share the long Gemini-style prompt.
    Perceptron uses its own short native instruction. Keep this mapping in one place so
    new adapters slot in cleanly.
    """
    if adapter_kind == "perceptron":
        return "perceptron"
    return "chat"
