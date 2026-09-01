"""Tests for per-sample dataset provenance on detection models."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.machine import Machine
from app.models.sample import Sample
from app.models.upload_session import UploadSession
from app.models.user import User
from tests.conftest import _auth_headers, _login_user, _register_user


def _promote(db: Session, email: str, role: str) -> None:
    user = db.query(User).filter(User.email == email).first()
    assert user is not None
    user.role = role
    db.commit()


@pytest.fixture()
def admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    _register_user(client, "admin@test.com", "Password123!", "Admin")
    _login_user(client, "admin@test.com", "Password123!")
    _promote(db, "admin@test.com", "admin")
    return _auth_headers(client)


def _make_machine_with_samples(db: Session, name: str, count: int) -> list[str]:
    owner = db.query(User).first()
    assert owner is not None
    token = uuid.uuid4().hex
    machine = Machine(
        owner_id=owner.id,
        token_hash=token,
        token_prefix=token[:8],
        name=name,
    )
    db.add(machine)
    db.flush()
    session = UploadSession(
        machine_id=machine.id,
        source_session_id=f"session-{machine.token_prefix}",
        name=f"Session {name}",
    )
    db.add(session)
    db.flush()
    ids = []
    for i in range(count):
        sample = Sample(
            machine_id=machine.id,
            upload_session_id=session.id,
            local_sample_id=f"{machine.token_prefix}-{i}",
            image_path=f"samples/{machine.token_prefix}-{i}.jpg",
        )
        db.add(sample)
        db.flush()
        ids.append(str(sample.id))
    db.commit()
    return ids


def _create_model(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(
        "/api/models",
        json={"slug": "prov-test", "name": "Prov Test", "model_family": "yolo"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


class TestAttachDatasetSamples:
    def test_requires_admin(
        self, client: TestClient, db: Session, admin_headers: dict[str, str]
    ) -> None:
        model_id = _create_model(client, admin_headers)
        ids = _make_machine_with_samples(db, "Rig A", 1)
        # Sessions are cookie-based on the shared client — switch to a member.
        _register_user(client, "member@test.com", "Password123!", "Member")
        _login_user(client, "member@test.com", "Password123!")
        resp = client.post(
            f"/api/models/{model_id}/dataset-samples",
            json={"samples": [{"sample_id": ids[0], "split": "train"}]},
            headers=_auth_headers(client),
        )
        assert resp.status_code == 403

    def test_attach_idempotent_and_skips_unknown(
        self, client: TestClient, db: Session, admin_headers: dict[str, str]
    ) -> None:
        model_id = _create_model(client, admin_headers)
        ids = _make_machine_with_samples(db, "Rig A", 3)
        body = {
            "samples": [{"sample_id": sid, "split": "train"} for sid in ids]
            + [{"sample_id": str(uuid.uuid4()), "split": "val"}]
        }
        r1 = client.post(f"/api/models/{model_id}/dataset-samples", json=body, headers=admin_headers)
        assert r1.status_code == 200, r1.text
        assert r1.json() == {"attached": 3, "skipped_unknown": 1, "total_recorded": 3}

        # Retrying the same chunk must not duplicate.
        r2 = client.post(f"/api/models/{model_id}/dataset-samples", json=body, headers=admin_headers)
        assert r2.status_code == 200
        assert r2.json() == {"attached": 0, "skipped_unknown": 1, "total_recorded": 3}

    def test_replace_drops_previous(
        self, client: TestClient, db: Session, admin_headers: dict[str, str]
    ) -> None:
        model_id = _create_model(client, admin_headers)
        old = _make_machine_with_samples(db, "Rig A", 2)
        new = _make_machine_with_samples(db, "Rig B", 1)
        client.post(
            f"/api/models/{model_id}/dataset-samples",
            json={"samples": [{"sample_id": sid, "split": "train"} for sid in old]},
            headers=admin_headers,
        )
        resp = client.post(
            f"/api/models/{model_id}/dataset-samples",
            json={"samples": [{"sample_id": new[0], "split": "val"}], "replace": True},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["total_recorded"] == 1

    def test_rejects_bad_split(
        self, client: TestClient, db: Session, admin_headers: dict[str, str]
    ) -> None:
        model_id = _create_model(client, admin_headers)
        ids = _make_machine_with_samples(db, "Rig A", 1)
        resp = client.post(
            f"/api/models/{model_id}/dataset-samples",
            json={"samples": [{"sample_id": ids[0], "split": "test"}]},
            headers=admin_headers,
        )
        assert resp.status_code == 422


class TestDatasetMachines:
    def test_aggregates_by_machine(
        self, client: TestClient, db: Session, admin_headers: dict[str, str]
    ) -> None:
        model_id = _create_model(client, admin_headers)
        rig_a = _make_machine_with_samples(db, "Rig A", 3)
        rig_b = _make_machine_with_samples(db, "Rig B", 1)
        samples = [{"sample_id": sid, "split": "train"} for sid in rig_a[:2]]
        samples += [{"sample_id": rig_a[2], "split": "val"}]
        samples += [{"sample_id": rig_b[0], "split": "train"}]
        client.post(
            f"/api/models/{model_id}/dataset-samples",
            json={"samples": samples},
            headers=admin_headers,
        )

        resp = client.get(f"/api/models/{model_id}/dataset-machines", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total_recorded"] == 4
        assert [m["machine_name"] for m in data["machines"]] == ["Rig A", "Rig B"]
        a, b = data["machines"]
        assert (a["train_samples"], a["val_samples"], a["total"]) == (2, 1, 3)
        assert (b["train_samples"], b["val_samples"], b["total"]) == (1, 0, 1)
        assert a["share"] == pytest.approx(0.75)

    def test_empty_for_unrecorded_model(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        model_id = _create_model(client, admin_headers)
        resp = client.get(f"/api/models/{model_id}/dataset-machines", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == {"machines": [], "total_recorded": 0}
