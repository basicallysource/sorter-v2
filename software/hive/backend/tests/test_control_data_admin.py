"""Admin control-data inventory endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.machine_control_data_segment import MachineControlDataSegment
from app.models.user import User


def _seed_segments(db, machine_id: str) -> None:
    base = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
    rows = [
        dict(local_id=1, started_at=base, ended_at=base + timedelta(minutes=30), records=1000, bytes=50_000,
             machine_setup="classification_channel", feeder_mode="PULSE_PERCEPTION_REV01",
             classification_mode="TWO_PIECE_STATE_MACHINE_REV01", autotune_mode=None,
             data_key=f"{machine_id}/control_data/1.jsonl.gz", evicted_locally=False),
        dict(local_id=2, started_at=base + timedelta(hours=1), ended_at=base + timedelta(hours=1, minutes=15),
             records=500, bytes=25_000, machine_setup="classification_channel",
             feeder_mode="PULSE_PERCEPTION_REV01", classification_mode="TWO_PIECE_STATE_MACHINE_REV01",
             autotune_mode="background", data_key=f"{machine_id}/control_data/2.jsonl.gz", evicted_locally=False),
        dict(local_id=3, started_at=base + timedelta(hours=2), ended_at=base + timedelta(hours=2, minutes=10),
             records=200, bytes=10_000, machine_setup="classification_channel",
             feeder_mode="GO_TO_ANGLE_REV01", classification_mode="TWO_PIECE_STATE_MACHINE_REV01",
             autotune_mode=None, data_key=None, evicted_locally=True),
    ]
    for row in rows:
        db.add(MachineControlDataSegment(machine_id=uuid.UUID(machine_id), **row))
    db.commit()


def test_summary_admin_only(client, test_machine):
    assert client.get("/api/admin/control-data/summary").status_code == 403


def test_summary_aggregates(client, db, test_machine):
    _seed_segments(db, test_machine["id"])
    user = db.query(User).filter(User.email == "member@test.com").first()
    user.role = "admin"
    db.commit()

    r = client.get("/api/admin/control-data/summary")
    assert r.status_code == 200, r.text
    body = r.json()

    totals = body["totals"]
    assert totals["segments"] == 3
    assert totals["records"] == 1700
    assert totals["bytes"] == 85_000
    assert totals["machines"] == 1
    assert totals["with_file"] == 2
    assert totals["evicted"] == 1
    assert totals["autotune_background"] == 1
    assert totals["plain"] == 2
    assert abs(totals["hours"] - (55 / 60)) < 0.02

    assert len(body["machines"]) == 1
    machine_row = body["machines"][0]
    assert machine_row["machine_id"] == test_machine["id"]
    assert machine_row["name"] == test_machine["name"]
    assert machine_row["segments"] == 3
    assert machine_row["feeder_modes"] == ["GO_TO_ANGLE_REV01", "PULSE_PERCEPTION_REV01"]

    feeder_dim = {entry["value"]: entry for entry in body["dimensions"]["feeder_mode"]}
    assert feeder_dim["PULSE_PERCEPTION_REV01"]["segments"] == 2
    assert feeder_dim["PULSE_PERCEPTION_REV01"]["machines"] == 1
    assert feeder_dim["GO_TO_ANGLE_REV01"]["segments"] == 1
    autotune_dim = {entry["value"]: entry for entry in body["dimensions"]["autotune_mode"]}
    assert autotune_dim[None]["segments"] == 2
    assert autotune_dim["background"]["segments"] == 1

    assert len(body["recent"]) == 3
    assert {seg["local_id"] for seg in body["recent"]} == {1, 2, 3}
    missing = [seg for seg in body["recent"] if seg["local_id"] == 3][0]
    assert missing["has_file"] is False


def test_summary_empty(client, db, test_user):
    user = db.query(User).filter(User.email == "member@test.com").first()
    user.role = "admin"
    db.commit()
    r = client.get("/api/admin/control-data/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["segments"] == 0
    assert body["machines"] == []
    assert body["recent"] == []
