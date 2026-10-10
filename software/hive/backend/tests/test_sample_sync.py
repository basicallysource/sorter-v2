"""Training samples sent through /api/machine/sync/sample, and the per-machine
rate limit on the routes machines upload to."""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.models.sample import Sample
from app.models.sample_channel_geometry import SampleChannelGeometry
from app.models.upload_session import UploadSession
from app.rate_limiting import machine_limiter, machine_rate_limit_key
from tests.conftest import TestingSessionLocal, make_test_image


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _jpeg(width: int = 64, height: int = 48) -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (160, 160, 160)).save(buf, format="JPEG")
    buf.seek(0)
    return buf


GEOMETRY = {
    "source_role": "c_channel_2",
    "frame_width": 64,
    "frame_height": 48,
    "polygon": [[2, 2], [60, 2], [60, 44], [2, 44]],
    "center": [32, 24],
    "inner_radius": 5.0,
    "outer_radius": 20.0,
    "arc_zones": [
        {"zone_type": "drop", "start_outer_angle": 10.0, "end_outer_angle": 40.0,
         "start_inner_angle": 12.0, "end_inner_angle": 38.0},
    ],
}


def _meta(local_id: int = 7, local_sample_id: str = "s-0001", **overrides) -> dict:
    meta = {
        "local_id": local_id,
        "source_session_id": "sess-a",
        "local_sample_id": local_sample_id,
        "source_role": "c_channel_2",
        "captured_at": 1_760_000_000.5,
        "capture_reason": "interval",
        "detection_algorithm": "gemini_sam",
        "detection_bboxes": [[4, 4, 20, 20]],
        "detection_count": 1,
        "detection_score": 0.9,
        "channel_geometry": GEOMETRY,
        "camera": {"exposure_us": 8000, "gain": 1.5},
        "lamp": {"on": True, "level": 0.8},
        "software": {"sorter": "1.2.3"},
        "extra_metadata": {"run_id": "run-1", "camera": {"model": "imx477"}},
    }
    meta.update(overrides)
    return meta


def _send(client: TestClient, token: str, meta: dict, image=None, filename: str = "frame.jpg"):
    return client.post(
        "/api/machine/sync/sample",
        headers=_bearer(token),
        data={"metadata": json.dumps(meta)},
        files={"image": (filename, image if image is not None else _jpeg(), "image/jpeg")},
    )


