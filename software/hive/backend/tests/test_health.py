from fastapi.testclient import TestClient


def test_health_round_trips_the_database(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["database"] == "ok"
