"""The service-to-service aggregate stats endpoint (key auth + the 24h window)."""

from __future__ import annotations

import time

from app.config import settings

STATS_KEY = "test-public-stats-key"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sync(client, machine_token, records) -> None:
    r = client.post("/api/machine/sync/piece-records",
                    headers=_bearer(machine_token), json={"records": records})
    assert r.status_code == 200, r.text


def test_requires_key(client, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", STATS_KEY)
    assert client.get("/api/public/stats").status_code == 401
    assert client.get("/api/public/stats", headers={"X-Stats-Key": "nope"}).status_code == 401


def test_last_24h_is_a_rolling_window(client, monkeypatch, machine_token):
    """Only pieces inside the trailing 24h count — not the whole calendar day,
    and not anything older than the window regardless of what day it landed on."""
    monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", STATS_KEY)
    now = time.time()
    _sync(client, machine_token, [
        {"piece_uuid": "recent-1", "local_id": 1, "seen_at": now - 60,
         "classification_status": "classified", "part_id": "3001", "color_id": "5"},
        {"piece_uuid": "recent-2", "local_id": 2, "seen_at": now - 23 * 3600,
         "classification_status": "classified", "part_id": "3001", "color_id": "5"},
        {"piece_uuid": "stale", "local_id": 3, "seen_at": now - 25 * 3600,
         "classification_status": "classified", "part_id": "3001", "color_id": "5"},
        {"piece_uuid": "ancient", "local_id": 4, "seen_at": now - 9 * 86400,
         "classification_status": "classified", "part_id": "3001", "color_id": "5"},
    ])

    r = client.get("/api/public/stats", headers={"X-Stats-Key": STATS_KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_24h_pieces"] == 2
    assert body["totals"]["pieces_seen"] == 4
