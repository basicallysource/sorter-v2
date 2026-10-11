"""The per-user "share my machines' live activity" opt-in.

Off by default; a signed-in user reads and changes it through their own profile
(`/api/auth/me`); and the fleet roster reports each machine owner's choice so a
public consumer can leave unshared machines out of a live activity listing.
"""

from __future__ import annotations

from app.config import settings
from app.models.user import User
from tests.conftest import _auth_headers, _login_user, _register_user
from tests.test_public_stats import TestStatsScopeKeys, _bearer


def _sign_in(client, email: str, name: str) -> dict[str, str]:
    _register_user(client, email, "Password123!", name)
    _login_user(client, email, "Password123!")
    return _auth_headers(client)


def _machine(client, headers, name: str) -> None:
    r = client.post("/api/machines", json={"name": name, "description": "d"}, headers=headers)
    assert r.status_code in (200, 201), r.text


class TestShareActivitySetting:
    def test_defaults_to_off(self, client, db):
        _sign_in(client, "member@test.com", "Member")
        assert client.get("/api/auth/me").json()["share_activity"] is False
        user = db.query(User).filter(User.email == "member@test.com").first()
        assert user.share_activity is False

    def test_a_user_can_turn_it_on_and_off(self, client):
        headers = _sign_in(client, "member@test.com", "Member")

        r = client.patch("/api/auth/me", json={"share_activity": True}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["share_activity"] is True
        assert client.get("/api/auth/me").json()["share_activity"] is True

        r = client.patch("/api/auth/me", json={"share_activity": False}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["share_activity"] is False
        assert client.get("/api/auth/me").json()["share_activity"] is False

    def test_other_profile_edits_leave_it_alone(self, client):
        headers = _sign_in(client, "member@test.com", "Member")
        client.patch("/api/auth/me", json={"share_activity": True}, headers=headers)

        r = client.patch("/api/auth/me", json={"display_name": "Renamed"}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["display_name"] == "Renamed"
        assert r.json()["share_activity"] is True

    def test_changing_it_needs_a_session(self, client):
        r = client.patch("/api/auth/me", json={"share_activity": True})
        assert r.status_code in (401, 403)


class TestRosterReportsTheOptIn:
    """/api/public/fleet carries each owner's choice; /fleet/anon stays as it was."""

    def _roster_as_admin(self, client, db, monkeypatch, path="/api/public/fleet"):
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "")
        stats = TestStatsScopeKeys()
        headers = stats._admin_headers(client, db)
        _machine(client, headers, "Admin Sorter")
        token = stats._mint(client, headers, ["fleet:read", "fleet:anon"])
        r = client.get(path, headers=_bearer(token))
        assert r.status_code == 200, r.text
        return headers, token, r.json()

    def test_each_row_reports_its_owners_setting(self, client, db, monkeypatch):
        sharer = _sign_in(client, "sharer@test.com", "Sharer")
        _machine(client, sharer, "Shared Sorter")
        client.patch("/api/auth/me", json={"share_activity": True}, headers=sharer)
        keeper = _sign_in(client, "keeper@test.com", "Keeper")
        _machine(client, keeper, "Private Sorter")

        _, _, body = self._roster_as_admin(client, db, monkeypatch)
        by_name = {m["name"]: m for m in body["machines"]}
        assert by_name["Shared Sorter"]["owner_shares_activity"] is True
        assert by_name["Private Sorter"]["owner_shares_activity"] is False
        assert by_name["Admin Sorter"]["owner_shares_activity"] is False

    def test_turning_it_off_again_takes_effect(self, client, db, monkeypatch):
        sharer = _sign_in(client, "sharer@test.com", "Sharer")
        _machine(client, sharer, "Shared Sorter")
        client.patch("/api/auth/me", json={"share_activity": True}, headers=sharer)
        client.patch("/api/auth/me", json={"share_activity": False}, headers=sharer)

        _, _, body = self._roster_as_admin(client, db, monkeypatch)
        mine = next(m for m in body["machines"] if m["name"] == "Shared Sorter")
        assert mine["owner_shares_activity"] is False

    def test_the_machine_listing_does_not_move_with_the_opt_in(self, client, db, monkeypatch):
        """The roster still lists every machine; the flag is for the consumer to apply."""
        sharer = _sign_in(client, "sharer@test.com", "Sharer")
        _machine(client, sharer, "Shared Sorter")
        client.patch("/api/auth/me", json={"share_activity": True}, headers=sharer)
        keeper = _sign_in(client, "keeper@test.com", "Keeper")
        _machine(client, keeper, "Private Sorter")

        _, _, body = self._roster_as_admin(client, db, monkeypatch)
        assert body["registered_machine_count"] == 3
        assert {m["name"] for m in body["machines"]} == {"Shared Sorter", "Private Sorter", "Admin Sorter"}

    def test_the_anonymous_roster_does_not_carry_it(self, client, db, monkeypatch):
        sharer = _sign_in(client, "sharer@test.com", "Sharer")
        _machine(client, sharer, "Shared Sorter")
        client.patch("/api/auth/me", json={"share_activity": True}, headers=sharer)

        _, _, body = self._roster_as_admin(client, db, monkeypatch, path="/api/public/fleet/anon")
        assert body["machines"]
        for row in body["machines"]:
            assert "owner_shares_activity" not in row
