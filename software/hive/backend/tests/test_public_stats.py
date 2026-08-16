"""The service-to-service aggregate stats endpoint (key auth + the 24h window)."""

from __future__ import annotations

import json
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
        assert body["registered_machine_count"] == len(body["machines"])

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
        assert r.json()["registered_discord_linked_count"] >= 1

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
                      "last_hour_pieces", "last_30d_pieces"):
            assert field in entry, f"{field} missing from the roster entry"
        # A machine that has never sorted reports zeros rather than nulls, so a
        # consumer can sort on these without special-casing a fresh machine.
        assert entry["pieces_seen"] == 0 and entry["last_24h_pieces"] == 0
        assert entry["last_hour_pieces"] == 0

    def test_a_machine_is_active_only_once_it_has_really_sorted(
        self, client, db, monkeypatch, machine_token
    ):
        """Registering is free, so the roster separates rows from real machines.

        Both counts are served: the registered one for anybody who genuinely
        wants it, the active one for anybody about to say a number out loud.
        """
        from app.routers import public_stats
        from app.services import machine_stats

        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        # Three pieces stands in for the real 250 — the point under test is the
        # comparison, not the constant, and 251 inserts would only be slower.
        monkeypatch.setattr(public_stats, "ACTIVE_MACHINE_MIN_PIECES", 2)
        headers = self._admin_headers(client, db)
        # A registration that never sorts anything — the exact thing the
        # threshold exists to keep out of the number people are shown.
        client.post(
            "/api/machines", json={"name": "Bench Sorter", "description": "d"}, headers=headers
        )
        token = self._mint(client, headers, ["fleet:read"])

        body = client.get("/api/public/fleet", headers=_bearer(token)).json()
        assert body["active_threshold_pieces"] == 2
        assert body["active_machine_count"] == 0
        assert body["registered_machine_count"] == len(body["machines"])
        assert all(not m["is_active"] for m in body["machines"])

        now = time.time()
        _sync(client, machine_token, [
            {"piece_uuid": f"real-{i}", "local_id": i, "seen_at": now - 60 * i,
             "classification_status": "classified", "part_id": "3001", "color_id": "5"}
            for i in range(1, 4)
        ])
        # The roster reads the hourly cache rather than recomputing, so the
        # worker's pass has to happen before the machine can look real.
        machine_stats.refresh_cache(db)

        body = client.get("/api/public/fleet", headers=_bearer(token)).json()
        sorted_one = max(body["machines"], key=lambda m: m["pieces_seen"])
        assert sorted_one["pieces_seen"] == 3 and sorted_one["is_active"]
        assert body["active_machine_count"] == 1
        assert body["registered_machine_count"] > body["active_machine_count"]

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
        # The month contains both, so the windows nest rather than overlap.
        assert mine["last_30d_pieces"] == 2


