"""Analytics over a machine set: daily aggregation, timeseries, auth scopes."""

from __future__ import annotations

from app.models.user import User
from tests.conftest import _login_user, _register_user, refresh_stats


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
    refresh_stats()


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
    # Colors carry a BrickLink swatch hex; the key is always present (None when
    # the parts catalog has no swatch or isn't loaded, as in this test env).
    assert any(c["color_id"] == "5" for c in dist["top_colors"])
    assert all("rgb" in c for c in dist["top_colors"])
    # Category breakdown is always a list (empty when no parts catalog is loaded,
    # as in this test env); each row is a name and a count.
    assert isinstance(dist["top_categories"], list)
    assert all({"category_name", "value"} <= set(c) for c in dist["top_categories"])


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


def test_piece_counter_is_live_between_refreshes(client, machine_token, test_machine):
    """The headline counter tops up from the cache watermark; the rest doesn't.

    This is the whole tiering, in one test. Pieces that arrive after a refresh
    are counted immediately, because that number is what people watch climb.
    The distributions and the daily series they belong to stay as of the last
    pass, because recomputing those on demand is what pinned the box.
    """
    _sync_two_days(client, machine_token)  # syncs, then refreshes

    later = 1_760_000_000.0 + 2 * 86400.0
    r = client.post(
        "/api/machine/sync/piece-records",
        headers=_bearer(machine_token),
        json={"records": [
            {"piece_uuid": "e", "local_id": 5, "seen_at": later,
             "classification_status": "classified", "part_id": "3003", "color_id": "9"},
        ]},
    )
    assert r.status_code == 200, r.text

    body = client.get(f"/api/analytics?machine_id={test_machine['id']}").json()
    assert body["totals"]["pieces_seen"] == 5          # live
    assert len(body["timeseries"]) == 2                # still as of the last pass
    part_ids = {p["part_id"] for p in body["distributions"]["top_parts"]}
    assert "3003" not in part_ids
    assert body["fresh_as_of"] is not None

    refresh_stats()
    body = client.get(f"/api/analytics?machine_id={test_machine['id']}").json()
    assert body["totals"]["pieces_seen"] == 5          # not double-counted
    assert len(body["timeseries"]) == 3
    assert "3003" in {p["part_id"] for p in body["distributions"]["top_parts"]}


def test_distributions_fold_across_machines(client, db, machine_token, test_machine):
    """Two machines' cached maps merge into one correct answer.

    A per-machine top-N could not do this: unique_parts for the pair is the
    size of the union of their part maps, and the fleet ranking has to see
    every key, not each machine's leaders.
    """
    _sync_two_days(client, machine_token)
    user = db.query(User).filter(User.email == "member@test.com").first()
    user.role = "admin"
    db.commit()

    body = client.get("/api/analytics?scope=all").json()
    # 3001 appears on both days, 3002 on one; "d" has no part id at all.
    assert body["totals"]["unique_parts"] == 2
    assert body["totals"]["unique_colors"] == 2
    ranked = [(p["part_id"], p["value"]) for p in body["distributions"]["top_parts"]]
    assert ranked[0] == ("3001", 2)
    assert dict(body["distributions"]["by_status"] and
                {s["label"]: s["value"] for s in body["distributions"]["by_status"]}) == {
        "classified": 3, "unknown": 1}
