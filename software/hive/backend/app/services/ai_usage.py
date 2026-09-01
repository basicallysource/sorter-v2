from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.ai_usage_event import AiUsageEvent

logger = logging.getLogger(__name__)

PERIOD_DAYS = {"week": 7, "month": 30, "year": 365}


@dataclass
class AiUsageTotals:
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    call_count: int
    message_count: int


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def record_ai_usage(
    db: Session,
    *,
    user_id: UUID,
    purpose: str,
    model: str | None,
    usage: dict[str, Any] | None,
    profile_id: UUID | None = None,
    message_id: UUID | None = None,
    generation_ids: list[str] | None = None,
    call_count: int = 1,
) -> AiUsageEvent | None:
    usage = usage or {}
    details = usage.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}

    event = AiUsageEvent(
        user_id=user_id,
        profile_id=profile_id,
        message_id=message_id,
        purpose=purpose,
        model=model,
        generation_ids=generation_ids or None,
        call_count=max(1, call_count),
        prompt_tokens=_int(usage.get("prompt_tokens")),
        completion_tokens=_int(usage.get("completion_tokens")),
        total_tokens=_int(usage.get("total_tokens")),
        cached_tokens=_int(details.get("cached_tokens")),
        cache_write_tokens=_int(details.get("cache_write_tokens")),
        cost_usd=_float_or_none(usage.get("cost")),
    )
    db.add(event)

    logger.info(
        "ai_usage.recorded purpose=%s user=%s profile=%s message=%s model=%s cost_usd=%s tokens=%s calls=%s",
        purpose,
        user_id,
        profile_id,
        message_id,
        model,
        event.cost_usd,
        event.total_tokens,
        event.call_count,
    )
    return event


def usage_totals(db: Session, *, user_id: UUID, since: datetime | None) -> AiUsageTotals:
    query = db.query(
        func.coalesce(func.sum(AiUsageEvent.cost_usd), 0.0),
        func.coalesce(func.sum(AiUsageEvent.prompt_tokens), 0),
        func.coalesce(func.sum(AiUsageEvent.completion_tokens), 0),
        func.coalesce(func.sum(AiUsageEvent.total_tokens), 0),
        func.coalesce(func.sum(AiUsageEvent.call_count), 0),
        func.count(AiUsageEvent.id),
    ).filter(AiUsageEvent.user_id == user_id)
    if since is not None:
        query = query.filter(AiUsageEvent.created_at >= since)

    try:
        row = query.one()
    except SQLAlchemyError:
        logger.exception("ai_usage.totals_failed user=%s", user_id)
        return AiUsageTotals(0.0, 0, 0, 0, 0, 0)

    return AiUsageTotals(
        cost_usd=round(float(row[0] or 0.0), 6),
        prompt_tokens=_int(row[1]),
        completion_tokens=_int(row[2]),
        total_tokens=_int(row[3]),
        call_count=_int(row[4]),
        message_count=_int(row[5]),
    )


def usage_summary(db: Session, *, user_id: UUID) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    periods: dict[str, Any] = {}
    for name, days in PERIOD_DAYS.items():
        totals = usage_totals(db, user_id=user_id, since=now - timedelta(days=days))
        periods[name] = totals.__dict__
    periods["all_time"] = usage_totals(db, user_id=user_id, since=None).__dict__

    first_event = (
        db.query(func.min(AiUsageEvent.created_at))
        .filter(AiUsageEvent.user_id == user_id)
        .scalar()
    )
    return {**periods, "since": first_event}
