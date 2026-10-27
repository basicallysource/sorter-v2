"""Channel crops go to Hive in batches: one upload for many crops, sent once
enough are waiting or the oldest has waited a minute, cut at the batch's byte
limit. A Hive without the batch endpoint gets them one at a time."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import requests

import channel_crop_store
from server import hive_sync

FAKE_JPEG = b"\xff\xd8\xff" + b"x" * 97


class _Client:
    def __init__(self, batch_status: int | None = None) -> None:
        self.batch_status = batch_status
        self.batches: list[list[tuple[dict, Path | None]]] = []
        self.singles: list[dict] = []

    def pushChannelCropBatch(self, crops):
        if self.batch_status is not None:
            response = requests.Response()
            response.status_code = self.batch_status
            raise requests.HTTPError(response=response)
        self.batches.append(crops)
        return max(meta["local_id"] for meta, _ in crops)

    def pushChannelCrop(self, meta, file_path):
        self.singles.append(meta)
        return meta["local_id"]


def _syncer(client: _Client):
    syncer = hive_sync._TargetSyncer.__new__(hive_sync._TargetSyncer)
    syncer._id = "t"
    syncer._name = "test hive"
    syncer._client = client
    syncer._gate = hive_sync._ConcurrencyGate(1, 1, lambda: False)
    syncer._stop = threading.Event()
    syncer._budget = hive_sync._UploadBudget()
    syncer._budget.setLimits(100_000_000, 1000)
    syncer._budget_wait_s = None
    syncer._crop_batches_off_until = 0.0
    syncer._wm = {t: 0 for t in hive_sync.DATA_TYPES}
    return syncer


def _rows(monkeypatch, tmp_path: Path, count: int, *, age_s: float = 0.0, size: int = len(FAKE_JPEG)) -> None:
    files = []
    for i in range(count):
        path = tmp_path / f"{i + 1}.jpg"
        path.write_bytes(FAKE_JPEG)
        files.append(path)
    rows = [
        {"id": i + 1, "channel": 3, "ts": 1.0, "created_at": time.time() - age_s, "track_id": 4,
         "com_forward_to_exit_deg": 2.0, "com_section": 1, "zone_code": 2, "sharpness": 9.0,
         "bbox": [1, 2, 3, 4], "bytes": size, "evicted_locally": False, "file_path": f"{i + 1}.jpg"}
        for i in range(count)
    ]
    monkeypatch.setattr(channel_crop_store, "listCropsAfter",
                        lambda after, limit: [r for r in rows if r["id"] > after][:limit])
    monkeypatch.setattr(channel_crop_store, "cropFile", lambda row: files[row["id"] - 1])
    monkeypatch.setattr(channel_crop_store, "getCropFileById", lambda crop_id: files[crop_id - 1])


def test_a_few_fresh_crops_wait_and_then_go_together(monkeypatch, tmp_path) -> None:
    client = _Client()
    syncer = _syncer(client)
    _rows(monkeypatch, tmp_path, 5)
    assert not syncer._drainChannelCrops()
    _rows(monkeypatch, tmp_path, 5, age_s=hive_sync.CROP_BATCH_WAIT_S + 1)
    assert syncer._drainChannelCrops()
    [batch] = client.batches
    assert [meta["local_id"] for meta, _ in batch] == [1, 2, 3, 4, 5]
    assert syncer._wm[hive_sync.DATA_TYPE_CROPS] == 5 and not client.singles


def test_a_backlog_goes_in_full_batches_cut_at_the_byte_limit(monkeypatch, tmp_path) -> None:
    client = _Client()
    syncer = _syncer(client)
    per_crop = hive_sync.MAX_CROP_BATCH_BYTES // 150
    _rows(monkeypatch, tmp_path, 400, size=per_crop)
    while syncer._drainChannelCrops():
        pass
    assert [len(b) for b in client.batches] == [150, 150, 100]
    assert syncer._wm[hive_sync.DATA_TYPE_CROPS] == 400


def test_a_hive_without_batches_gets_crops_one_at_a_time(monkeypatch, tmp_path) -> None:
    client = _Client(batch_status=404)
    syncer = _syncer(client)
    _rows(monkeypatch, tmp_path, 150)
    assert syncer._drainChannelCrops()
    assert len(client.singles) == hive_sync.FILES_PER_PASS and not client.batches
    assert syncer._crop_batches_off_until > time.monotonic() + hive_sync.UNSUPPORTED_RETRY_S - 60
