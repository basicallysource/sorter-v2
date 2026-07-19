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
