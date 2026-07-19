"""Device enrollment: silent self-enroll, re-enroll dedupe, token rotation."""

from __future__ import annotations

from app.models.device import Device

KEY = "enroll-test-key-0123456789abcdef"


def test_enroll_creates_device(client, db):
    resp = client.post("/api/devices/enroll", json={"device_key": KEY, "hardware_info": {"model": "Orange Pi 5"}})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["device_id"]
    assert body["token"]

    device = db.query(Device).filter(Device.device_key == KEY).first()
    assert device is not None
    assert str(device.id) == body["device_id"]
    assert device.hardware_info == {"model": "Orange Pi 5"}
    assert device.machine_id is None
    assert device.install_id is None


def test_reenroll_same_key_keeps_row_rotates_token(client, db):
    first = client.post("/api/devices/enroll", json={"device_key": KEY}).json()
    second = client.post("/api/devices/enroll", json={"device_key": KEY}).json()

    assert first["device_id"] == second["device_id"]
    assert first["token"] != second["token"]
    assert db.query(Device).count() == 1

    # Old token no longer works, new one does.
    old = client.post(
        "/api/devices/color-predict",
        headers={"Authorization": f"Bearer {first['token']}"},
        files=[("images", ("c.png", b"\x89PNG-not-really", "image/png"))],
    )
    assert old.status_code == 401


def test_short_device_key_rejected(client):
    resp = client.post("/api/devices/enroll", json={"device_key": "short"})
    assert resp.status_code == 422


def _ping_payload(install_id: str | None = None) -> dict:
    payload = {
        "reason": "periodic",
        "software": {"version": "sorter/canary/v0.1.0", "channel": "canary", "commit": "abc123"},
        "hardware": {"model": "Orange Pi 5", "ram_bytes": 8_000_000_000, "cpu_temp_c": 47.5},
        "config": {"machine_setup": "classification_channel"},
        "usage": {"pieces_seen": 100, "pieces_classified": 90, "best_hour_ppm": 6.5},
        "uptime": {"process_s": 12.0, "system_s": 4000.0},
        "registered": False,
    }
    if install_id is not None:
        payload["install_id"] = install_id
    return payload


def test_ping_requires_device_auth(client):
    resp = client.post("/api/devices/ping", json=_ping_payload(), headers={"Authorization": "Bearer bogus"})
    assert resp.status_code == 401


def test_ping_updates_device_telemetry(client, db, device_token):
    resp = client.post(
        "/api/devices/ping",
        json=_ping_payload(),
        headers={"Authorization": f"Bearer {device_token}"},
    )
    assert resp.status_code == 200, resp.text

    device = db.query(Device).first()
    db.refresh(device)
    assert device.ping_count == 1
    assert device.software_version == "sorter/canary/v0.1.0"
    assert device.hw_model == "Orange Pi 5"
    assert device.pieces_seen == 100
    assert device.best_hour_ppm == 6.5
    assert device.first_ping_at is not None
    assert device.last_ping_payload["reason"] == "periodic"


def test_ping_absorbs_legacy_install_row(client, db, device_token):
    from app.models.install import Install

    legacy_id = "legacy-install-0001"
    # Seed a pre-merge installs row via the legacy endpoint.
    resp = client.post("/api/installs/ping", json={"install_id": legacy_id, "reason": "boot"})
    assert resp.status_code == 200
    legacy = db.get(Install, legacy_id)
    assert legacy is not None and legacy.ping_count == 1
    legacy_first_seen = legacy.first_seen_at

    resp = client.post(
        "/api/devices/ping",
        json=_ping_payload(install_id=legacy_id),
        headers={"Authorization": f"Bearer {device_token}"},
    )
    assert resp.status_code == 200, resp.text

    assert db.get(Install, legacy_id) is None
    device = db.query(Device).first()
    db.refresh(device)
    assert device.install_id == legacy_id
    assert device.ping_count == 2  # legacy 1 + this ping
    assert device.first_ping_at == legacy_first_seen


def test_forget_wipes_device_telemetry_but_not_identity(client, db, device_token):
    install_id = "forget-me-0001"
    resp = client.post(
        "/api/devices/ping",
        json=_ping_payload(install_id=install_id),
        headers={"Authorization": f"Bearer {device_token}"},
    )
    assert resp.status_code == 200

    resp = client.post("/api/installs/forget", json={"install_id": install_id})
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    device = db.query(Device).first()
    db.refresh(device)
    assert device.install_id is None
    assert device.ping_count == 0
    assert device.software_version is None
    assert device.last_ping_payload is None
    # Service identity survives: enrollment + token still valid.
    assert device.token_hash
    assert device.is_active
    resp = client.post(
        "/api/devices/ping",
        json=_ping_payload(),
        headers={"Authorization": f"Bearer {device_token}"},
    )
    assert resp.status_code == 200
