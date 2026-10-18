"""Machine -> Hive telemetry records (sqlite dialect path)."""

from __future__ import annotations

from uuid import UUID

from app.models.machine import Machine
from app.models.machine_hardware_report import MachineHardwareReport
from app.models.machine_telemetry import MachineTelemetryRecord

BASE = 1_760_000_000.0


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _window(local_id: int, **data) -> dict:
    return {
        "local_id": local_id, "kind": "stepper_load", "form": "window", "schema": 1,
        "started_at": BASE + local_id, "ended_at": BASE + local_id + 3600,
        "data": {"steppers": {"chute": {"samples": 10, "bands": []}}, **data},
    }


def test_records_upsert_by_local_id_and_move_the_watermark(client, db, machine_token, test_machine):
    batch = [_window(1), _window(2)]
    r1 = client.post("/api/machine/sync/telemetry", headers=_bearer(machine_token), json={"records": batch})
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"max_local_id": 2, "upserted": 2, "skipped": 0}
    # Sent again (a retry): no duplicates, the last copy wins.
    batch[1]["data"]["note"] = "again"
    r2 = client.post("/api/machine/sync/telemetry", headers=_bearer(machine_token), json={"records": batch})
    assert r2.json()["max_local_id"] == 2
    rows = db.query(MachineTelemetryRecord).filter_by(machine_id=UUID(test_machine["id"])).order_by(MachineTelemetryRecord.local_id).all()
    assert [(r.local_id, r.kind, r.form, r.schema) for r in rows] == [(1, "stepper_load", "window", 1), (2, "stepper_load", "window", 1)]
    assert rows[1].data["note"] == "again"
    assert (rows[0].ended_at - rows[0].started_at).total_seconds() == 3600
    state = client.get("/api/machine/sync/state", headers=_bearer(machine_token)).json()
    assert state["telemetry"] == {"max_local_id": 2}


def test_a_bad_record_is_skipped_and_the_watermark_still_moves(client, db, machine_token, test_machine):
    bad_kind = {**_window(3), "kind": "Not A Kind"}
    backwards = {**_window(4), "ended_at": BASE}
    too_large = _window(5, blob="x" * (70 * 1024))
    r = client.post(
        "/api/machine/sync/telemetry",
        headers=_bearer(machine_token),
        json={"records": [bad_kind, backwards, too_large, _window(6)]},
    )
    assert r.json() == {"max_local_id": 6, "upserted": 1, "skipped": 3}
    assert [row.local_id for row in db.query(MachineTelemetryRecord).filter_by(machine_id=UUID(test_machine["id"]))] == [6]


def test_specs_become_the_machines_hardware_report(client, db, machine_token, test_machine):
    specs = {
        "schema_version": 3, "boot_id": "boot-1", "captured_at": "2026-10-18T23:00:00+00:00",
        "platform": {"model": "Orange Pi 5", "arch": "aarch64", "os": {"name": "Ubuntu"}},
        "controller_boards": {"distribution": {"family": "basically"}},
        "steppers": {"chute": {"sgthrs": 55}},
    }
    record = {"local_id": 7, "kind": "machine_specs", "form": "snapshot", "started_at": BASE, "ended_at": BASE, "data": specs}
    r = client.post("/api/machine/sync/telemetry", headers=_bearer(machine_token), json={"records": [record]})
    assert r.status_code == 200, r.text
    db.expire_all()
    machine = db.get(Machine, UUID(test_machine["id"]))
    assert machine.hardware_info["platform"]["model"] == "Orange Pi 5"
    [report] = db.query(MachineHardwareReport).filter_by(machine_id=UUID(test_machine["id"])).all()
    assert report.specs["steppers"] == {"chute": {"sgthrs": 55}}


def test_telemetry_needs_a_machine_token(client):
    assert client.post("/api/machine/sync/telemetry", json={"records": []}).status_code == 422
    assert client.post("/api/machine/sync/telemetry", headers=_bearer("bogus"), json={"records": []}).status_code == 401
