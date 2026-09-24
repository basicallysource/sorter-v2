from fastapi.testclient import TestClient

from app.routers import machine_lookup

RID = "abcdefghijklmnop0123"
BASE = f"/api/machine-ip-lookup/{RID}"


def _post_key(client: TestClient, key: str) -> None:
    assert client.post(f"{BASE}/pubkey", json={"pubkey": key}).status_code == 200


def _publish(client: TestClient, ciphertext: str) -> None:
    assert client.post(BASE, json={"ciphertext": ciphertext}).status_code == 200


def test_the_sorter_gets_the_key_and_the_page_gets_the_address(client: TestClient) -> None:
    machine_lookup._store.clear()
    assert client.get(f"{BASE}/pubkey").json() == {"pubkey": None}
    _post_key(client, "key-1")
    assert client.get(f"{BASE}/pubkey").json() == {"pubkey": "key-1"}
    assert client.get(BASE).json() == {"ready": False, "ciphertext": None}
    _publish(client, "sealed-1")
    assert client.get(BASE).json() == {"ready": True, "ciphertext": "sealed-1"}


def test_a_reloaded_page_drops_the_address_sealed_to_its_old_key(client: TestClient) -> None:
    machine_lookup._store.clear()
    _post_key(client, "key-1")
    _publish(client, "sealed-1")
    _post_key(client, "key-1")  # the same page re-posting keeps it
    assert client.get(BASE).json()["ready"] is True
    _post_key(client, "key-2")  # a reload makes a new key pair
    assert client.get(BASE).json() == {"ready": False, "ciphertext": None}


def test_re_posting_the_key_keeps_the_entry_alive(client: TestClient, monkeypatch) -> None:
    machine_lookup._store.clear()
    clock = [1000.0]
    monkeypatch.setattr(machine_lookup, "_now", lambda: clock[0])
    _post_key(client, "key-1")
    clock[0] += machine_lookup.TTL_SECONDS - 1
    _post_key(client, "key-1")
    clock[0] += machine_lookup.TTL_SECONDS - 1
    assert client.get(f"{BASE}/pubkey").json() == {"pubkey": "key-1"}
    clock[0] += 2
    assert client.get(f"{BASE}/pubkey").json() == {"pubkey": None}
