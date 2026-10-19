"""The defaults block every sorter fetches, and an admin's overrides."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import machine_defaults


def _make_admin(db: Session) -> None:
    user = db.query(User).filter(User.email == "member@test.com").first()
    user.role = "admin"
    db.commit()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_machine_gets_the_block_and_a_304_while_it_has_it(client, machine_token):
    machine_defaults.invalidate()
    r = client.get("/api/machine/defaults", headers=_bearer(machine_token))
    assert r.status_code == 200, r.text
    block = r.json()
    assert block["defaults"]["steppers"]["chute"]["sgthrs"] == 55
    assert block["defaults"]["sharing"]["channel_crops"] is True
    assert r.headers["etag"] == f'"{block["version"]}"'
    again = client.get("/api/machine/defaults", headers={**_bearer(machine_token), "If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    beat = client.post("/api/machine/heartbeat", headers=_bearer(machine_token))
    assert beat.json()["defaults_version"] == block["version"]


def test_an_override_changes_the_block_and_its_version(client, db, machine_token, auth_headers):
    _make_admin(db)
    admin_headers = auth_headers
    machine_defaults.invalidate()
    before = client.get("/api/machine/defaults", headers=_bearer(machine_token)).json()
    r = client.put("/api/admin/machine-defaults", headers=admin_headers, json={"path": "steppers.chute.sgthrs", "value": 60})
    assert r.status_code == 200, r.text
    assert [o["path"] for o in r.json()["overrides"]] == ["steppers.chute.sgthrs"]
    after = client.get("/api/machine/defaults", headers=_bearer(machine_token)).json()
    assert after["defaults"]["steppers"]["chute"]["sgthrs"] == 60
    assert after["version"] != before["version"]
    r = client.put("/api/admin/machine-defaults", headers=admin_headers, json={"path": "steppers.chute.sgthrs", "value": None})
    assert r.json()["overrides"] == []
    assert client.get("/api/machine/defaults", headers=_bearer(machine_token)).json()["version"] == before["version"]


def test_an_override_must_name_a_default_and_keep_its_type(client, db, auth_headers):
    _make_admin(db)
    admin_headers = auth_headers
    for path, value in (("steppers.chute.nope", 1), ("steppers.chute", 1), ("steppers.chute.sgthrs", "high"), ("sharing.network", 1)):
        r = client.put("/api/admin/machine-defaults", headers=admin_headers, json={"path": path, "value": value})
        assert r.status_code == 400, (path, r.text)
    r = client.put("/api/admin/machine-defaults", headers=admin_headers, json={"path": "sample_capture.interval_s", "value": 300})
    assert r.status_code == 200
    assert r.json()["defaults"]["sample_capture"]["interval_s"] == 300.0
    client.put("/api/admin/machine-defaults", headers=admin_headers, json={"path": "sample_capture.interval_s", "value": None})


def test_only_admins_set_defaults(client, auth_headers):
    r = client.put("/api/admin/machine-defaults", headers=auth_headers, json={"path": "steppers.chute.sgthrs", "value": 60})
    assert r.status_code == 403
