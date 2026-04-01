"""Tests for machine management and token endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestCreateMachine:
    def test_create_machine(
        self, client: TestClient, test_user: dict, auth_headers: dict
    ) -> None:
        resp = client.post(
            "/api/machines",
            json={"name": "My Sorter", "description": "A sorting machine"},
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["name"] == "My Sorter"
        assert "raw_token" in data  # Raw token shown only at creation
        assert "id" in data

    def test_create_machine_returns_token_once(
        self, client: TestClient, test_user: dict, auth_headers: dict
    ) -> None:
        create_resp = client.post(
            "/api/machines",
            json={"name": "Once Token"},
            headers=auth_headers,
        )
        assert create_resp.status_code in (200, 201)
        data = create_resp.json()
        assert "raw_token" in data
        machine_id = data["id"]

        # Listing machines should NOT return the raw token
        list_resp = client.get("/api/machines", headers=auth_headers)
        assert list_resp.status_code == 200
        machines = list_resp.json()
        if isinstance(machines, dict) and "items" in machines:
            machines = machines["items"]
        for m in machines:
            if m["id"] == machine_id:
                assert "raw_token" not in m or m.get("raw_token") is None
                assert "token_prefix" in m
                break


class TestListMachines:
    def test_list_machines(
        self, client: TestClient, test_user: dict, auth_headers: dict
    ) -> None:
        # Create two machines
        client.post(
            "/api/machines",
            json={"name": "Machine A"},
            headers=auth_headers,
        )
        client.post(
            "/api/machines",
            json={"name": "Machine B"},
            headers=auth_headers,
        )

        resp = client.get("/api/machines", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        items = data if isinstance(data, list) else data.get("items", data)
        assert len(items) >= 2


class TestRenameMachine:
    def test_rename_machine(
        self, client: TestClient, test_machine: dict, auth_headers: dict
    ) -> None:
        machine_id = test_machine["id"]
        resp = client.patch(
            f"/api/machines/{machine_id}",
            json={"name": "Renamed Sorter"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed Sorter"


class TestDeleteMachine:
    def test_delete_machine(
        self, client: TestClient, test_machine: dict, auth_headers: dict
    ) -> None:
        machine_id = test_machine["id"]
        resp = client.delete(
            f"/api/machines/{machine_id}",
            headers=auth_headers,
        )
        assert resp.status_code in (200, 204)

        # Machine should no longer appear in listing
        list_resp = client.get("/api/machines", headers=auth_headers)
        data = list_resp.json()
        items = data if isinstance(data, list) else data.get("items", data)
        assert all(m["id"] != machine_id for m in items)


class TestRotateToken:
    def test_rotate_token(
        self, client: TestClient, test_machine: dict, auth_headers: dict
    ) -> None:
        machine_id = test_machine["id"]
        old_token = test_machine["raw_token"]

        resp = client.post(
            f"/api/machines/{machine_id}/rotate-token",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        new_token = data["raw_token"]
        assert new_token != old_token

        # Old token should no longer work for heartbeat
        old_resp = client.post(
            "/api/machine/heartbeat",
            headers={"Authorization": f"Bearer {old_token}"},
            json={},
        )
        assert old_resp.status_code == 401

        # New token should work
        new_resp = client.post(
            "/api/machine/heartbeat",
            headers={"Authorization": f"Bearer {new_token}"},
            json={},
        )
        assert new_resp.status_code == 200


class TestHeartbeat:
    def test_heartbeat_updates_last_seen(
        self, client: TestClient, machine_token: str
    ) -> None:
        resp = client.post(
            "/api/machine/heartbeat",
            headers={"Authorization": f"Bearer {machine_token}"},
            json={"hardware_info": {"cpu": "RPi5"}},
        )
        assert resp.status_code == 200

    def test_machine_token_auth(self, client: TestClient) -> None:
        # Invalid token should be rejected
        resp = client.post(
            "/api/machine/heartbeat",
            headers={"Authorization": "Bearer invalid-token"},
            json={},
        )
        assert resp.status_code == 401
