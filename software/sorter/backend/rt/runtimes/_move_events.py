from __future__ import annotations

import logging
import time
from typing import Any

from rt.contracts.events import Event, EventBus
from rt.events.topics import RUNTIME_MOVE_COMPLETED


def publish_move_completed(
    bus: EventBus | None,
    logger: logging.Logger,
    *,
    runtime_id: str,
    feed_id: str | None,
    source: str,
    ok: bool,
    duration_ms: float | int | None = None,
    degrees: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Publish a side-effect event after a hardware move command returns."""

    if bus is None or not feed_id:
        return
    now_wall = time.time()
    payload: dict[str, Any] = {
        "feed_id": feed_id,
        "source": source,
        "ok": bool(ok),
        "completed_ts": float(now_wall),
    }
    if duration_ms is not None:
        payload["duration_ms"] = float(duration_ms)
    if degrees is not None:
        payload["degrees"] = float(degrees)
    if extra:
        payload.update(extra)
    try:
        bus.publish(
            Event(
                topic=RUNTIME_MOVE_COMPLETED,
                payload=payload,
                source=runtime_id,
                ts_mono=time.monotonic(),
            )
        )
    except Exception:
        logger.exception(
            "Runtime move-completed publish failed (runtime=%s source=%s)",
            runtime_id,
            source,
        )


__all__ = ["publish_move_completed"]
