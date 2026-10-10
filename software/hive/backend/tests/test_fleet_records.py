"""/api/public/fleet/records: speed, milestones and newest finds per machine."""

from __future__ import annotations

import time

import pytest

from app.config import settings
from app.models.machine import Machine
from app.services import analytics, fleet_records, machine_stats
from tests import test_public_stats as public_stats
from tests.test_public_stats import _bearer, _sync


def _piece(uuid, local_id, seen_at, **fields):
    return {"piece_uuid": uuid, "local_id": local_id, "seen_at": seen_at, **fields}


def _sorted(part, color):
    return {"classification_status": "classified", "part_id": part, "color_id": color, "bin_x": 1}


@pytest.fixture()
def two_machines(client, auth_headers, machine_token, test_machine, monkeypatch):
    """Machine A sorted four pieces, one of them a day and a half ago and one a
    double feed; machine B sorted two, both in the last few minutes."""
    monkeypatch.setattr(fleet_records, "FLEET_MILESTONES", (2, 3))
    monkeypatch.setattr(fleet_records, "FLEET_MILESTONE_STEP", 10)
    monkeypatch.setattr(fleet_records, "MACHINE_MILESTONES", (2, 3))
    fleet_records.reset_cache()

    other = client.post("/api/machines", json={"name": "Other Sorter", "description": "d"},
                        headers=auth_headers)
    assert other.status_code in (200, 201), other.text

    now = time.time()
    _sync(client, machine_token, [
        _piece("a1", 1, now - 36 * 3600, **_sorted("3001", "5")),
        _piece("a2", 2, now - 120, **_sorted("3001", "5")),
        _piece("a3", 3, now - 90, **_sorted("3002", "11")),
        _piece("a4", 4, now - 60, classification_status="multi_drop_fail"),
    ])
    _sync(client, other.json()["raw_token"], [
        _piece("b1", 1, now - 100, **_sorted("3003", "11")),
        _piece("b2", 2, now - 50, **_sorted("3004", "any_color")),
    ])
    yield test_machine["id"], other.json()["id"]
    fleet_records.reset_cache()


def _refresh(db):
    ids = [mid for (mid,) in db.query(Machine.id).all()]
    analytics.refresh_daily_stats(db)
    machine_stats.refresh_all(db)
    return fleet_records.refresh(db, ids)


def _key(client, db, scope):
    # Imported as a module, not by name: a test class imported into this file
    # would be collected and run a second time from here.
    keys = public_stats.TestStatsScopeKeys()
    return keys._mint(client, keys._admin_headers(client, db), [scope])


def test_records(client, db, two_machines, monkeypatch):
    a, b = two_machines
    monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
    _refresh(db)

    token = _key(client, db, "fleet:read")
    r = client.get("/api/public/fleet/records", headers=_bearer(token))
    assert r.status_code == 200, r.text
    body = r.json()

    speed = {s["machine_id"]: s for s in body["speed"]}
    # The day leaves out the piece from a day and a half ago; the double feed
    # counts as a piece but was never put in a bin.
    assert speed[a]["day"] == {"pieces": 3, "distributed": 2, "double_feeds": 1, "active_seconds": 60.0}
    assert speed[b]["day"]["active_seconds"] == 50.0
    # The month has it, and the gap before it is idle time, not running time.
    assert speed[a]["month"] == {"pieces": 4, "distributed": 3, "active_seconds": 60.0}

    # Fleet order: a1, a2, b1, a3, ... so the 2nd piece was A's and the 3rd B's.
    assert [(m["pieces"], m["machine_id"]) for m in body["fleet_milestones"]] == [(2, a), (3, b)]
    assert body["fleet_milestones"][1]["part_id"] == "3003"
    assert body["next_fleet_milestone"] == 10
    assert body["fleet_pieces"] == 6

    # A reached two pieces (a2) before B did (b2), and only A reached three.
    assert [(m["pieces"], m["machine_id"]) for m in body["machine_milestones"]] == [(2, a), (3, a)]

    assert [(p["part_id"], p["machine_id"], p["ordinal"]) for p in body["newest_parts"]] == [
        ("3004", b, 4), ("3002", a, 3), ("3003", b, 2), ("3001", a, 1)]
    assert body["distinct_parts"] == 4
    # "any_color" is not a colour; colour 11 was B's find even though A saw it later.
    assert [(c["color_id"], c["machine_id"]) for c in body["newest_colors"]] == [("11", b), ("5", a)]
    assert body["distinct_colors"] == 2

    roster = client.get("/api/public/fleet", headers=_bearer(token)).json()
    mine = next(m for m in roster["machines"] if m["id"] == a)
    assert (mine["unique_parts"], mine["unique_colors"]) == (2, 2)


def test_a_milestone_does_not_move_once_answered(client, db, two_machines, machine_token):
    """A backlog uploaded late, with an earlier seen_at, would take the record
    off its holder. Once given, the answer stands."""
    a, b = two_machines
    _refresh(db)
    _sync(client, machine_token, [_piece("late", 5, time.time() - 110, **_sorted("3001", "5"))])
    body = _refresh(db)
    assert [(m["pieces"], m["machine_id"]) for m in body["fleet_milestones"]] == [(2, a), (3, b)]


def test_a_stats_key_cannot_read_records(client, db, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
    r = client.get("/api/public/fleet/records", headers=_bearer(_key(client, db, "stats:read")))
    assert r.status_code == 403
