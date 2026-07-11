"""Machine -> Hive piece sync ingest + admin fleet stats (sqlite dialect path)."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.user import User
from tests.conftest import make_test_image


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_sync_state_starts_empty(client, machine_token):
    resp = client.get("/api/machine/sync/state", headers=_bearer(machine_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "piece_records": {"max_local_id": 0},
        "piece_images": {"max_local_id": 0},
    }


def test_piece_records_upsert_is_idempotent(client, machine_token):
    base = 1_760_000_000.0
    records = [
        {"piece_uuid": "p1", "local_id": 10, "seen_at": base, "recorded_at": base + 1,
         "classification_status": "classified", "part_id": "3001", "color_id": "5",
         "bin_x": 1, "bin_y": 0, "bin_z": 0},
        {"piece_uuid": "p2", "local_id": 11, "seen_at": base + 5, "recorded_at": base + 6,
         "classification_status": "classified", "part_id": "3002", "color_id": "5",
         "bin_x": 1, "bin_y": 0, "bin_z": 0},
    ]
    r1 = client.post("/api/machine/sync/piece-records", headers=_bearer(machine_token), json={"records": records})
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"max_local_id": 11, "upserted": 2}

    # Re-send the same batch: idempotent, watermark unchanged, no duplicate rows.
    r2 = client.post("/api/machine/sync/piece-records", headers=_bearer(machine_token), json={"records": records})
    assert r2.json()["max_local_id"] == 11

    state = client.get("/api/machine/sync/state", headers=_bearer(machine_token)).json()
    assert state["piece_records"]["max_local_id"] == 11


def test_piece_records_update_on_conflict(client, machine_token):
    base = 1_760_000_000.0
    client.post("/api/machine/sync/piece-records", headers=_bearer(machine_token),
                json={"records": [{"piece_uuid": "p1", "local_id": 1, "classification_status": "unknown"}]})
    # Same natural key, changed status -> upsert updates in place.
    client.post("/api/machine/sync/piece-records", headers=_bearer(machine_token),
                json={"records": [{"piece_uuid": "p1", "local_id": 1, "classification_status": "classified",
                                   "part_id": "3001", "seen_at": base, "bin_x": 2, "bin_y": 0, "bin_z": 0}]})
    from app.models.machine_piece import MachinePiece
    from tests.conftest import TestingSessionLocal
    s: Session = TestingSessionLocal()
    rows = s.query(MachinePiece).filter(MachinePiece.piece_uuid == "p1").all()
    s.close()
    assert len(rows) == 1
    assert rows[0].classification_status == "classified"
    assert rows[0].part_id == "3001"


def test_piece_image_with_and_without_file(client, machine_token, upload_dir):
    img = make_test_image(fmt="jpeg")
    meta = {"piece_uuid": "p1", "seq": 0, "local_id": 100, "source": "c4_burst", "channel": 4}
    r = client.post(
        "/api/machine/sync/piece-image",
        headers=_bearer(machine_token),
        data={"metadata": json.dumps(meta)},
        files={"image": ("crop.jpg", img, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"max_local_id": 100, "image_stored": True}

    # Metadata-only (evicted locally): no file, still recorded.
    meta2 = {"piece_uuid": "p2", "seq": 0, "local_id": 101, "source": "c2_match"}
    r2 = client.post("/api/machine/sync/piece-image", headers=_bearer(machine_token),
                     data={"metadata": json.dumps(meta2)})
    assert r2.status_code == 200, r2.text
    assert r2.json()["image_stored"] is False

    from app.models.machine_piece_image import MachinePieceImage
    from tests.conftest import TestingSessionLocal
    s: Session = TestingSessionLocal()
    imgs = {i.piece_uuid: i for i in s.query(MachinePieceImage).all()}
    s.close()
    assert imgs["p1"].image_key and imgs["p1"].evicted_locally is False
    assert imgs["p2"].image_key is None and imgs["p2"].evicted_locally is True


def test_sync_requires_machine_token(client):
    assert client.get("/api/machine/sync/state").status_code == 422  # missing Authorization
    assert client.get("/api/machine/sync/state", headers=_bearer("bogus")).status_code == 401


def test_admin_fleet_endpoints(client, db, machine_token, test_machine):
    base = 1_760_000_000.0
    records = [
        {"piece_uuid": "a", "local_id": 1, "seen_at": base, "classification_status": "classified",
         "part_id": "3001", "color_id": "5", "bin_x": 1, "bin_y": 0, "bin_z": 0},
        {"piece_uuid": "b", "local_id": 2, "seen_at": base + 5, "classification_status": "classified",
         "part_id": "3002", "color_id": "5", "bin_x": 1, "bin_y": 0, "bin_z": 0},
        {"piece_uuid": "c", "local_id": 3, "seen_at": base + 999, "classification_status": "unknown"},
    ]
    client.post("/api/machine/sync/piece-records", headers=_bearer(machine_token), json={"records": records})

    # Non-admin (the member test_user) is forbidden.
    assert client.get("/api/admin/machines").status_code == 403

    # Promote to admin. The stats endpoint computes the cache on first read
    # (cold-start fallback), so no manual cache priming is needed.
    user = db.query(User).filter(User.email == "member@test.com").first()
    user.role = "admin"
    db.commit()

    machines = client.get("/api/admin/machines").json()
    assert any(m["id"] == test_machine["id"] and m["owner_email"] == "member@test.com" for m in machines)

    stats = client.get("/api/admin/machines/stats").json()
    st = stats[test_machine["id"]]
    assert st["pieces_seen"] == 3
    assert st["distributed"] == 2
    assert st["classified"] == 2
    assert st["unique_parts"] == 2
    assert st["unique_colors"] == 1
    # Only the 5s gap counts as active (999s gap is idle) -> ppm = 2*60/5 = 24.
    assert abs(st["active_seconds"] - 5.0) < 0.01
    assert abs(st["overall_ppm"] - 24.0) < 0.01
