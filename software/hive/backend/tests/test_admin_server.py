"""The admin Server page's endpoint: admin only, and every part present."""

from __future__ import annotations

import pytest

from app.models.user import User
from tests.conftest import _login_user, _register_user


@pytest.fixture()
def admin(client, db) -> None:
    _register_user(client, "admin@test.com", "Password123!", "Admin")
    user = db.query(User).filter(User.email == "admin@test.com").first()
    user.role = "admin"
    db.commit()
    _login_user(client, "admin@test.com", "Password123!")


def test_server_page_needs_a_session(client):
    assert client.get("/api/admin/server").status_code == 401


def test_server_page_is_admin_only(client, test_user):
    assert client.get("/api/admin/server").status_code == 403


def test_server_page_has_every_part(client, admin):
    assert client.get("/api/health").status_code == 200

    r = client.get("/api/admin/server")
    assert r.status_code == 200, r.text
    body = r.json()
    for part in ("process", "requests", "workers", "jobs", "database", "disk", "memory", "storage"):
        assert part in body and "error" not in (body[part] if isinstance(body[part], dict) else {}), (part, body[part])

    # Timed by the middleware, under the route's template.
    routes = {(row["method"], row["route"]) for row in body["requests"]["routes"]}
    assert ("GET", "/api/health") in routes
    assert body["requests"]["totals"]["count"] >= 1

    workers = {w["name"]: w for w in body["workers"]}
    assert {"Machine stats", "Labeling queue", "Storage walk", "Job queue", "Teacher"} <= set(workers)
    assert isinstance(body["jobs"]["kinds"], list)
    assert body["database"] == {"dialect": "sqlite"}
    assert body["process"]["db_pool"]["checked_out"] is not None
    assert body["process"]["threadpool"]["size"] >= 1
    assert all(d["total_bytes"] > 0 for d in body["disk"])
