"""Per-image, per-labeler crop quality flags: a high-quality star plus
"not good enough for classification" reasons, on piece crops and channel crops."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.image_quality_label import ImageQualityLabel
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.user import User
from tests.conftest import _auth_headers, _login_user, _register_user


def _make_piece(db: Session, machine_id: str, piece_uuid: str, seq: int = 0) -> None:
    db.add(
        MachinePiece(
            machine_id=UUID(machine_id),
            piece_uuid=piece_uuid,
            local_id=1,
            part_id="3001",
            part_name="Brick 2 x 4",
            recorded_at=datetime.now(timezone.utc) - timedelta(hours=1),
            seen_at=datetime.now(timezone.utc) - timedelta(hours=1),
            dead=False,
        )
    )
    db.add(
        MachinePieceImage(
            machine_id=UUID(machine_id),
            piece_uuid=piece_uuid,
            seq=seq,
            local_id=1,
            image_key="crops/test.jpg",
        )
    )
    db.commit()


def _make_crop(db: Session, machine_id: str, local_id: int) -> None:
    db.add(
        MachineChannelCrop(
            machine_id=UUID(machine_id),
            local_id=local_id,
            channel=3,
            image_key="crops/chan.jpg",
        )
    )
    db.commit()


def _post_quality(client: TestClient, headers: dict, machine_id: str, **kwargs):
    return client.post(
        "/api/labeling/image-quality",
        json={"machine_id": machine_id, **kwargs},
        headers=headers,
    )


def test_star_a_piece_image_and_reload(client, db, test_machine, auth_headers):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-1")

    resp = _post_quality(
        client, auth_headers, mid, crop_kind="piece_image", piece_uuid="piece-1", seq=0, high_quality=True
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] is True

    row = db.query(ImageQualityLabel).one()
    assert row.crop_kind == "piece_image"
    assert row.seq == 0
    assert row.high_quality is True
    assert row.crop_local_id is None

    # piece_detail echoes the per-image flags back onto each crop.
    detail = client.get(f"/api/labeling/piece/{mid}/piece-1")
    assert detail.status_code == 200, detail.text
    img = detail.json()["images"][0]
    assert img["high_quality"] is True
    assert img["motion_blur"] is False


def test_reason_flags_and_all_false_deletes_the_row(client, db, test_machine, auth_headers):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-2")

    r1 = _post_quality(
        client,
        auth_headers,
        mid,
        crop_kind="piece_image",
        piece_uuid="piece-2",
        seq=0,
        motion_blur=True,
        low_resolution=True,
    )
    assert r1.status_code == 200, r1.text
    row = db.query(ImageQualityLabel).one()
    assert row.motion_blur is True
    assert row.low_resolution is True
    assert row.high_quality is False

    # Clearing every flag deletes the row — an unmarked crop leaves nothing behind.
    r2 = _post_quality(client, auth_headers, mid, crop_kind="piece_image", piece_uuid="piece-2", seq=0)
    assert r2.status_code == 200, r2.text
    assert r2.json()["deleted"] is True
    assert db.query(ImageQualityLabel).count() == 0


def test_resubmitting_updates_the_one_row(client, db, test_machine, auth_headers):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-3")

    _post_quality(
        client, auth_headers, mid, crop_kind="piece_image", piece_uuid="piece-3", seq=0, high_quality=True
    )
    r = _post_quality(
        client, auth_headers, mid, crop_kind="piece_image", piece_uuid="piece-3", seq=0, motion_blur=True
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] is False

    rows = db.query(ImageQualityLabel).all()
    assert len(rows) == 1
    assert rows[0].high_quality is False
    assert rows[0].motion_blur is True


def test_channel_crop_round_trip(client, db, test_machine, auth_headers):
    mid = test_machine["id"]
    _make_crop(db, mid, 4242)

    r = _post_quality(
        client, auth_headers, mid, crop_kind="channel_crop", crop_local_id=4242, no_piece_in_frame=True
    )
    assert r.status_code == 200, r.text
    row = db.query(ImageQualityLabel).one()
    assert row.crop_kind == "channel_crop"
    assert row.crop_local_id == 4242
    assert row.piece_uuid is None
    assert row.seq is None
    assert row.no_piece_in_frame is True


def test_two_labelers_each_get_their_own_row(client, db, test_machine, auth_headers):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-5")
    _post_quality(
        client, auth_headers, mid, crop_kind="piece_image", piece_uuid="piece-5", seq=0, high_quality=True
    )

    # A second labeler, promoted to reviewer so the piece is visible to them.
    _register_user(client, "second@test.com", "Password123!", "Second Labeler")
    _login_user(client, "second@test.com", "Password123!")
    user = db.query(User).filter(User.email == "second@test.com").first()
    user.role = "reviewer"
    db.commit()

    r = _post_quality(
        client,
        _auth_headers(client),
        mid,
        crop_kind="piece_image",
        piece_uuid="piece-5",
        seq=0,
        motion_blur=True,
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True
    assert db.query(ImageQualityLabel).count() == 2


def test_missing_image_key_is_rejected(client, db, test_machine, auth_headers):
    mid = test_machine["id"]
    _make_piece(db, mid, "piece-6")

    # piece_image without seq → no image identity.
    r = _post_quality(
        client, auth_headers, mid, crop_kind="piece_image", piece_uuid="piece-6", high_quality=True
    )
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "IMAGE_KEY_INVALID"
    assert db.query(ImageQualityLabel).count() == 0


def test_unknown_crop_kind_is_rejected(client, test_machine, auth_headers):
    mid = test_machine["id"]
    r = _post_quality(client, auth_headers, mid, crop_kind="whatever", high_quality=True)
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "CROP_KIND_INVALID"


def test_unknown_piece_is_not_found(client, test_machine, auth_headers):
    mid = test_machine["id"]
    r = _post_quality(
        client, auth_headers, mid, crop_kind="piece_image", piece_uuid="ghost", seq=0, high_quality=True
    )
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "PIECE_NOT_FOUND"
