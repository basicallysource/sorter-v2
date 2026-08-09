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


class TestStatsScopeKeys:
    """hv_* API keys with stats:read replace the shared secret (kept for legacy)."""

    def _admin_headers(self, client, db):
        from app.models.user import User
        from tests.conftest import _auth_headers, _login_user, _register_user

        _register_user(client, "stats-admin@test.com", "Password123!", "Stats Admin")
        _login_user(client, "stats-admin@test.com", "Password123!")
        user = db.query(User).filter(User.email == "stats-admin@test.com").first()
        user.role = "admin"
        db.commit()
        _login_user(client, "stats-admin@test.com", "Password123!")
        return _auth_headers(client)

    def _mint(self, client, headers, scopes, machine_ids=None):
        payload = {"name": "stats-key", "scopes": scopes}
        if machine_ids is not None:
            payload["machine_ids"] = machine_ids
        r = client.post("/api/auth/api-keys", json=payload, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()["raw_token"]

    def test_stats_read_key_accepted_without_env_secret(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        token = self._mint(client, headers, ["stats:read"])
        r = client.get("/api/public/stats", headers=_bearer(token))
        assert r.status_code == 200, r.text
        assert "last_24h_pieces" in r.json()

    def test_key_without_stats_scope_403s(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        token = self._mint(client, headers, ["models:read"])
        r = client.get("/api/public/stats", headers=_bearer(token))
        assert r.status_code == 403
        assert "stats:read" in r.json()["error"]

    def test_machine_scoped_key_cannot_read_fleet_stats(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        m = client.post(
            "/api/machines",
            json={"name": "Stats Sorter", "description": "d"},
            headers=headers,
        )
        assert m.status_code in (200, 201)
        token = self._mint(client, headers, ["stats:read"], machine_ids=[m.json()["id"]])
        r = client.get("/api/public/stats", headers=_bearer(token))
        assert r.status_code == 403

    def test_legacy_secret_still_accepted(self, client, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", STATS_KEY)
        r = client.get("/api/public/stats", headers={"X-Stats-Key": STATS_KEY})
        assert r.status_code == 200


class TestFleetRoster:
    """/api/public/fleet — machines with owner Discord identity where linked."""

    def _admin_headers(self, client, db):
        return TestStatsScopeKeys._admin_headers(TestStatsScopeKeys(), client, db)

    def _mint(self, client, headers, scopes, machine_ids=None):
        return TestStatsScopeKeys._mint(TestStatsScopeKeys(), client, headers, scopes, machine_ids)

    def test_requires_key(self, client, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        assert client.get("/api/public/fleet").status_code in (401, 503)

    def test_a_stats_only_key_cannot_read_the_roster(self, client, db, monkeypatch):
        """The whole point of the two scopes: a key minted for a public consumer
        draws the aggregates and is refused the list of machines and owners."""
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        token = self._mint(client, headers, ["stats:read"])
        assert client.get("/api/public/stats", headers=_bearer(token)).status_code == 200
        r = client.get("/api/public/fleet", headers=_bearer(token))
        assert r.status_code == 403
        assert "fleet:read" in r.json()["error"]

    def test_a_fleet_only_key_cannot_read_the_aggregates(self, client, db, monkeypatch):
        """And the reverse, so neither scope is quietly a superset of the other."""
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        token = self._mint(client, headers, ["fleet:read"])
        assert client.get("/api/public/fleet", headers=_bearer(token)).status_code == 200
        r = client.get("/api/public/stats", headers=_bearer(token))
        assert r.status_code == 403
        assert "stats:read" in r.json()["error"]

    def test_the_legacy_shared_secret_does_not_open_the_roster(self, client, monkeypatch):
        """It opens the anonymous tier and only that. A shared secret cannot be
        revoked per consumer, so it must never stand in for fleet:read."""
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", STATS_KEY)
        assert client.get("/api/public/stats", headers={"X-Stats-Key": STATS_KEY}).status_code == 200
        assert client.get("/api/public/fleet", headers={"X-Stats-Key": STATS_KEY}).status_code == 401

    def test_roster_masks_unlinked_owners(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        m = client.post(
            "/api/machines",
            json={"name": "Roster Sorter", "description": "d"},
            headers=headers,
        )
        assert m.status_code in (200, 201)
        token = self._mint(client, headers, ["fleet:read"])

        r = client.get("/api/public/fleet", headers=_bearer(token))
        assert r.status_code == 200, r.text
        body = r.json()
        mine = next(x for x in body["machines"] if x["name"] == "Roster Sorter")
        assert mine["owner_discord"] is None
        assert body["machine_count"] == len(body["machines"])

        # Link a Discord identity to the owner; the roster now names them.
        from app.models.user import User
        from app.models.user_identity import UserIdentity

        user = db.query(User).filter(User.email == "stats-admin@test.com").first()
        db.add(
            UserIdentity(
                user_id=user.id,
                provider="discord",
                provider_user_id="123456789012345678",
                provider_login="spencer",
            )
        )
        db.commit()

        r = client.get("/api/public/fleet", headers=_bearer(token))
        mine = next(x for x in r.json()["machines"] if x["name"] == "Roster Sorter")
        assert mine["owner_discord"] == {
            "id": "123456789012345678",
            "login": "spencer",
            "avatar_url": None,
        }
        assert r.json()["discord_linked_count"] >= 1

    def test_machine_scoped_key_rejected(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        m = client.post(
            "/api/machines",
            json={"name": "Scoped Sorter", "description": "d"},
            headers=headers,
        )
        token = self._mint(client, headers, ["fleet:read"], machine_ids=[m.json()["id"]])
        assert client.get("/api/public/fleet", headers=_bearer(token)).status_code == 403

    def test_roster_carries_the_numbers_a_leaderboard_needs(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        m = client.post(
            "/api/machines", json={"name": "Counting Sorter", "description": "d"}, headers=headers
        )
        assert m.status_code in (200, 201)
        token = self._mint(client, headers, ["fleet:read"])
        entry = next(
            x
            for x in client.get("/api/public/fleet", headers=_bearer(token)).json()["machines"]
            if x["name"] == "Counting Sorter"
        )
        for field in ("pieces_seen", "distributed", "overall_ppm", "last_24h_pieces",
                      "last_hour_pieces"):
            assert field in entry, f"{field} missing from the roster entry"
        # A machine that has never sorted reports zeros rather than nulls, so a
        # consumer can sort on these without special-casing a fresh machine.
        assert entry["pieces_seen"] == 0 and entry["last_24h_pieces"] == 0
        assert entry["last_hour_pieces"] == 0

    def test_the_hour_window_is_narrower_than_the_day(self, client, db, monkeypatch, machine_token):
        """A machine that sorted this morning but not this hour is powered on,
        not working — the two counters have to be able to disagree."""
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        token = self._mint(client, headers, ["fleet:read"])
        now = time.time()
        _sync(client, machine_token, [
            {"piece_uuid": "h-now", "local_id": 1, "seen_at": now - 60,
             "classification_status": "classified", "part_id": "3001", "color_id": "5"},
            {"piece_uuid": "h-old", "local_id": 2, "seen_at": now - 5 * 3600,
             "classification_status": "classified", "part_id": "3001", "color_id": "5"},
        ])
        body = client.get("/api/public/fleet", headers=_bearer(token)).json()
        mine = max(body["machines"], key=lambda m: m["last_24h_pieces"])
        assert mine["last_24h_pieces"] == 2
        assert mine["last_hour_pieces"] == 1
