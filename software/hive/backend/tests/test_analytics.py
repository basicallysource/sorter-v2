"""Analytics over a machine set: daily aggregation, timeseries, auth scopes."""

from __future__ import annotations

from app.models.user import User
from tests.conftest import _login_user, _register_user


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sync_two_days(client, machine_token) -> None:
    # Day 1: 1_760_000_000 = 2025-10-09 UTC; +86400 -> day 2. Two distributed
    # pieces 5s apart each day (active gap counts), one far-apart piece (idle).
    d1 = 1_760_000_000.0
    d2 = d1 + 86400.0
    records = [
        {"piece_uuid": "a", "local_id": 1, "seen_at": d1, "classification_status": "classified",
         "part_id": "3001", "color_id": "5", "bin_x": 1, "bin_y": 0, "bin_z": 0},
        {"piece_uuid": "b", "local_id": 2, "seen_at": d1 + 5, "classification_status": "classified",
         "part_id": "3002", "color_id": "5", "bin_x": 1, "bin_y": 0, "bin_z": 0},
        {"piece_uuid": "c", "local_id": 3, "seen_at": d2, "classification_status": "classified",
         "part_id": "3001", "color_id": "4", "bin_x": 1, "bin_y": 0, "bin_z": 0},
        {"piece_uuid": "d", "local_id": 4, "seen_at": d2 + 5, "classification_status": "unknown",
         "part_id": None, "color_id": None},
    ]
    r = client.post("/api/machine/sync/piece-records", headers=_bearer(machine_token), json={"records": records})
    assert r.status_code == 200, r.text


def test_single_machine_analytics(client, machine_token, test_machine):
    _sync_two_days(client, machine_token)
    r = client.get(f"/api/analytics?machine_id={test_machine['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"]["kind"] == "machine"
    assert body["scope"]["machine_count"] == 1

    ts = body["timeseries"]
    assert len(ts) == 2  # two distinct days
    assert ts[0]["pieces_seen"] == 2 and ts[1]["pieces_seen"] == 2
    # Cumulative pieces monotonically increase; one machine seen from day 1.
    assert ts[0]["cumulative_pieces"] == 2 and ts[1]["cumulative_pieces"] == 4
    assert ts[0]["cumulative_machines"] == 1 and ts[1]["cumulative_machines"] == 1
    # Day 1: 2 distributed over 5s active -> ppm = 2*60/5 = 24; capacity = 24*1440.
    assert abs(ts[0]["throughput_ppm"] - 24.0) < 0.01
    assert abs(ts[0]["capacity_per_day"] - 24.0 * 1440.0) < 1.0

    totals = body["totals"]
    assert totals["pieces_seen"] == 4
    assert totals["distributed"] == 3
    assert totals["classified"] == 3
    assert totals["unique_parts"] == 2  # 3001, 3002 (piece d has null part)
    assert totals["machines"] == 1

    dist = body["distributions"]
    statuses = {d["label"]: d["value"] for d in dist["by_status"]}
    assert statuses.get("classified") == 3 and statuses.get("unknown") == 1
    assert dist["by_machine"] == []  # single machine -> omitted
    parts = {d["part_id"]: d["value"] for d in dist["top_parts"]}
    assert parts.get("3001") == 2 and parts.get("3002") == 1


def test_my_fleet_scope_default(client, machine_token, test_machine):
    _sync_two_days(client, machine_token)
    r = client.get("/api/analytics")  # default scope = my fleet
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"]["kind"] == "my_fleet"
    assert body["totals"]["pieces_seen"] == 4


def test_scope_all_requires_admin(client, db, machine_token, test_machine):
    _sync_two_days(client, machine_token)
    # member -> forbidden
    assert client.get("/api/analytics?scope=all").status_code == 403
    # promote -> allowed
    user = db.query(User).filter(User.email == "member@test.com").first()
    user.role = "admin"
    db.commit()
    r = client.get("/api/analytics?scope=all")
    assert r.status_code == 200, r.text
    assert r.json()["scope"]["kind"] == "all"
    assert r.json()["totals"]["pieces_seen"] == 4


def test_other_users_machine_is_404(client, db, machine_token, test_machine):
    _sync_two_days(client, machine_token)
    _register_user(client, "other@test.com", "Password123!", "Other")
    _login_user(client, "other@test.com", "Password123!")
    assert client.get(f"/api/analytics?machine_id={test_machine['id']}").status_code == 404
    # their own (empty) fleet is fine, just empty
    r = client.get("/api/analytics")
    assert r.status_code == 200
    assert r.json()["timeseries"] == []