def test_sample_is_stored_as_a_full_frame_with_geometry_and_metadata(client, machine_token, upload_dir):
    r = _send(client, machine_token, _meta())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["max_local_id"] == 7
    assert body["created"] is True

    s: Session = TestingSessionLocal()
    try:
        sample = s.query(Sample).one()
        assert str(sample.id) == body["sample_id"]
        assert sample.local_sample_id == "s-0001"
        assert sample.source_role == "c_channel_2"
        assert sample.capture_reason == "interval"
        assert sample.captured_at is not None
        assert sample.detection_count == 1
        # The one image is the full frame.
        assert sample.image_path.endswith(".jpg")
        assert sample.full_frame_path == sample.image_path
        assert (sample.image_width, sample.image_height) == (64, 48)
        assert sample.phash is not None
        assert sample.sample_payload["assets"]["img_primary"]["kind"] == "full_frame"
        assert sample.sample_payload["assets"]["img_full_frame"]["storage_path"] == sample.image_path
        # camera / lamp / software land under their own keys; a camera dict
        # already in extra_metadata is merged, not replaced.
        assert sample.extra_metadata["camera"] == {"model": "imx477", "exposure_us": 8000, "gain": 1.5}
        assert sample.extra_metadata["lamp"] == {"on": True, "level": 0.8}
        assert sample.extra_metadata["software"] == {"sorter": "1.2.3"}
        assert sample.extra_metadata["run_id"] == "run-1"

        geom = s.query(SampleChannelGeometry).one()
        assert geom.sample_id == sample.id
        assert geom.polygon_x == [2.0, 60.0, 60.0, 2.0]
        assert geom.outer_radius == 20.0
        assert geom.drop_start_outer_angle == 10.0

        session = s.query(UploadSession).one()
        assert session.source_session_id == "sess-a"
        assert session.sample_count == 1
        assert session.last_upload_at is not None
    finally:
        s.close()

    # The review UI sees a full frame it can cut the channel crop out of.
    detail = client.get(f"/api/samples/{body['sample_id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["has_full_frame"] is True
    assert detail.json()["has_channel_geometry"] is True


def test_sample_resend_is_idempotent_and_advances_the_watermark(client, machine_token, upload_dir):
    first = _send(client, machine_token, _meta(local_id=7))
    assert first.status_code == 200, first.text

    again = _send(client, machine_token, _meta(local_id=7))
    assert again.status_code == 200, again.text
    assert again.json() == {"max_local_id": 7, "sample_id": first.json()["sample_id"], "created": False}

    # The machine may re-send a stored sample under a newer local id (after
    # losing its own record of the ack): no duplicate, watermark still moves.
    later = _send(client, machine_token, _meta(local_id=9))
    assert later.status_code == 200, later.text
    assert later.json()["created"] is False
    assert later.json()["max_local_id"] == 9

    s: Session = TestingSessionLocal()
    try:
        assert s.query(Sample).count() == 1
        assert s.query(UploadSession).one().sample_count == 1
    finally:
        s.close()

    state = client.get("/api/machine/sync/state", headers=_bearer(machine_token)).json()
    assert state["samples"] == {"max_local_id": 9}


def test_sample_rejects_non_jpeg_and_bad_metadata(client, machine_token, upload_dir):
    png = _send(client, machine_token, _meta(), image=make_test_image(fmt="png"), filename="frame.png")
    assert png.status_code == 400
    assert png.json()["code"] == "INVALID_IMAGE_FORMAT"

    climbing = _send(client, machine_token, _meta(local_sample_id="../escape"))
    assert climbing.status_code == 400
    assert climbing.json()["code"] == "INVALID_METADATA"

    missing_role = _meta()
    del missing_role["source_role"]
    assert _send(client, machine_token, missing_role).status_code == 400

    s: Session = TestingSessionLocal()
    try:
        assert s.query(Sample).count() == 0
        assert s.query(UploadSession).count() == 0
    finally:
        s.close()
    state = client.get("/api/machine/sync/state", headers=_bearer(machine_token)).json()
    assert state["samples"] == {"max_local_id": 0}


def test_old_upload_route_counts_each_sample_once(client, machine_token, upload_dir):
    def upload(sample_id: str):
        return client.post(
            "/api/machine/upload",
            headers=_bearer(machine_token),
            data={"metadata": json.dumps({"source_session_id": "sess-old", "local_sample_id": sample_id})},
            files={"image": ("test.png", make_test_image(), "image/png")},
        )

    assert upload("one").status_code == 200
    assert upload("two").status_code == 200
    assert upload("two").status_code == 200  # re-send

    s: Session = TestingSessionLocal()
    try:
        session = s.query(UploadSession).filter_by(source_session_id="sess-old").one()
        assert session.sample_count == 2
        assert session.last_upload_at is not None
    finally:
        s.close()


def _request(headers: dict[str, str], client_host: str = "203.0.113.5") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (client_host, 1234), "path": "/", "method": "POST"})


def test_rate_limit_key_is_the_machine_token_not_the_address():
    a = machine_rate_limit_key(_request(_bearer("token-a")))
    b = machine_rate_limit_key(_request(_bearer("token-b")))
    assert a != b
    assert a == machine_rate_limit_key(_request(_bearer("token-a"), client_host="198.51.100.9"))
    assert "token-a" not in a  # only a hash is kept
    assert machine_rate_limit_key(_request({})) == "203.0.113.5"


def test_machines_behind_one_address_do_not_share_a_bucket(client, machine_token, auth_headers, upload_dir):
    other = client.post("/api/machines", json={"name": "Second Sorter"}, headers=auth_headers)
    assert other.status_code in (200, 201), other.text
    other_token = other.json()["raw_token"]

    def send_bad(token: str):
        # Bad metadata is refused after the limiter has counted the request,
        # which keeps this test from storing 120 samples.
        return client.post(
            "/api/machine/sync/sample",
            headers=_bearer(token),
            data={"metadata": "{"},
            files={"image": ("frame.jpg", _jpeg(8, 8), "image/jpeg")},
        )

    machine_limiter.reset()
    machine_limiter.enabled = True
    try:
        for _ in range(120):
            assert send_bad(machine_token).status_code == 400
        limited = send_bad(machine_token)
        assert limited.status_code == 429
        assert 1 <= int(limited.headers["Retry-After"]) <= 60

        # Same test client address, different machine: its own bucket.
        assert send_bad(other_token).status_code == 400
    finally:
        machine_limiter.enabled = False
        machine_limiter.reset()
