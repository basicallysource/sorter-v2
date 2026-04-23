"""Project rt piece-lifecycle events into the SQLite dossier table.

Subscribes to ``PIECE_REGISTERED`` / ``PIECE_CLASSIFIED`` / ``PIECE_DISTRIBUTED``
on the rt event bus and upserts the flattened payload into the piece_dossiers
table via ``local_state.remember_piece_dossier``. After persisting, the
merged row is also mirrored into the ``recent_known_objects`` ring (so a
freshly connecting WS client sees the piece on replay) and pushed live to
all open WS clients as a ``known_object`` event (so the Recent Pieces panel
on the dashboard updates without a reload).

Pure subscriber — the imports into ``local_state`` / ``server.shared_state``
are lazy so rt/ stays free of server-boot-time coupling. Wire with
``install(bus)`` once per rt runtime build.
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
        from local_state import (
            get_piece_dossier,
            get_piece_preview_paths,
            remember_piece_dossier,
            remember_recent_known_object,
        )
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
        event_wall = time.time()
        if event.topic == PIECE_CLASSIFIED:
            # rt events carry the monotonic classifier timestamp separately
            # as classified_ts_mono; UI/runtime stats need wall time here.
            dossier_payload["classified_at"] = event_wall
            category = dossier_payload.get("category")
            if isinstance(category, str) and category.strip():
                dossier_payload.setdefault("part_category", category)
        if event.topic == PIECE_DISTRIBUTED:
            dossier_payload["distributed_at"] = event_wall
            category = dossier_payload.get("category")
            if isinstance(category, str) and category.strip():
                dossier_payload.setdefault("category_id", category)
            reason = dossier_payload.get("reason")
            if isinstance(reason, str) and reason.strip():
                dossier_payload.setdefault("distribution_reason", reason)
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
            return

        # Read back the authoritative merged view the SQLite upsert just
        # produced — it carries server-filled defaults (stage,
        # classification_status, created/updated timestamps) so the live
        # event shape matches what a reconnecting client gets on replay.
        try:
            merged = get_piece_dossier(piece_uuid)
        except Exception:
            _LOG.debug(
                "piece_dossier projection: get_piece_dossier raised",
                exc_info=True,
            )
            return
        if not isinstance(merged, dict):
            return

        try:
            preview_paths = get_piece_preview_paths([piece_uuid])
            preview = preview_paths.get(piece_uuid)
            if isinstance(preview, str) and preview.strip():
                merged["preview_jpeg_path"] = preview
                remember_piece_dossier(piece_uuid, merged, status=stage or None)
                refreshed = get_piece_dossier(piece_uuid)
                if isinstance(refreshed, dict):
                    merged = refreshed
                    merged["preview_jpeg_path"] = preview
        except Exception:
            _LOG.debug(
                "piece_dossier projection: preview enrichment raised",
                exc_info=True,
            )

        try:
            from server.services import runtime_stats as runtime_stats_service

            runtime_stats_service.observe_known_object(merged)
        except Exception:
            _LOG.debug(
                "piece_dossier projection: runtime_stats observe raised",
                exc_info=True,
            )

        try:
            remember_recent_known_object(merged)
        except Exception:
            _LOG.debug(
                "piece_dossier projection: remember_recent_known_object raised",
                exc_info=True,
            )

        # Live push to every open WS client. Lazy-import shared_state so
        # this module stays import-safe before the server loop exists.
        try:
            from server import shared_state
        except Exception:
            return
        try:
            shared_state.broadcast_from_thread(
                {"tag": "known_object", "data": merged}
            )
        except Exception:
            _LOG.debug(
                "piece_dossier projection: broadcast_from_thread raised",
                exc_info=True,
            )

    for topic in (PIECE_REGISTERED, PIECE_CLASSIFIED, PIECE_DISTRIBUTED):
        bus.subscribe(topic, _on_piece_event)


__all__ = ["install"]
