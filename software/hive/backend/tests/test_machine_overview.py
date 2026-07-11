"""Single-machine overview + owner/admin piece access + server-health."""

from __future__ import annotations

from app.models.user import User
from tests.conftest import _login_user, _register_user


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sync_pieces(client, machine_token) -> None:
    base = 1_760_000_000.0
    records = [
        {"piece_uuid": "a", "local_id": 1, "seen_at": base, "classification_status": "classified",
         "part_id": "3001", "color_id": "5", "bin_x": 1, "bin_y": 0, "bin_z": 0},
        {"piece_uuid": "b", "local_id": 2, "seen_at": base + 5, "classification_status": "classified",
         "part_id": "3002", "color_id": "5", "bin_x": 1, "bin_y": 0, "bin_z": 0},
    ]
    client.post("/api/machine/sync/piece-records", headers=_bearer(machine_token), json={"records": records})


def test_overview_owner_admin_and_forbidden(client, db, machine_token, test_machine):
    _sync_pieces(client, machine_token)

    # Owner (member@test.com, logged in via fixtures) sees their machine.
    r = client.get(f"/api/machines/{test_machine['id']}/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["machine"]["id"] == test_machine["id"]
    assert body["is_owner"] is True
    assert body["viewer_is_admin"] is False
    assert body["stats"]["pieces_seen"] == 2
    assert body["stats"]["distributed"] == 2
    assert body["stats"]["computed_at"] is not None

    # A different member gets 404 (existence not leaked), not 403.
    _register_user(client, "other@test.com", "Password123!", "Other User")
    _login_user(client, "other@test.com", "Password123!")
    assert client.get(f"/api/machines/{test_machine['id']}/overview").status_code == 404

    # Promote that user to admin -> can view any machine.
    other = db.query(User).filter(User.email == "other@test.com").first()
    other.role = "admin"
    db.commit()
    r = client.get(f"/api/machines/{test_machine['id']}/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_owner"] is False
    assert body["viewer_is_admin"] is True


def test_owner_can_list_own_pieces(client, machine_token, test_machine):
    _sync_pieces(client, machine_token)
    r = client.get(f"/api/machines/{test_machine['id']}/pieces")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_pieces_forbidden_for_other_member(client, db, machine_token, test_machine):
    _sync_pieces(client, machine_token)
    _register_user(client, "nope@test.com", "Password123!", "Nope")
    _login_user(client, "nope@test.com", "Password123!")
    assert client.get(f"/api/machines/{test_machine['id']}/pieces").status_code == 404


def test_server_health_admin_only(client, db, test_machine):
    # Logged in as member -> forbidden.
    assert client.get("/api/admin/server-health").status_code == 403

    user = db.query(User).filter(User.email == "member@test.com").first()
    user.role = "admin"
    db.commit()

    r = client.get("/api/admin/server-health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"storage", "database", "memory"}
    assert "sample_images" in body["storage"]
    assert "piece_images" in body["storage"]
    assert "total_bytes" in body["storage"]
    assert "tables" in body["database"]
    assert "used_bytes" in body["memory"]


def test_refresh_stats_endpoint(client, db, test_machine, machine_token):
    _sync_pieces(client, machine_token)
    user = db.query(User).filter(User.email == "member@test.com").first()
    user.role = "admin"
    db.commit()
    csrf = client.cookies.get("csrf_token", "")
    r = client.post("/api/admin/machines/stats/refresh", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["refreshed"] >= 1
