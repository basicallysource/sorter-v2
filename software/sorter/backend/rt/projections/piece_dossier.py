"""Project rt piece-lifecycle events into the SQLite dossier table.

Subscribes to ``PIECE_REGISTERED`` / ``PIECE_CLASSIFIED`` / ``PIECE_DISTRIBUTED``
on the rt event bus and upserts the flattened payload into the piece_dossiers
table via ``local_state.remember_piece_dossier``. The dossier table is what
the UI and the ``SetProgressSync`` worker read from, so this projection keeps
those consumers fed without pushing persistence into the perception/runtime
hot path.

Pure subscriber — no perception coupling. Wire with ``install(bus)`` once
per rt runtime build.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from rt.contracts.events import Event, EventBus
from rt.events.topics import (
    PIECE_CLASSIFIED,
    PIECE_DISTRIBUTED,
    PIECE_REGISTERED,
)

_LOG = logging.getLogger(__name__)

_TOPIC_TO_STAGE = {
    PIECE_REGISTERED: "registered",
    PIECE_CLASSIFIED: "classified",
    PIECE_DISTRIBUTED: "distributed",
}


def install(bus: EventBus) -> None:
    """Attach the piece-dossier projection to the three piece-lifecycle topics.

    Import or subscribe failures are swallowed with a warning so a missing
    persistence helper cannot stop the rt runtime from coming up.
    """
    try:
        from local_state import remember_piece_dossier
    except Exception:
        _LOG.warning(
            "piece_dossier projection: could not import local_state (non-fatal)"
        )
        return

    def _on_piece_event(event: Event) -> None:
        payload = dict(event.payload or {})
        piece_uuid = payload.get("piece_uuid") or payload.get("uuid")
        if not isinstance(piece_uuid, str) or not piece_uuid.strip():
            _LOG.debug(
                "piece_dossier projection: event missing piece_uuid (topic=%s)",
                event.topic,
            )
            return
        # Flatten: merge the nested "dossier" shape into the top-level
        # payload so the dossier row carries part_id / bin_id / etc.
        dossier_payload: dict[str, Any] = dict(payload)
        nested = payload.get("dossier")
        if isinstance(nested, dict):
            for k, v in nested.items():
                dossier_payload.setdefault(k, v)
        stage = str(payload.get("stage") or _TOPIC_TO_STAGE.get(event.topic, ""))
        if event.topic == PIECE_DISTRIBUTED:
            dossier_payload.setdefault("distributed_at", time.time())
        try:
            remember_piece_dossier(
                piece_uuid,
                dossier_payload,
                status=stage or None,
            )
        except Exception:
            _LOG.debug(
                "piece_dossier projection: remember_piece_dossier raised",
                exc_info=True,
            )

    for topic in (PIECE_REGISTERED, PIECE_CLASSIFIED, PIECE_DISTRIBUTED):
        bus.subscribe(topic, _on_piece_event)


__all__ = ["install"]
