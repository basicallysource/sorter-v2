from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from server import api as api_module  # noqa: E402


def _row(
    uuid: str,
    *,
    gid: int,
    active: bool,
    status: str,
    sort_ts: float,
    part_id: str | None = None,
    angle: float | None = None,
) -> dict[str, Any]:
    return {
        "uuid": uuid,
        "piece": {
            "uuid": uuid,
            "tracked_global_id": gid,
            "classification_status": status,
            "part_id": part_id,
        },
        "tracked_global_id": gid,
        "global_id": gid,
        "live": active,
        "active": active,
        "polar_angle_deg": angle,
        "polar_offset_deg": angle,
        "created_at": sort_ts,
        "updated_at": sort_ts,
        "stage": "registered" if active else "distributed",
        "classification_status": status,
        "track_summary": None,
        "has_track_segments": False,
        "preview_jpeg_path": None,
        "sort_ts": sort_ts,
        "history_finished_at": None,
    }


def test_tracked_pieces_dedupes_active_splits_but_keeps_history() -> None:
    rows = [
        _row("pending-new", gid=7, active=True, status="pending", sort_ts=20.0, angle=35.0),
        _row(
            "classified-old",
            gid=7,
            active=True,
            status="classified",
            sort_ts=10.0,
            part_id="3001",
            angle=12.0,
        ),
        _row(
            "distributed",
            gid=7,
            active=False,
            status="classified",
            sort_ts=5.0,
            part_id="3001",
            angle=None,
        ),
    ]

    deduped = api_module._dedupe_tracked_piece_rows(rows)

    assert len(deduped) == 2
    active = next(row for row in deduped if row["active"])
    history = next(row for row in deduped if not row["active"])
    assert active["uuid"] == "classified-old"
    assert active["piece"]["part_id"] == "3001"
    assert active["sort_ts"] == 20.0
    assert active["polar_angle_deg"] == 35.0
    assert history["uuid"] == "distributed"


def test_tracked_pieces_treats_lost_dossier_as_history(monkeypatch) -> None:
    piece = {
        "uuid": "lost-piece",
        "tracked_global_id": 9,
        "stage": "registered",
        "classification_status": "pending",
        "classification_channel_zone_state": "lost",
        "updated_at": 20.0,
    }
    monkeypatch.setattr(api_module, "list_piece_dossiers", lambda **_kwargs: [piece])
    monkeypatch.setattr(api_module, "_tracked_history_summary_map", lambda _limit: {})
    monkeypatch.setattr(
        api_module,
        "_current_classification_drop_angle_deg",
        lambda: 30.0,
    )
    monkeypatch.setattr(api_module, "get_piece_segment_counts", lambda piece_uuids: {})
    monkeypatch.setattr(api_module, "get_piece_preview_paths", lambda piece_uuids: {})

    result = api_module.get_tracked_pieces(limit=20)

    assert result["items"][0]["uuid"] == "lost-piece"
    assert result["items"][0]["active"] is False
