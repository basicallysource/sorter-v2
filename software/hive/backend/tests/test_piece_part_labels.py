"""Human part (mold) corrections on synced machine pieces."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.piece_part_label import PiecePartLabel
from app.models.user import User
from app.routers import piece_color_labels as labeling_router
from app.routers import profiles as profiles_router
from app.services.profile_catalog import ProfileCatalogService
from tests.conftest import _auth_headers, _login_user, _register_user


def _catalog() -> ProfileCatalogService:
    service = ProfileCatalogService.__new__(ProfileCatalogService)
    service._parts_data = SimpleNamespace(
        parts={
            "3623": {
                "part_num": "3623",
                "name": "Plate 1 x 3",
                "part_cat_id": 14,
                "part_img_url": "https://img.example/3623.png",
            },
            "3069b": {
                "part_num": "3069b",
                "name": "Tile 1 x 2 with Groove",
                "part_cat_id": 19,
                "part_img_url": "https://img.example/3069b.png",
            },
            "6141": {
                "part_num": "6141",
                "name": "Plate Round 1 x 1 with Solid Stud",
                "part_cat_id": 14,
                "part_img_url": "https://img.example/6141.png",
            },
        },
        categories={14: {"id": 14, "name": "Plates"}, 19: {"id": 19, "name": "Tiles"}},
        bl_to_rb_part={"4073": "6141"},
    )
    return service


@pytest.fixture()
def catalog(monkeypatch: pytest.MonkeyPatch) -> ProfileCatalogService:
    service = _catalog()
    monkeypatch.setattr(labeling_router, "get_profile_catalog_service", lambda: service)
    monkeypatch.setattr(profiles_router, "get_profile_catalog_service", lambda: service)
    return service


def _make_piece(db: Session, machine_id: str, piece_uuid: str, part_id: str | None = "3001") -> MachinePiece:
    """A synced piece old enough to be labelable, with one crop in storage."""
    piece = MachinePiece(
        machine_id=UUID(machine_id),
        piece_uuid=piece_uuid,
        local_id=1,
        part_id=part_id,
        part_name="Brick 2 x 4" if part_id else None,
        recorded_at=datetime.now(timezone.utc) - timedelta(hours=1),
        seen_at=datetime.now(timezone.utc) - timedelta(hours=1),
        dead=False,
    )
    db.add(piece)
    db.add(
        MachinePieceImage(
            machine_id=UUID(machine_id),
            piece_uuid=piece_uuid,
            seq=0,
            local_id=1,
            image_key="crops/test.jpg",
        )
    )
    db.commit()
    return piece


def _post_label(client: TestClient, headers: dict, machine_id: str, piece_uuid: str, **kwargs):
    return client.post(
        "/api/labeling/piece-part-label",
        json={"machine_id": machine_id, "piece_uuid": piece_uuid, **kwargs},
        headers=headers,
    )


def test_submit_part_label_records_correction(client, db, test_machine, auth_headers, catalog):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-1")

    resp = _post_label(client, auth_headers, mid, "piece-1", part_num="3623")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] is True
    assert body["part"]["part_num"] == "3623"
    assert body["part"]["name"] == "Plate 1 x 3"
    assert body["part"]["category_name"] == "Plates"

    row = db.query(PiecePartLabel).filter(PiecePartLabel.piece_uuid == "piece-1").one()
    assert row.part_num == "3623"
    assert row.cant_tell is False
    # The machine's prediction is snapshotted so the label still reads as a
    # disagreement after a re-sync.
    assert row.predicted_part_num == "3001"


def test_part_label_can_fill_in_an_unidentified_piece(client, db, test_machine, auth_headers, catalog):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-unknown", part_id=None)

    resp = _post_label(client, auth_headers, mid, "piece-unknown", part_num="3069b")
    assert resp.status_code == 200, resp.text

    row = db.query(PiecePartLabel).filter(PiecePartLabel.piece_uuid == "piece-unknown").one()
    assert row.part_num == "3069b"
    assert row.predicted_part_num is None


def test_cant_tell_is_a_stored_answer(client, db, test_machine, auth_headers, catalog):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-2")

    resp = _post_label(client, auth_headers, mid, "piece-2", cant_tell=True)
    assert resp.status_code == 200, resp.text
    assert resp.json()["part"] is None

    row = db.query(PiecePartLabel).filter(PiecePartLabel.piece_uuid == "piece-2").one()
    assert row.cant_tell is True
    assert row.part_num is None


def test_bricklink_part_num_resolves_to_the_rebrickable_mold(
    client, db, test_machine, auth_headers, catalog
):
    # Brickognize predicts BrickLink ids, so confirming a machine guess submits
    # '4073' for what the catalog knows as 6141. Store the Rebrickable id.
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-bl", part_id="4073")

    resp = _post_label(client, auth_headers, mid, "piece-bl", part_num="4073")
    assert resp.status_code == 200, resp.text
    assert resp.json()["part"]["part_num"] == "6141"

    row = db.query(PiecePartLabel).filter(PiecePartLabel.piece_uuid == "piece-bl").one()
    assert row.part_num == "6141"


def test_unknown_part_is_rejected(client, db, test_machine, auth_headers, catalog):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-3")

    resp = _post_label(client, auth_headers, mid, "piece-3", part_num="not-a-real-part")
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "PART_NUM_INVALID"
    assert db.query(PiecePartLabel).count() == 0


def test_part_num_or_cant_tell_is_required(client, db, test_machine, auth_headers, catalog):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-4")

    resp = _post_label(client, auth_headers, mid, "piece-4")
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "PART_REQUIRED"


def test_resubmitting_updates_the_same_row(client, db, test_machine, auth_headers, catalog):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-5")

    first = _post_label(client, auth_headers, mid, "piece-5", part_num="3623")
    assert first.json()["created"] is True
    second = _post_label(client, auth_headers, mid, "piece-5", part_num="3069b")
    assert second.status_code == 200, second.text
    assert second.json()["created"] is False

    rows = db.query(PiecePartLabel).filter(PiecePartLabel.piece_uuid == "piece-5").all()
    assert len(rows) == 1
    assert rows[0].part_num == "3069b"


def test_two_labelers_each_get_their_own_correction(client, db, test_machine, auth_headers, catalog):
    """The whole point of a separate table: corrections are per-person, and one
    labeler's answer never overwrites another's."""
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-6")
    _post_label(client, auth_headers, mid, "piece-6", part_num="3623")

    # A second labeler, promoted to reviewer so the piece is visible to them.
    _register_user(client, "second@test.com", "Password123!", "Second Labeler")
    _login_user(client, "second@test.com", "Password123!")
    user = db.query(User).filter(User.email == "second@test.com").first()
    user.role = "reviewer"
    db.commit()
    resp = _post_label(client, _auth_headers(client), mid, "piece-6", part_num="3069b")
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] is True

    rows = db.query(PiecePartLabel).filter(PiecePartLabel.piece_uuid == "piece-6").all()
    assert len(rows) == 2
    assert {r.part_num for r in rows} == {"3623", "3069b"}


def test_piece_detail_returns_my_part_label_and_the_prediction(client, db, test_machine, auth_headers, catalog):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-7", part_id="3069b")
    _post_label(client, auth_headers, mid, "piece-7", part_num="3623")

    resp = client.get(f"/api/labeling/piece/{mid}/piece-7")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["my_part_label"]["part_num"] == "3623"
    assert body["my_part_label"]["part"]["name"] == "Plate 1 x 3"
    assert body["predicted_part"]["part_num"] == "3069b"


def test_piece_detail_predicted_part_is_null_when_unidentified(client, db, test_machine, auth_headers, catalog):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-8", part_id=None)

    resp = client.get(f"/api/labeling/piece/{mid}/piece-8")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["predicted_part"] is None
    assert body["my_part_label"] is None


def test_delete_part_label(client, db, test_machine, auth_headers, catalog):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-9")
    _post_label(client, auth_headers, mid, "piece-9", part_num="3623")

    resp = client.delete(f"/api/labeling/piece-part-label/{mid}/piece-9", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert db.query(PiecePartLabel).count() == 0

    missing = client.delete(f"/api/labeling/piece-part-label/{mid}/piece-9", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "PART_LABEL_NOT_FOUND"





def test_catalog_categories_are_served_to_non_admins(client, test_user, catalog, monkeypatch):
    monkeypatch.setattr(
        catalog, "admin_list_categories", lambda: [{"id": 14, "name": "Plates", "part_count": 142}]
    )
    resp = client.get("/api/profile-catalog/categories")
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["name"] == "Plates"
