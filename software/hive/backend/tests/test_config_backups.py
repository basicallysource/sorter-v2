"""Tests for versioned machine config backups."""

from fastapi.testclient import TestClient


def _mauth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _payload(toml_text: str) -> dict:
    return {
        "content_hash": f"hash:{hash(toml_text) & 0xFFFFFFFF}",
        "payload": {"toml_text": toml_text, "local_state": {"zones": []}},
        "trigger": "config_change",
    }


class TestConfigBackups:
    def test_upload_creates_v1_then_dedups(self, client: TestClient, machine_token: str):
        body = _payload("[servo]\nbackend='waveshare'\n")
        r1 = client.post("/api/machine/config-backup", json=body, headers=_mauth(machine_token))
        assert r1.status_code == 200, r1.text
        assert r1.json()["version"] == 1
        assert r1.json()["deduped"] is False

        # Same hash → deduped, still v1
        r2 = client.post("/api/machine/config-backup", json=body, headers=_mauth(machine_token))
        assert r2.status_code == 200, r2.text
        assert r2.json()["version"] == 1
        assert r2.json()["deduped"] is True

    def test_changed_config_increments_version(self, client: TestClient, machine_token: str):
        client.post("/api/machine/config-backup", json=_payload("a"), headers=_mauth(machine_token))
        r = client.post("/api/machine/config-backup", json=_payload("b"), headers=_mauth(machine_token))
        assert r.json()["version"] == 2
        assert r.json()["deduped"] is False

    def test_machine_lists_and_fetches_own_versions(self, client: TestClient, machine_token: str):
        client.post("/api/machine/config-backup", json=_payload("a"), headers=_mauth(machine_token))
        client.post("/api/machine/config-backup", json=_payload("b"), headers=_mauth(machine_token))

        lst = client.get("/api/machine/config-backups", headers=_mauth(machine_token))
        assert lst.status_code == 200, lst.text
        versions = [row["version"] for row in lst.json()]
        assert versions == [2, 1]  # newest first
        assert "payload" not in lst.json()[0]  # summary is lightweight

        detail = client.get("/api/machine/config-backup/1", headers=_mauth(machine_token))
        assert detail.status_code == 200, detail.text
        assert detail.json()["payload"]["toml_text"] == "a"

        missing = client.get("/api/machine/config-backup/99", headers=_mauth(machine_token))
        assert missing.status_code == 404

    def test_owner_can_browse_machine_backups(
        self, client: TestClient, machine_token: str, test_machine: dict, auth_headers: dict
    ):
        client.post("/api/machine/config-backup", json=_payload("a"), headers=_mauth(machine_token))
        machine_id = test_machine["id"]

        lst = client.get(f"/api/machines/{machine_id}/config-backups", headers=auth_headers)
        assert lst.status_code == 200, lst.text
        assert lst.json()[0]["version"] == 1

        detail = client.get(f"/api/machines/{machine_id}/config-backups/1", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["payload"]["toml_text"] == "a"
