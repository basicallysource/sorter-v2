"""A machine sends channel crops in batches: one upload and one stored file for
many crops, each crop's image key a byte range in that file. Reads, serving and
deletes take the range; a bad crop costs only its own picture."""

from __future__ import annotations

import io
import json

from PIL import Image

from app.models.machine_channel_crop import MachineChannelCrop
from app.services.storage_backend import (
    LocalStorageBackend,
    S3StorageBackend,
    get_backend,
    ranged_key,
    split_ranged_key,
)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _jpeg(shade: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (24, 16), (shade, shade, shade)).save(buf, format="JPEG")
    return buf.getvalue()


def _meta(local_id: int, **extra) -> dict:
    return {"local_id": local_id, "channel": 3, "ts": 1_760_000_000.0 + local_id, "track_id": 7,
            "zone_code": 2, "com_forward_to_exit_deg": 4.5, "bbox": [1, 2, 30, 40], **extra}


def _send(client, token: str, crops: list[tuple[dict, bytes | None]]):
    blob = bytearray()
    metas = []
    for meta, image in crops:
        entry = dict(meta)
        if image is not None:
            entry["offset"], entry["length"] = len(blob), len(image)
            entry["bytes"] = len(image)
            blob += image
        metas.append(entry)
    return client.post(
        "/api/machine/sync/channel-crop-batch",
        headers=_bearer(token),
        data={"metadata": json.dumps({"crops": metas})},
        files={"crops": ("crops.bin", bytes(blob), "application/octet-stream")} if blob else None,
    )


def _row(db, local_id: int) -> MachineChannelCrop:
    db.expire_all()
    return db.query(MachineChannelCrop).filter_by(local_id=local_id).one()


def test_a_batch_is_one_file_and_each_crop_reads_back(client, db, machine_token, upload_dir):
    a, b = _jpeg(40), _jpeg(200)
    r = _send(client, machine_token, [(_meta(1), a), (_meta(2), None), (_meta(3), b)])
    assert r.status_code == 200, r.text
    assert r.json() == {"max_local_id": 3, "stored": 2, "without_image": 1}

    first, second, third = _row(db, 1), _row(db, 2), _row(db, 3)
    assert get_backend().read_bytes(first.image_key) == a
    assert get_backend().read_bytes(third.image_key) == b
    assert second.image_key is None and second.evicted_locally
    assert first.track_id == 7 and first.zone_code == 2 and first.bbox_x2 == 30
    file_key = split_ranged_key(first.image_key)[0]
    assert file_key == split_ranged_key(third.image_key)[0]
    assert file_key.endswith("/channel_crops/batches/1-3.bin")

    served = get_backend().serve(third.image_key, headers={"Cache-Control": "max-age=60"})
    assert served.body == b and served.media_type == "image/jpeg"
    assert served.headers["Cache-Control"] == "max-age=60"
    state = client.get("/api/machine/sync/state", headers=_bearer(machine_token)).json()
    assert state["channel_crops"] == {"max_local_id": 3}


def test_a_bad_crop_costs_only_its_own_picture(client, db, machine_token, upload_dir):
    good = _jpeg(90)
    r = client.post(
        "/api/machine/sync/channel-crop-batch",
        headers=_bearer(machine_token),
        data={"metadata": json.dumps({"crops": [
            {**_meta(10), "offset": 0, "length": len(good)},
            {**_meta(11), "offset": len(good), "length": 5},  # not a JPEG
            {**_meta(12), "offset": 0, "length": 10_000_000},  # past the end
            {"local_id": 13, "channel": "not a number"},
        ]})},
        files={"crops": ("crops.bin", good + b"hello", "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"max_local_id": 13, "stored": 1, "without_image": 2}
    assert get_backend().read_bytes(_row(db, 10).image_key) == good
    assert _row(db, 11).image_key is None and _row(db, 12).image_key is None
    assert db.query(MachineChannelCrop).filter_by(local_id=13).count() == 0


def test_a_resend_without_pictures_keeps_the_stored_ones(client, db, machine_token, upload_dir):
    image = _jpeg(120)
    assert _send(client, machine_token, [(_meta(20), image)]).status_code == 200
    key = _row(db, 20).image_key
    assert _send(client, machine_token, [(_meta(20, sharpness=3.5), None)]).status_code == 200
    row = _row(db, 20)
    assert row.image_key == key and row.sharpness == 3.5
    assert get_backend().read_bytes(key) == image


def test_ranged_keys_on_the_local_backend(tmp_path):
    backend = LocalStorageBackend(str(tmp_path))
    backend.write_stream("m/batch.bin", io.BytesIO(b"aaaa\xff\xd8\xffbbcc"))
    key = ranged_key("m/batch.bin", 4, 5)
    assert split_ranged_key(key) == ("m/batch.bin", 4, 5)
    assert split_ranged_key("m/plain.jpg") == ("m/plain.jpg", None, None)
    assert split_ranged_key("m/odd#name.jpg") == ("m/odd#name.jpg", None, None)
    assert backend.read_bytes(key) == b"\xff\xd8\xffbb"
    assert backend.exists(key)
    backend.delete(key)
    assert (tmp_path / "m" / "batch.bin").exists()


def test_ranged_keys_on_s3_read_a_range_and_are_never_signed():
    backend = S3StorageBackend(
        bucket="bucket",
        endpoint_url="http://127.0.0.1:9",
        region="us-east-1",
        access_key_id="test",
        secret_access_key="test",
    )
    calls: list[dict] = []

    class Body:
        def read(self):
            return b"\xff\xd8\xffxy"

    class Client:
        exceptions = backend.client.exceptions

        def get_object(self, **kwargs):
            calls.append(kwargs)
            return {"Body": Body()}

        def delete_object(self, **kwargs):
            calls.append({"deleted": kwargs})

    backend.client = Client()
    key = ranged_key("m/batch.bin", 100, 5)
    assert backend.read_bytes(key) == b"\xff\xd8\xffxy"
    assert calls == [{"Bucket": "bucket", "Key": "m/batch.bin", "Range": "bytes=100-104"}]
    assert backend.presigned_get_url(key) is None
    served = backend.serve(key)
    assert served.body == b"\xff\xd8\xffxy" and served.media_type == "image/jpeg"
    backend.delete(key)
    assert not any("deleted" in c for c in calls)
