"""Machine ingest stays cheap: no transaction is open while a file goes to
storage, machines.last_seen_at is written at most once a minute per machine,
a crop is three statements, a small file goes to S3 in one PUT, and the
answers machines read are exactly what they were."""

from __future__ import annotations

import gzip
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import event
from sqlalchemy.engine.interfaces import CacheStats

from app.database import SessionLocal
from app.models.machine import Machine
from app.routers import machine_sync, upload
from app.services import machine_presence
from app.services.storage_backend import S3StorageBackend
from tests.conftest import engine, make_test_image


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _jpeg() -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (160, 160, 160)).save(buf, format="JPEG")
    buf.seek(0)
    return buf


def _crop(client, token: str, local_id: int, image: bool = True):
    return client.post(
        "/api/machine/sync/channel-crop",
        headers=_bearer(token),
        data={"metadata": json.dumps({"local_id": local_id, "channel": 2, "ts": 1_760_000_000.0, "bbox": [1, 2, 3, 4], "bytes": 10})},
        files={"image": ("c.png", make_test_image(), "image/png")} if image else None,
    )


class Statements:
    """The SQL the test database runs inside the block, and whether each was
    compiled again or came from SQLAlchemy's statement cache."""

    def __init__(self) -> None:
        self.sql: list[str] = []
        self.cached: list[bool] = []

    def __enter__(self) -> "Statements":
        event.listen(engine, "before_cursor_execute", self._note)
        return self

    def __exit__(self, *exc) -> None:
        event.remove(engine, "before_cursor_execute", self._note)

    def _note(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.sql.append(" ".join(statement.replace('"', "").split()))
        self.cached.append(getattr(context, "cache_hit", None) is CacheStats.CACHE_HIT)

    def count(self, prefix: str) -> int:
        return sum(1 for s in self.sql if s.upper().startswith(prefix.upper()))


@pytest.fixture()
def clock(monkeypatch) -> list[float]:
    now = [1000.0]
    monkeypatch.setattr(machine_presence, "_monotonic", lambda: now[0])
    return now


def test_crop_answers_are_what_machines_read(client, machine_token, upload_dir):
    assert _crop(client, machine_token, 10).json() == {"max_local_id": 10, "image_stored": True}
    # A crop that arrives late does not move the watermark back.
    assert _crop(client, machine_token, 7).json() == {"max_local_id": 10, "image_stored": True}
    assert _crop(client, machine_token, 12, image=False).json() == {"max_local_id": 12, "image_stored": False}
    state = client.get("/api/machine/sync/state", headers=_bearer(machine_token)).json()
    assert state["channel_crops"] == {"max_local_id": 12}


def test_no_transaction_is_open_while_a_file_goes_to_storage(client, db, machine_token, upload_dir, monkeypatch):
    open_during_write: list[bool] = []

    def watched(save):
        def wrapper(*args, **kwargs):
            open_during_write.append(db.in_transaction())
            return save(*args, **kwargs)

        return wrapper

    for module, name in (
        (machine_sync, "save_channel_crop_file"),
        (machine_sync, "save_piece_image_file"),
        (machine_sync, "save_control_data_file"),
        (machine_sync, "save_sample_frame_file"),
        (upload, "save_upload_file"),
    ):
        monkeypatch.setattr(module, name, watched(getattr(module, name)))

    headers = _bearer(machine_token)
    assert _crop(client, machine_token, 1).status_code == 200
    r = client.post(
        "/api/machine/sync/piece-image",
        headers=headers,
        data={"metadata": json.dumps({"piece_uuid": "p1", "seq": 0, "local_id": 1, "source": "detection"})},
        files={"image": ("p.png", make_test_image(), "image/png")},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/machine/sync/control-data-segment",
        headers=headers,
        data={"metadata": json.dumps({"local_id": 1})},
        files={"data": ("s.jsonl.gz", gzip.compress(b"{}\n"), "application/gzip")},
    )
    assert r.status_code == 200, r.text
    frame_meta = {
        "local_id": 1,
        "source_session_id": "sess-0",
        "local_sample_id": "frame-1",
        "source_role": "c_channel_2",
        "captured_at": 1_760_000_000.0,
        "capture_reason": "interval",
    }
    r = client.post(
        "/api/machine/sync/sample",
        headers=headers,
        data={"metadata": json.dumps(frame_meta)},
        files={"image": ("f.jpg", _jpeg(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    meta = {"source_session_id": "sess-1", "local_sample_id": "sample-1", "source_role": "classification"}
    r = client.post(
        "/api/machine/upload",
        headers=headers,
        data={"metadata": json.dumps(meta)},
        files={"image": ("s.png", make_test_image(), "image/png"), "full_frame": ("f.png", make_test_image(), "image/png")},
    )
    assert r.status_code in (200, 201), r.text
    r = client.patch(
        "/api/machine/upload/sess-1/sample-1",
        headers=headers,
        data={"metadata": json.dumps(meta)},
        files={"image": ("s2.png", make_test_image(), "image/png"), "overlay": ("o.png", make_test_image(), "image/png")},
    )
    assert r.status_code == 200, r.text

    assert open_during_write == [False] * 8


def test_last_seen_is_written_at_most_once_a_minute(client, db, machine_token, upload_dir, clock):
    with Statements() as sql:
        for local_id in range(1, 6):
            assert _crop(client, machine_token, local_id).status_code == 200
    # The first crop: the machine had never been seen.
    assert sql.count("UPDATE machines") == 1

    machine = db.query(Machine).filter(Machine.last_seen_at.isnot(None)).one()
    machine.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=61)
    db.commit()
    clock[0] += 61
    with Statements() as sql:
        for local_id in range(6, 9):
            assert _crop(client, machine_token, local_id).status_code == 200
    assert sql.count("UPDATE machines") == 1


def test_requests_that_load_the_same_old_value_write_it_once(clock):
    now = datetime.now(timezone.utc)
    stale = now - timedelta(minutes=5)
    machine_id = uuid.uuid4()
    # Five requests at once, each with the machine as it was loaded.
    loaded = [SimpleNamespace(id=machine_id, last_seen_at=stale) for _ in range(5)]
    for machine in loaded:
        machine_presence.mark_machine_seen(machine, now)
    assert sum(m.last_seen_at == now for m in loaded) == 1

    clock[0] += 61
    later = SimpleNamespace(id=machine_id, last_seen_at=stale)
    machine_presence.mark_machine_seen(later, now + timedelta(seconds=61))
    assert later.last_seen_at == now + timedelta(seconds=61)

    fresh = SimpleNamespace(id=uuid.uuid4(), last_seen_at=now - timedelta(seconds=10))
    machine_presence.mark_machine_seen(fresh, now)
    assert fresh.last_seen_at == now - timedelta(seconds=10)


def test_a_crop_is_three_cached_statements(client, db, machine_token, upload_dir):
    # Production sessions keep what they loaded across a commit; the test
    # session would read the machine again after the one before the upload.
    assert SessionLocal.kw["expire_on_commit"] is False
    db.expire_on_commit = False
    assert _crop(client, machine_token, 1).status_code == 200
    with Statements() as sql:
        assert _crop(client, machine_token, 2).status_code == 200
    # The machine's token, the crop, the watermark, none compiled again.
    assert len(sql.sql) == 3, sql.sql
    assert sql.count("SELECT") == 1
    assert sql.count("INSERT INTO machine_channel_crops") == 1
    assert sql.count("INSERT INTO machine_sync_state") == 1
    assert sql.cached == [True, True, True], list(zip(sql.sql, sql.cached))


def test_s3_puts_a_small_file_in_one_request():
    backend = S3StorageBackend(
        bucket="bucket",
        endpoint_url="http://127.0.0.1:9",
        region="us-east-1",
        access_key_id="test",
        secret_access_key="test",
    )
    calls: list[tuple] = []

    class Client:
        def put_object(self, **kwargs):
            calls.append(("put", kwargs))

        def upload_fileobj(self, source, bucket, key, ExtraArgs=None):
            calls.append(("transfer", key, ExtraArgs, len(source.read())))

    backend.client = Client()
    backend.write_stream("small", io.BytesIO(b"x" * 1000), content_type="image/jpeg")
    big = S3StorageBackend.SINGLE_PUT_MAX_BYTES + 1
    backend.write_stream("big", io.BytesIO(b"\0" * big), content_type="application/gzip")

    assert calls[0] == ("put", {"Bucket": "bucket", "Key": "small", "Body": b"x" * 1000, "ContentType": "image/jpeg"})
    assert calls[1] == ("transfer", "big", {"ContentType": "application/gzip"}, big)