class TestContributors:
    """/api/public/contributors — the people tier, behind its own scope."""

    def _admin_headers(self, client, db):
        return TestStatsScopeKeys._admin_headers(TestStatsScopeKeys(), client, db)

    def _mint(self, client, headers, scopes):
        return TestStatsScopeKeys._mint(TestStatsScopeKeys(), client, headers, scopes)

    def test_needs_its_own_scope(self, client, db, monkeypatch):
        """A fleet key must not read the contributor list, and vice versa: the
        two describe different populations."""
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        fleet = self._mint(client, headers, ["fleet:read"])
        r = client.get("/api/public/contributors", headers=_bearer(fleet))
        assert r.status_code == 403
        assert "contributors:read" in r.json()["error"]

        contrib = self._mint(client, headers, ["contributors:read"])
        assert client.get("/api/public/contributors", headers=_bearer(contrib)).status_code == 200
        assert client.get("/api/public/fleet", headers=_bearer(contrib)).status_code == 403

    def test_the_legacy_secret_does_not_open_it(self, client, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", STATS_KEY)
        r = client.get("/api/public/contributors", headers={"X-Stats-Key": STATS_KEY})
        assert r.status_code == 401

    def test_every_window_is_served_at_once(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        token = self._mint(client, headers, ["contributors:read"])
        body = client.get("/api/public/contributors", headers=_bearer(token)).json()
        assert set(body["periods"]) == {"24h", "7d", "30d", "all"}

    def test_no_avatar_and_no_user_id_leak(self, client, db, monkeypatch):
        """The avatar URL embeds a Discord snowflake for anyone who signed in
        with Discord, so serving it would hand out the id of people who never
        linked. The internal user id is a correlation handle with no use here."""
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        headers = self._admin_headers(client, db)
        token = self._mint(client, headers, ["contributors:read"])
        body = client.get("/api/public/contributors", headers=_bearer(token)).json()
        for entries in body["periods"].values():
            for e in entries:
                assert "avatar_url" not in e
                assert "user_id" not in e
                assert "email" not in e


class TestFleetAnonTier:
    """The de-identified roster: what it drops, and that a key for it cannot
    ask for the identified one."""

    def _admin_headers(self, client, db):
        from app.models.user import User
        from tests.conftest import _auth_headers, _login_user, _register_user

        _register_user(client, "anon-admin@test.com", "Password123!", "Anon Admin")
        _login_user(client, "anon-admin@test.com", "Password123!")
        user = db.query(User).filter(User.email == "anon-admin@test.com").first()
        user.role = "admin"
        db.commit()
        _login_user(client, "anon-admin@test.com", "Password123!")
        return _auth_headers(client)

    def _mint(self, client, headers, scopes):
        r = client.post(
            "/api/auth/api-keys", json={"name": "anon-key", "scopes": scopes}, headers=headers
        )
        assert r.status_code == 200, r.text
        return r.json()["raw_token"]

    def _link_discord(self, db, email):
        """Give the machine owner a linked Discord identity, so the identified
        tier has something to serve and the anonymous one has something to drop."""
        from app.models.machine import Machine
        from app.models.user_identity import UserIdentity

        owner_id = db.query(Machine.owner_id).first()[0]
        db.add(UserIdentity(
            user_id=owner_id, provider="discord",
            provider_user_id="1234567890", provider_login="someowner",
        ))
        db.commit()

    def test_scope_is_separate_from_fleet_read_in_both_directions(
        self, client, db, machine_token
    ):
        """The whole point of a third scope: neither key can ask for the other's
        tier, so a consumer that should only see the de-identified view cannot
        hold a credential that reaches the roster."""
        headers = self._admin_headers(client, db)
        anon_only = self._mint(client, headers, ["fleet:anon"])
        full_only = self._mint(client, headers, ["fleet:read"])

        assert client.get("/api/public/fleet", headers=_bearer(anon_only)).status_code == 403
        assert client.get("/api/public/fleet/anon", headers=_bearer(full_only)).status_code == 403
        assert client.get("/api/public/fleet/anon", headers=_bearer(anon_only)).status_code == 200

    def test_drops_every_handle_back_to_a_person(self, client, db, machine_token):
        _sync(client, machine_token, [
            {"piece_uuid": "a", "local_id": 1, "seen_at": time.time() - 60,
             "classification_status": "classified", "part_id": "3001", "color_id": "5"},
        ])
        self._link_discord(db, "anon-admin@test.com")
        headers = self._admin_headers(client, db)

        full = client.get(
            "/api/public/fleet", headers=_bearer(self._mint(client, headers, ["fleet:read"]))
        ).json()
        anon = client.get(
            "/api/public/fleet/anon", headers=_bearer(self._mint(client, headers, ["fleet:anon"]))
        ).json()

        # The identified tier really does carry the things being dropped, so
        # this test fails if the roster stops serving them rather than passing
        # vacuously.
        assert full["machines"][0]["owner_discord"]["id"] == "1234567890"
        assert full["machines"][0]["name"]
        assert ":" in full["machines"][0]["last_seen_at"]  # a timestamp, with a clock in it

        row = anon["machines"][0]
        for gone in ("owner_discord", "name", "id", "last_seen_at", "last_hour_pieces"):
            assert gone not in row, f"{gone} survived into the de-identified roster"
        # And nothing anywhere in the payload spells the owner's Discord id.
        assert "1234567890" not in json.dumps(anon)

    def test_keeps_the_counts_and_a_stable_pseudonym(self, client, db, machine_token):
        _sync(client, machine_token, [
            {"piece_uuid": f"p{i}", "local_id": i + 1, "seen_at": time.time() - 60,
             "classification_status": "classified", "part_id": "3001", "color_id": "5"}
            for i in range(3)
        ])
        # Lifetime counters are served out of machine_stats_cache, which an
        # hourly worker fills and which is therefore empty in a test.
        from app.services import machine_stats

        machine_stats.refresh_cache(db)

        headers = self._admin_headers(client, db)
        token = self._mint(client, headers, ["fleet:anon"])

        first = client.get("/api/public/fleet/anon", headers=_bearer(token)).json()
        again = client.get("/api/public/fleet/anon", headers=_bearer(token)).json()

        row = first["machines"][0]
        assert row["pieces_seen"] == 3
        assert row["sorting_within_the_hour"] is True
        # A DATE, not a timestamp: no clock to plot a working day against.
        assert len(row["last_seen_date"]) == 10
        assert row["label"].startswith("m-")
        # Stable across calls, so a consumer can hold a follow-up conversation
        # about the same machine.
        assert row["label"] == again["machines"][0]["label"]

    def test_does_not_serve_the_registration_count(self, client, db, machine_token):
        """The number that counts benches which never sorted a piece. This tier's
        audience is people being told a number out loud."""
        headers = self._admin_headers(client, db)
        body = client.get(
            "/api/public/fleet/anon", headers=_bearer(self._mint(client, headers, ["fleet:anon"]))
        ).json()
        assert "registered_machine_count" not in body
        assert "active_machine_count" in body
