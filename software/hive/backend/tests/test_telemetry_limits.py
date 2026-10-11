"""The telemetry limits Hive sets for machines: defaults, the admin API, and the
heartbeat that hands them out."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import User

DEFAULTS = {
    "version": 1,
    "sample_burst_interval_s": 10.0,
    "sample_floor_interval_s": 3600.0,
    "sample_ramp_hours": 72.0,
    "sample_store_max_bytes": 1073741824,
    "upload_bytes_per_minute": 30000000,
    "upload_files_per_minute": 120,
}


def _make_admin(db: Session) -> None:
    user = db.query(User).filter(User.email == "member@test.com").first()
    user.role = "admin"
    db.commit()


def _heartbeat(client, token: str):
    return client.post("/api/machine/heartbeat", headers={"Authorization": f"Bearer {token}"}, json={})


def test_heartbeat_carries_the_default_limits(client, test_machine, machine_token):
    resp = _heartbeat(client, machine_token)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "machine_id": test_machine["id"], "limits": DEFAULTS}


def test_admin_reads_defaults_then_updates_some_limits(client, db, machine_token, auth_headers):
    _make_admin(db)

    resp = client.get("/api/admin/telemetry-limits")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {**DEFAULTS, "updated_at": None}

    resp = client.put(
        "/api/admin/telemetry-limits",
        json={"sample_ramp_hours": 24, "upload_files_per_minute": 60},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sample_ramp_hours"] == 24.0
    assert body["upload_files_per_minute"] == 60
    assert body["sample_burst_interval_s"] == 10.0  # untouched
    assert body["updated_at"] is not None

    # A second partial update keeps the first one.
    resp = client.put("/api/admin/telemetry-limits", json={"sample_burst_interval_s": 5}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["sample_ramp_hours"] == 24.0

    limits = _heartbeat(client, machine_token).json()["limits"]
    assert limits == {**DEFAULTS, "sample_ramp_hours": 24.0, "upload_files_per_minute": 60, "sample_burst_interval_s": 5.0}


def test_admin_update_is_validated(client, db, auth_headers):
    _make_admin(db)

    for bad in (
        {"sample_burst_interval_s": 0},
        {"upload_bytes_per_minute": -1},
        {"upload_files_per_minute": 1.5},
        {"sample_ramp_hours": "lots"},
        {"no_such_limit": 1},
    ):
        resp = client.put("/api/admin/telemetry-limits", json=bad, headers=auth_headers)
        assert resp.status_code == 422, (bad, resp.text)

    # The floor is where the ramp ends, so it may not be faster than the burst,
    # whether the request moves one end or both.
    resp = client.put("/api/admin/telemetry-limits", json={"sample_floor_interval_s": 5}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_TELEMETRY_LIMITS"
    resp = client.put(
        "/api/admin/telemetry-limits",
        json={"sample_burst_interval_s": 60, "sample_floor_interval_s": 30},
        headers=auth_headers,
    )
    assert resp.status_code == 400

    # Nothing was written by the refused requests.
    assert client.get("/api/admin/telemetry-limits").json() == {**DEFAULTS, "updated_at": None}


def test_telemetry_limits_are_admin_only(client, auth_headers):
    assert client.get("/api/admin/telemetry-limits").status_code == 403
    resp = client.put("/api/admin/telemetry-limits", json={"sample_ramp_hours": 1}, headers=auth_headers)
    assert resp.status_code == 403
