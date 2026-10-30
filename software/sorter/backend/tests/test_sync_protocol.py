"""Per-piece storage and its sync to Hive: the one cursor rule (sync_seq.py),
the first-run migration, predictions, piece images, the sync loop's legs, and
storage maintenance (retention and vacuum)."""

from __future__ import annotations

import base64
import os
import queue
import random
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import requests

import bin_contents
import db
import piece_image_store
import piece_predictions
import piece_records
import sorting_runs
import storage_maintenance
import sync_seq
from server import hive_sync

FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"x" * 200 + b"\xff\xd9"
FAKE_JPEG_B64 = base64.b64encode(FAKE_JPEG).decode("utf-8")
DAY = 86400.0


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


class _DbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._old_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "state.sqlite")
        os.environ["LOCAL_STATE_DB_PATH"] = self.db_path
        piece_image_store._worker_started.set()
        # A queue of this test's own: no worker an earlier test started takes from it.
        piece_image_store._queue = queue.Queue(maxsize=piece_image_store._queue.maxsize)
        with piece_image_store._seen_lock:
            piece_image_store._seen_counts.clear()
            piece_image_store._seen_order.clear()
            piece_image_store._flags_done.clear()
        piece_records._aggregates_memo.clear()
        piece_records._value_stats_memo = None

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_db
        self._tmpdir.cleanup()

    def drainImageQueue(self) -> None:
        while True:
            try:
                kind, piece_uuid, payload = piece_image_store._queue.get_nowait()
            except Exception:
                return
            if kind == "image":
                piece_image_store._writeImage(piece_uuid, *payload)
            elif kind == "flags":
                piece_image_store._updateImageFlags(piece_uuid, payload)

    def record(self, piece_uuid: str, seen_at: float | None = None, **fields) -> None:
        seen_at = time.time() if seen_at is None else seen_at
        piece = {
            "uuid": piece_uuid,
            "created_at": seen_at,
            "distributed_at": seen_at,
            "classification_status": "classified",
            "part_id": "3001",
            "part_name": "Brick 2 x 4",
            "color_id": "11",
            "color_name": "Black",
            "destination_bin": [0, 0, 1],
        }
        piece.update(fields)
        piece_records.recordPiece(piece, run_id="process-1")

    def images(self, piece_uuid: str, n: int, *, used: bool = False) -> None:
        piece_image_store.enqueueKnownObjectImages({
            "uuid": piece_uuid,
            "recognition_image_set": [
                {"image": FAKE_JPEG_B64, "source": "c4_burst", "channel": 4, "ts": 1000.0 + i,
                 "created_at": time.time(), "sharpness": 50.0, "used": used, "excluded_from_result": False}
                for i in range(n)
            ],
        })
        self.drainImageQueue()


class CursorRuleTests(_DbTestCase):
    def test_an_update_after_sync_is_sent_again_with_the_whole_verdict(self) -> None:
        self.record("a")
        rows = piece_records.listRecordsAfter(0, 10)
        self.assertEqual(["a"], [r["uuid"] for r in rows])
        wm = rows[-1]["sync_seq"]
        self.assertEqual([], piece_records.listRecordsAfter(wm, 10))

        piece_records.setPieceCorrection(
            "a", set_color=True, color_corrected_id="85",
            set_rejection_reasons=True, rejection_reasons=["blurry", "not_lego"],
        )
        again = piece_records.listRecordsAfter(wm, 10)
        self.assertEqual(["a"], [r["uuid"] for r in again])
        payload = hive_sync._recordToPayload(again[0])
        self.assertGreater(payload["sync_seq"], wm)
        self.assertEqual("85", payload["color_corrected_id"])
        self.assertEqual(["blurry", "not_lego"], payload["rejection_reasons"])
        self.assertIsNone(payload["part_correct"])

        wm = payload["sync_seq"]
        piece_records.markFeedbackSubmitted("a", color=True)
        flagged = piece_records.listRecordsAfter(wm, 10)
        self.assertTrue(hive_sync._recordToPayload(flagged[0])["color_feedback_submitted"])
        # The distribution write after an early record goes again too, and
        # keeps the verdict.
        wm = flagged[0]["sync_seq"]
        self.record("a", destination_bin=[0, 0, 7])
        final = piece_records.listRecordsAfter(wm, 10)
        self.assertEqual(7, final[0]["bin_z"])
        self.assertEqual("85", final[0]["color_corrected_id"])

    def test_a_correction_on_an_unknown_piece_takes_no_seq(self) -> None:
        self.record("a")
        seq_before = piece_records.listRecordsAfter(0, 10)[-1]["sync_seq"]
        self.assertFalse(piece_records.setPieceCorrection("nope", set_part=True, part_correct=False))
        self.record("b")
        self.assertEqual(seq_before + 1, piece_records.listRecordsAfter(seq_before, 10)[0]["sync_seq"])

    def test_nothing_is_skipped_while_writes_interleave_with_the_reader(self) -> None:
        piece_records.listRecordsAfter(0, 1)  # schema
        rng = random.Random(7)
        done = threading.Event()
        written: list[str] = []

        def writer() -> None:
            for i in range(250):
                uuid_val = f"p{i}"
                self.record(uuid_val)
                written.append(uuid_val)
                if written and rng.random() < 0.6:
                    target = rng.choice(written)
                    piece_records.setPieceCorrection(target, set_part=True, part_correct=rng.random() < 0.5)
            done.set()

        received: dict[str, set[int]] = {}
        wm = 0

        def drain_once() -> int:
            nonlocal wm
            rows = piece_records.listRecordsAfter(wm, 7)
            for row in rows:
                received.setdefault(row["uuid"], set()).add(int(row["sync_seq"]))
            if rows:
                wm = int(rows[-1]["sync_seq"])
            return len(rows)

        thread = threading.Thread(target=writer)
        thread.start()
        while not done.is_set():
            drain_once()
        thread.join()
        while drain_once():
            pass
        with piece_records._connection() as conn:
            final = {r["uuid"]: int(r["sync_seq"]) for r in conn.execute("SELECT uuid, sync_seq FROM piece_records")}
        self.assertEqual(250, len(final))
        for uuid_val, seq in final.items():
            self.assertIn(seq, received.get(uuid_val, set()), f"{uuid_val} at seq {seq} was never read")


class FirstRunTests(_DbTestCase):
    def _oldDatabase(self) -> None:
        # The schema the previous version left: no sync_seq, a correction
        # journal, piece_images with a never-written hive_image_id.
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE piece_records (id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT UNIQUE, run_id TEXT, "
            "machine_id TEXT, seen_at REAL, recorded_at REAL, classification_status TEXT, part_id TEXT, "
            "part_name TEXT, color_id TEXT, color_name TEXT, category_id TEXT, confidence REAL, bin_x INTEGER, "
            "bin_y INTEGER, bin_z INTEGER, dead INTEGER NOT NULL DEFAULT 0, part_correct INTEGER, "
            "color_corrected_id TEXT, correction_updated_at REAL)"
        )
        for i in range(1, 6):
            conn.execute(
                "INSERT INTO piece_records (id, uuid, seen_at, classification_status, correction_updated_at, "
                "color_corrected_id) VALUES (?, ?, ?, 'classified', ?, ?)",
                (i, f"r{i}", 1000.0 + i, 2000.0 if i == 2 else None, "85" if i == 2 else None),
            )
        conn.execute(
            "CREATE TABLE piece_corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, piece_uuid TEXT NOT NULL, "
            "part_correct INTEGER, color_corrected_id TEXT, part_feedback_submitted INTEGER NOT NULL DEFAULT 0, "
            "color_feedback_submitted INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL, rejection_reasons TEXT)"
        )
        conn.execute("INSERT INTO piece_corrections (piece_uuid, color_corrected_id, updated_at) VALUES ('r2', '85', 2000.0)")
        conn.execute(
            "CREATE TABLE piece_images (id INTEGER PRIMARY KEY AUTOINCREMENT, piece_uuid TEXT NOT NULL, "
            "seq INTEGER NOT NULL, source TEXT, channel INTEGER, ts REAL, created_at REAL NOT NULL, sharpness REAL, "
            "bytes INTEGER NOT NULL, file_path TEXT NOT NULL, deleted_at REAL, synced_at REAL, hive_image_id TEXT, "
            "used INTEGER NOT NULL DEFAULT 0, excluded_from_result INTEGER NOT NULL DEFAULT 0, score REAL, "
            "UNIQUE(piece_uuid, seq))"
        )
        conn.execute(
            "CREATE INDEX idx_piece_images_unsynced ON piece_images(created_at) WHERE synced_at IS NULL AND deleted_at IS NULL"
        )
        for i in range(1, 9):
            conn.execute(
                "INSERT INTO piece_images (id, piece_uuid, seq, created_at, bytes, file_path) VALUES (?, ?, ?, ?, 10, 'x.jpg')",
                (i, f"r{(i % 5) + 1}", i, 1000.0 + i),
            )
        conn.commit()
        conn.close()

    def test_existing_ids_keep_their_watermark_meaning(self) -> None:
        self._oldDatabase()
        # Hive already has records up to id 3 and images up to id 6.
        records = piece_records.listRecordsAfter(3, 100)
        # 4 and 5 were never sent; 2 had a verdict that may not have reached
        # Hive (its journal is gone), so it goes again.
        self.assertEqual(["r4", "r5", "r2"], [r["uuid"] for r in records])
        self.assertEqual([4, 5], [r["sync_seq"] for r in records[:2]])
        self.assertGreater(records[2]["sync_seq"], 8)  # above every id in every table
        self.assertEqual("85", records[2]["color_corrected_id"])
        self.assertEqual([7, 8], [r["sync_seq"] for r in piece_image_store.listImagesAfter(6, 100)])
        # Every new seq is above every old id.
        self.record("new")
        newest = piece_records.listRecordsAfter(records[2]["sync_seq"], 10)
        self.assertEqual(["new"], [r["uuid"] for r in newest])
        with piece_records._connection() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        self.assertNotIn("piece_corrections", tables)
        self.assertNotIn("idx_piece_images_unsynced", tables)

    def test_a_fresh_database_starts_at_one(self) -> None:
        self.record("a")
        self.assertEqual(1, piece_records.listRecordsAfter(0, 10)[0]["sync_seq"])


class PieceImageTests(_DbTestCase):
    def test_images_wait_for_their_record_and_go_once_with_final_flags(self) -> None:
        self.images("p", 2)
        self.assertEqual([], piece_image_store.listImagesAfter(0, 10))
        # Classification settles: the flags land before the record.
        piece_image_store._maybeEnqueueFlags("p", [
            {"used": True, "excluded_from_result": False},
            {"used": False, "excluded_from_result": True},
        ])
        self.drainImageQueue()
        self.assertEqual([], piece_image_store.listImagesAfter(0, 10))

        self.record("p")
        record_seq = piece_records.listRecordsAfter(0, 10)[0]["sync_seq"]
        rows = piece_image_store.listImagesAfter(0, 10)
        self.assertEqual([(0, True, False), (1, False, True)], [(r["seq"], r["used"], r["excluded_from_result"]) for r in rows])
        self.assertEqual(2, len({r["sync_seq"] for r in rows}))
        self.assertTrue(all(r["sync_seq"] > record_seq for r in rows))
        wm = rows[-1]["sync_seq"]

        # The record written again (distribution after an early record) does
        # not send the images again.
        self.record("p", destination_bin=[0, 0, 3])
        self.assertEqual([], piece_image_store.listImagesAfter(wm, 10))

        # A frame written after its record is ready at once.
        piece_image_store._writeImage("p", 2, {"image": FAKE_JPEG_B64, "source": "c4_burst", "created_at": time.time()})
        late = piece_image_store.listImagesAfter(wm, 10)
        self.assertEqual([2], [r["seq"] for r in late])

    def test_flags_that_change_after_the_record_send_the_image_again(self) -> None:
        self.images("q", 1)
        self.record("q")
        wm = piece_image_store.listImagesAfter(0, 10)[-1]["sync_seq"]
        piece_image_store._updateImageFlags("q", [(0, 0, 0, None)])  # unchanged
        self.assertEqual([], piece_image_store.listImagesAfter(wm, 10))
        piece_image_store._updateImageFlags("q", [(0, 1, 0, None)])
        again = piece_image_store.listImagesAfter(wm, 10)
        self.assertEqual([True], [r["used"] for r in again])

    def test_images_of_a_piece_never_recorded_never_sync(self) -> None:
        self.images("orphan", 2)
        self.record("other")
        self.assertEqual([], [r for r in piece_image_store.listImagesAfter(0, 10) if r["piece_uuid"] == "orphan"])

    def test_the_flags_set_forgets_the_oldest_piece_first(self) -> None:
        with patch.object(piece_image_store, "_MAX_SEEN_UUIDS", 2):
            for name in ("a", "b", "c"):
                piece_image_store._maybeEnqueueFlags(name, [{"used": True}])
        self.assertEqual(["b", "c"], list(piece_image_store._flags_done))
        self.drainImageQueue()


def _attempt(label: str, applied: bool, items: list[dict], colors: list[dict], images: list[dict] | None = None):
    from defs.known_object import ClassificationAttempt
    from defs.events import ClassificationAttemptStrategy

    return ClassificationAttempt(
        strategy=ClassificationAttemptStrategy(label), n_burst=1, found=bool(items), label=label,
        applied=applied, items=items, colors=colors, images=images,
    )


def _live(
    request: str, kind: str, value_id: str, *, rank: int = 0, score: float = 0.5, applied: bool = False,
    created_at: float | None = None,
) -> dict:
    """One live prediction with one answer."""
    return {
        "source": "live", "request": request, "provider": "brickognize", "model_name": None, "model_sha": None,
        "images": None, "created_at": time.time() if created_at is None else created_at,
        "answers": [{"kind": kind, "rank": rank, "value_id": value_id, "value_name": None, "score": score,
                     "applied": applied}],
    }


class PredictionTests(_DbTestCase):
    def test_every_ranked_answer_is_kept_under_its_request_with_what_it_saw(self) -> None:
        burst = [{"set": "burst", "seq": 0, "channel": 4}, {"set": "burst", "seq": 2, "channel": 4}]
        link = {"set": "link", "seq": 0, "channel": 3}
        attempts = [
            _attempt(
                "combined", True,
                [{"id": "3001", "name": "Brick", "score": 0.9, "rank": 0}, {"id": "3002", "name": "Brick 2x3", "score": 0.05, "rank": 2}],
                [{"id": "11", "name": "Black", "score": 0.7, "rank": 1}, {"id": "85", "name": "Dark Bluish Gray", "score": 0.2, "rank": 0}],
                images=[*burst, link],
            ),
            _attempt("single_burst", False, [{"id": "3001", "name": "Brick", "score": 0.8, "rank": 0}], [], images=burst[1:]),
            _attempt("single_burst", False, [], []),  # an empty request is left out
        ]
        hosted = {"model_name": "colorpred-v3", "model_sha256": "abc", "top": [
            {"color_id": 85, "color_name": "Dark Bluish Gray", "confidence": 0.6},
            {"color_id": 11, "color_name": "Black", "confidence": 0.3},
            {"color_id": 86, "color_name": "Light Bluish Gray", "confidence": 0.05},
        ]}
        predictions = piece_predictions.fromClassification(
            attempts=attempts, hosted=hosted, hosted_images=[*burst, link],
            applied_part=("3001", 0), applied_color=("hive_basically", "85", None), created_at=5000.0,
        )
        self.assertEqual(["combined", "single_burst", "hosted"], [p["request"] for p in predictions])
        self.assertEqual(8, sum(len(p["answers"]) for p in predictions))
        piece_predictions.recordPredictions("piece", predictions)
        self.assertEqual(0, piece_predictions.recordPredictions("piece", predictions))  # a retry adds nothing

        stored = piece_predictions.listForPiece("piece")
        self.assertEqual(predictions, stored)
        combined, single, hosted_ = stored
        self.assertEqual(("live", "brickognize", None, None), (combined["source"], combined["provider"], combined["model_name"], combined["model_sha"]))
        self.assertEqual([*burst, link], combined["images"])
        self.assertEqual(
            [("color", 0, "85", False), ("color", 1, "11", False), ("part", 0, "3001", True), ("part", 2, "3002", False)],
            [(a["kind"], a["rank"], a["value_id"], a["applied"]) for a in combined["answers"]],
        )
        self.assertEqual(burst[1:], single["images"])
        self.assertEqual(("hive_basically", "colorpred-v3", "abc"), (hosted_["provider"], hosted_["model_name"], hosted_["model_sha"]))
        self.assertEqual([("85", 0.6, True), ("11", 0.3, False), ("86", 0.05, False)],
                         [(a["value_id"], a["score"], a["applied"]) for a in hosted_["answers"]])

    def test_a_classified_piece_keeps_every_request_and_the_images_it_sent(self) -> None:
        from defs.known_object import KnownObject
        from defs.events import ClassificationAttemptStrategy
        from defs.known_object import RecognitionImage
        from subsystems.classification_channel.two_piece.base import (
            Rev01BaseState, _ClassifyRequest, _SendImage, _imageRefs,
        )
        from subsystems.classification_channel.two_piece.context import SimpleStateMachineRev01Context

        class _Logger:
            def info(self, *_a, **_k): ...
            def warning(self, *_a, **_k): ...
            def error(self, *_a, **_k): ...

        state = Rev01BaseState.__new__(Rev01BaseState)
        state.logger = _Logger()
        state.gc = SimpleNamespace(logger=_Logger())
        state.event_queue = SimpleNamespace(put=lambda _e: None)
        state.ctx = SimpleStateMachineRev01Context()
        state._prefetchHiveMetadata = lambda _r: None
        state._applyHivePieceMetadata = lambda _o: None
        state.sharpness = lambda _f: 0.0
        piece = KnownObject(uuid="classified-1")
        piece.recognition_image_set = [RecognitionImage(image="", source="c4_burst", channel=4) for _ in range(3)]
        piece.link_match_image_set = [RecognitionImage(image="", source="link_match", channel=2)]
        state.ctx.known_object = piece
        state.ctx.captured_crops = []

        frame = np.zeros((2, 2, 3), np.uint8)
        sent = [_SendImage(frame, piece.recognition_image_set[1]), _SendImage(frame, piece.recognition_image_set[2]),
                _SendImage(frame, piece.link_match_image_set[0])]
        requests_ = [
            _ClassifyRequest(ClassificationAttemptStrategy.combined, "combined", sent),
            _ClassifyRequest(ClassificationAttemptStrategy.single_burst, "single_burst", [sent[1]]),
        ]
        for req in requests_:
            req.image_refs = _imageRefs(piece, req.images)
        colors = [{"id": str(c), "name": f"c{c}", "score": s} for c, s in ((5, 0.1), (11, 0.6), (85, 0.2), (86, 0.05), (1, 0.03), (2, 0.02))]
        for rank, color in enumerate(colors):
            color["rank"] = rank
        result = {"listing_id": "L", "items": [{"id": "3001", "name": "Brick", "score": 0.9, "rank": 0, "img_url": "u", "type": "part"}], "colors": colors}
        state._runRequestsParallel = lambda reqs, _uuid: [(req, result, None, 0.1) for req in reqs]
        holder = {"started_at": time.monotonic(), "thread": threading.Thread(target=lambda: None),
                  "images": _imageRefs(piece, sent),
                  "result": {"color_id": 11, "color_name": "Black", "confidence": 0.8, "model_sha256": "sha",
                             "model_name": "colorpred-v3",
                             "top": [{"color_id": 11, "color_name": "Black", "confidence": 0.8},
                                     {"color_id": 85, "color_name": "DBG", "confidence": 0.1}]}}
        holder["thread"].start()
        state._runClassifyRequests(requests_, piece.uuid, holder)
        state.updateKnownObjectWithResult(state.ctx.classification_result, None)
        self.assertTrue(db.drain(5.0))

        combined = state.ctx.classification_attempts[0]
        self.assertEqual(0.6, combined.color_score)
        self.assertEqual(["11", "85", "5", "86", "1"], [c["id"] for c in combined.colors])
        stored = piece_predictions.listForPiece(piece.uuid)
        self.assertEqual(stored, piece_predictions.recent(piece.uuid))
        counts = {(p["request"], kind): len([a for a in p["answers"] if a["kind"] == kind])
                  for p in stored for kind in ("part", "color")}
        self.assertEqual({("combined", "color"): 5, ("combined", "part"): 1, ("single_burst", "color"): 5,
                          ("single_burst", "part"): 1, ("hosted", "color"): 2, ("hosted", "part"): 0}, counts)
        applied = sorted((p["request"], a["kind"], a["value_id"]) for p in stored for a in p["answers"] if a["applied"])
        self.assertEqual([("combined", "part", "3001"), ("hosted", "color", "11")], applied)
        everything = [{"set": "burst", "seq": 1, "channel": 4}, {"set": "burst", "seq": 2, "channel": 4},
                      {"set": "link", "seq": 0, "channel": 2}]
        self.assertEqual({"combined": everything, "single_burst": everything[1:2], "hosted": everything},
                         {p["request"]: p["images"] for p in stored})
        self.assertEqual("colorpred-v3", stored[2]["model_name"])

    def test_piece_detail_serves_the_predictions_from_disk(self) -> None:
        from server import shared_state
        from server.routers import pieces

        self.record("d")
        piece_predictions.recordPredictions("d", piece_predictions.fromClassification(
            attempts=[_attempt("combined", True, [], [{"id": "11", "name": "Black", "score": 0.7, "rank": 0}])],
            hosted=None, applied_part=None, applied_color=("brickognize", "11", 0),
        ))
        with patch.object(shared_state, "gc_ref", None):
            detail = pieces.getPiece("d")
        self.assertEqual("disk", detail.origin)
        self.assertEqual([("live", "combined", None)], [(p.source, p.request, p.images) for p in detail.predictions])
        self.assertEqual([("color", "11", True)], [(a.kind, a.value_id, a.applied) for a in detail.predictions[0].answers])

    def _flatTable(self, rows: list[tuple]) -> None:
        """piece_predictions as sorters wrote it before requests had a table
        of their own."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE piece_predictions (id INTEGER PRIMARY KEY AUTOINCREMENT, piece_uuid TEXT NOT NULL, "
                "request TEXT NOT NULL, provider TEXT NOT NULL, model TEXT, kind TEXT NOT NULL, rank INTEGER NOT NULL, "
                "value_id TEXT NOT NULL, value_name TEXT, score REAL, applied INTEGER NOT NULL DEFAULT 0, "
                "created_at REAL NOT NULL, UNIQUE(piece_uuid, request, kind, rank))"
            )
            conn.execute("CREATE INDEX idx_piece_predictions_uuid ON piece_predictions(piece_uuid)")
            conn.executemany(
                "INSERT INTO piece_predictions (id, piece_uuid, request, provider, model, kind, rank, value_id, "
                "value_name, score, applied, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            # The newest rows went (retention): their ids stay used.
            conn.execute("DELETE FROM piece_predictions WHERE id > 6")

    def test_old_rows_move_under_their_requests_and_keep_their_ids(self) -> None:
        self._flatTable([
            (1, "a", "combined", "brickognize", None, "part", 0, "3001", "Brick", 0.9, 1, 100.0),
            (2, "a", "combined", "brickognize", None, "color", 0, "11", "Black", 0.7, 0, 100.0),
            (3, "a", "single_burst", "brickognize", None, "part", 0, "3001", "Brick", 0.8, 0, 100.0),
            (4, "a", "hosted", "hive_basically", "sha", "color", 0, "85", "Dark Bluish Gray", 0.6, 1, 100.0),
            (5, "a", "hosted", "hive_basically", "sha", "color", 1, "11", "Black", 0.3, 0, 100.0),
            (6, "b", "combined", "brickognize", None, "part", 0, "3003", None, 0.5, 1, 200.0),
            (9, "c", "combined", "brickognize", None, "part", 0, "1", None, 0.1, 0, 300.0),
        ])
        self.assertEqual(6, piece_predictions.getMaxId())
        a = piece_predictions.listForPiece("a")
        self.assertEqual(["combined", "single_burst", "hosted"], [p["request"] for p in a])
        self.assertTrue(all(p["source"] == "live" and p["images"] is None for p in a))
        self.assertEqual(("hive_basically", None, "sha"), (a[2]["provider"], a[2]["model_name"], a[2]["model_sha"]))
        self.assertEqual([("85", True), ("11", False)], [(x["value_id"], x["applied"]) for x in a[2]["answers"]])

        # Hive's watermark still means what it did: the same ids, in order,
        # each with its request's fields.
        rows = piece_predictions.listAfter(3, 10)
        self.assertEqual([4, 5, 6], [r["id"] for r in rows])
        self.assertEqual(("a", "live", "hosted", "sha", 1), (rows[0]["piece_uuid"], rows[0]["source"], rows[0]["request"],
                                                           rows[0]["model_sha"], rows[0]["applied"]))
        # A new answer never takes an id Hive may already have.
        piece_predictions.recordPredictions("d", [_live("combined", "part", "1")])
        self.assertEqual([10], [r["id"] for r in piece_predictions.listAfter(6, 10)])
        with sqlite3.connect(self.db_path) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertNotIn("piece_predictions_flat", tables)

    def test_the_move_runs_once_and_an_empty_old_table_moves_too(self) -> None:
        self._flatTable([(7, "x", "combined", "brickognize", None, "part", 0, "1", None, 0.1, 0, 1.0)])
        self.assertEqual([], piece_predictions.listForPiece("x"))
        with piece_records._connection() as conn:
            piece_predictions._createTables(conn)  # again: nothing to do
            conn.commit()
        piece_predictions.recordPredictions("y", [_live("combined", "part", "1")])
        self.assertEqual([8], [r["id"] for r in piece_predictions.listAfter(0, 10)])

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from server.routers import pieces

        app = FastAPI()
        app.include_router(pieces.router)
        return TestClient(app)

    def _run(self, pieces: list[dict], **fields) -> dict:
        body = {"source": "colorpred-v4 rerun, 13 Oct", "provider": "basically", "model_name": "colorpred-v4",
                "model_sha": "f00d", "kind": "color", "made_at": 9000.0, "pieces": pieces}
        body.update(fields)
        return body

    def test_a_later_run_imports_once_per_piece_and_shows_beside_the_live_answers(self) -> None:
        from server import shared_state

        self.record("p")
        self.images("p", 3)
        piece_predictions.recordPredictions("p", [_live("combined", "color", "11", score=0.7, applied=True)])
        self.images("unrecorded-but-photographed", 1)
        answers = [{"value_id": "85", "value_name": "Dark Bluish Gray", "score": 0.81},
                   {"value_id": "11", "value_name": "Black", "score": 0.12}, {"value_id": "86", "score": 0.03}]
        body = self._run([
            {"piece_uuid": "p", "answers": answers, "image_seqs": [0, 2]},
            {"piece_uuid": "unrecorded-but-photographed", "answers": answers[:1], "image_seqs": [0]},
            {"piece_uuid": "nobody", "answers": answers[:1], "image_seqs": [0]},
        ])
        with self._client() as client:
            first = client.post("/api/predictions/import", json=body)
            again = client.post("/api/predictions/import", json=body)
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual({"added": 2, "already": 0, "unknown": ["nobody"]}, first.json())
        self.assertEqual({"added": 0, "already": 2, "unknown": ["nobody"]}, again.json())

        with patch.object(shared_state, "gc_ref", None), self._client() as client:
            detail = client.get("/api/pieces/p").json()
        live, rerun = detail["predictions"]
        self.assertEqual("live", live["source"])
        self.assertEqual(
            {"source": "colorpred-v4 rerun, 13 Oct", "request": "colorpred-v4", "provider": "basically",
             "model_name": "colorpred-v4", "model_sha": "f00d", "created_at": 9000.0,
             "images": [{"set": "burst", "seq": 0, "channel": 4}, {"set": "burst", "seq": 2, "channel": 4}]},
            {k: rerun[k] for k in ("source", "request", "provider", "model_name", "model_sha", "created_at", "images")},
        )
        self.assertEqual([(0, "85", 0.81, False), (1, "11", 0.12, False), (2, "86", 0.03, False)],
                         [(a["rank"], a["value_id"], a["score"], a["applied"]) for a in rerun["answers"]])

    def test_a_piece_in_memory_shows_an_imported_run_at_once(self) -> None:
        self.record("m")
        live = [_live("combined", "color", "11", applied=True)]
        piece_predictions.recordPredictions("m", live)
        piece_predictions.remember("m", live)
        piece_predictions.importRun(
            source="rerun", provider="basically", model_name="colorpred-v4", model_sha=None, kind="color",
            pieces=[{"piece_uuid": "m", "answers": [{"value_id": "85", "score": 0.9}], "image_seqs": []}],
        )
        self.assertEqual(["live", "rerun"], [p["source"] for p in piece_predictions.recent("m")])

    def test_an_import_is_bounded_and_never_poses_as_the_live_classification(self) -> None:
        one = {"piece_uuid": "p", "answers": [{"value_id": "85", "score": 0.9}], "image_seqs": [0]}
        with self._client() as client:
            too_many = client.post("/api/predictions/import",
                                   json=self._run([one] * (piece_predictions.IMPORT_MAX_PIECES + 1)))
            live = client.post("/api/predictions/import", json=self._run([one], source="live"))
            bad_kind = client.post("/api/predictions/import", json=self._run([one], kind="mold"))
            no_answers = client.post("/api/predictions/import", json=self._run([{**one, "answers": []}]))
        self.assertEqual(422, too_many.status_code)
        self.assertEqual(400, live.status_code)
        self.assertEqual(422, bad_kind.status_code)
        self.assertEqual(422, no_answers.status_code)
        self.assertEqual(0, piece_predictions.getMaxId())


class _FakeClient:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self.predictions: list[dict] = []
        self.images: list[dict] = []
        self.records_error: Exception | None = None

    def getSyncState(self) -> dict:
        return {}

    def pushPieceRecords(self, records: list[dict]) -> int:
        if self.records_error is not None:
            raise self.records_error
        self.records.extend(records)
        return max(r["sync_seq"] for r in records)

    def pushPiecePredictions(self, records: list[dict]) -> int:
        self.predictions.extend(records)
        return max(r["local_id"] for r in records)

    def pushPieceImage(self, meta: dict, file_path: Path | None) -> int:
        self.images.append(meta)
        return int(meta["sync_seq"])


class SyncLoopTests(_DbTestCase):
    def _syncer(self, client: _FakeClient):
        syncer = hive_sync._TargetSyncer.__new__(hive_sync._TargetSyncer)
        syncer._gc = None
        syncer._id = "t"
        syncer._name = "test hive"
        syncer._client = client
        syncer._gate = hive_sync._ConcurrencyGate(1, 1, lambda: False)
        syncer._stop = threading.Event()
        syncer._mark_retention = lambda: None
        syncer._paused_until = {t: 0.0 for t in hive_sync.DATA_TYPES}
        syncer._paused_why = {}
        syncer._budget = hive_sync._UploadBudget()
        syncer._budget_wait_s = None
        syncer._last_error = None
        syncer._state_ok = True
        syncer._backoff_s = hive_sync.SERVER_DOWN_BACKOFF_S
        syncer._next_waiting_note = float("inf")
        syncer._wm = {t: 0 for t in hive_sync.DATA_TYPES}
        return syncer

    def _pass(self, syncer, allowed=("piece_records", "piece_images"), files_per_minute: int = 1000) -> bool:
        limits = {"upload_bytes_per_minute": 10_000_000, "upload_files_per_minute": files_per_minute}
        with patch.object(hive_sync.sharing, "streamAllowed", lambda _t, stream: stream in allowed), \
                patch.object(hive_sync.hive_limits, "targetLimits", lambda _t: limits):
            return syncer._runOnce()

    def _readyPiece(self, name: str) -> None:
        self.images(name, 2)
        self.record(name)
        piece_predictions.recordPredictions(name, [_live("combined", "color", "11", score=0.7, applied=True)])

    def test_a_later_run_syncs_after_the_live_answers_with_its_source(self) -> None:
        self._readyPiece("a")
        piece_predictions.importRun(
            source="colorpred-v4 rerun, 13 Oct", provider="basically", model_name="colorpred-v4", model_sha="f00d",
            kind="color", pieces=[{"piece_uuid": "a", "answers": [{"value_id": "85", "score": 0.8}], "image_seqs": [0, 1]}],
        )
        client = _FakeClient()
        self._pass(self._syncer(client))
        self.assertEqual(
            [("live", "combined", None, None, None, True),
             ("colorpred-v4 rerun, 13 Oct", "colorpred-v4", "f00d", "colorpred-v4",
              [{"set": "burst", "seq": 0, "channel": 4}, {"set": "burst", "seq": 1, "channel": 4}], False)],
            [(r["source"], r["request"], r["model"], r["model_name"], r["images"], r["applied"]) for r in client.predictions],
        )
        self.assertEqual([1, 2], [r["local_id"] for r in client.predictions])

    def test_every_leg_runs_in_the_same_pass(self) -> None:
        self._readyPiece("a")
        client = _FakeClient()
        syncer = self._syncer(client)
        self.assertTrue(self._pass(syncer))
        self.assertEqual(["a"], [r["piece_uuid"] for r in client.records])
        self.assertEqual(["a"], [r["piece_uuid"] for r in client.predictions])
        self.assertEqual(2, len(client.images))
        self.assertFalse(self._pass(syncer))  # nothing left

    def test_a_refused_batch_pauses_its_leg_and_the_others_carry_on(self) -> None:
        self._readyPiece("a")
        client = _FakeClient()
        client.records_error = _http_error(422)
        syncer = self._syncer(client)
        self.assertTrue(self._pass(syncer))
        self.assertEqual([], client.records)
        self.assertEqual(2, len(client.images))
        self.assertEqual(1, len(client.predictions))
        self.assertGreater(syncer._paused_until[hive_sync.DATA_TYPE_RECORDS], time.monotonic())
        self.assertIn("piece_records", syncer._legError())
        # Images of a piece recorded later still go while records wait.
        self._readyPiece("b")
        self._pass(syncer)
        self.assertEqual(4, len(client.images))
        self.assertEqual([], client.records)

    def test_a_server_error_backs_the_whole_target_off(self) -> None:
        self._readyPiece("a")
        client = _FakeClient()
        client.records_error = _http_error(503)
        syncer = self._syncer(client)
        with self.assertRaises(requests.HTTPError):
            self._pass(syncer)
        self.assertEqual(0.0, syncer._paused_until[hive_sync.DATA_TYPE_RECORDS])

    def test_a_spent_budget_waits_instead_of_spinning(self) -> None:
        self._readyPiece("a")
        client = _FakeClient()
        syncer = self._syncer(client)
        syncer._budget.setLimits(10_000_000, 1)
        syncer._budget._files = 0.0
        self.assertTrue(self._pass(syncer, files_per_minute=1))  # records and predictions still go
        self.assertEqual([], client.images)
        self.assertGreater(syncer._budget_wait_s, 30.0)
        self.assertFalse(self._pass(syncer, files_per_minute=1))

    def test_retention_watermarks_ignore_a_type_a_target_does_not_take(self) -> None:
        syncer = self._syncer(_FakeClient())
        syncer._wm[hive_sync.DATA_TYPE_IMAGES] = 7
        effective = {stream: True for stream in hive_sync.STREAM.values()}
        effective["piece_images"] = False
        with patch.object(hive_sync.sharing, "consentGiven", lambda: True), \
                patch.object(hive_sync.sharing, "effective", lambda _t: effective):
            wms = syncer.retentionWatermarks()
            self.assertEqual(hive_sync.NOT_WANTED, wms[hive_sync.DATA_TYPE_IMAGES])
            self.assertEqual(0, wms[hive_sync.DATA_TYPE_RECORDS])
            syncer._state_ok = False
            self.assertIsNone(syncer.retentionWatermarks()[hive_sync.DATA_TYPE_RECORDS])
        with patch.object(hive_sync.sharing, "consentGiven", lambda: False):
            self.assertEqual(hive_sync.NOT_WANTED, syncer.retentionWatermarks()[hive_sync.DATA_TYPE_RECORDS])


class RetentionTests(_DbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.now = time.time()
        self.cutoff = self.now - storage_maintenance.PIECE_HISTORY_DAYS * DAY

    def _totals(self) -> dict:
        lot = sorting_runs.listLots()[0]
        return {
            "overview": piece_records.getOverview(),
            "aggregates": piece_records.getAggregates(None, days=3650),
            "runs": [(r["name"], r["pieces"], r["distributed_pieces"]) for r in sorting_runs.listRuns()],
            "lot": (lot["pieces"], lot["runs"]),
            "lot_parts": [(p["part_id"], p["color_id"], p["counts"], p["in_lot"]) for p in sorting_runs.lotParts(lot["id"])["parts"]],
        }

    def _seed(self) -> None:
        lot = sorting_runs.createLot("Bulk box")
        sorting_runs.startRun("old run", lot_id=lot["id"], started_at=self.now - 400 * DAY)
        sorting_runs.startRun("newer run", lot_id=lot["id"], started_at=self.now - 30 * DAY)
        self.record("old-a", self.now - 300 * DAY)
        self.images("old-a", 2)
        piece_predictions.recordPredictions(
            "old-a", [_live("combined", "part", "3001", score=0.9, applied=True, created_at=self.now - 300 * DAY)]
        )
        self.record("old-b", self.now - 250 * DAY, part_id="3003", color_id="5", color_name="Red")
        piece_records.setPieceCorrection("old-b", set_color=True, color_corrected_id="21")
        self.record("old-dead", self.now - 240 * DAY, dead=True, destination_bin=None)
        self.record("old-unsent", self.now - 200 * DAY)
        self.record("new", self.now - 10 * DAY)
        # Hive has everything but old-unsent's latest write.
        self.records_wm = piece_records.listRecordsAfter(0, 100)[-1]["sync_seq"]
        piece_records.setPieceCorrection("old-unsent", set_part=True, part_correct=False)

    def _confirmed(self, records_wm: int | None) -> dict:
        return {
            hive_sync.DATA_TYPE_RECORDS: records_wm,
            hive_sync.DATA_TYPE_IMAGES: 10**9,
            hive_sync.DATA_TYPE_PREDICTIONS: 10**9,
        }

    def test_old_synced_pieces_go_and_every_total_stays(self) -> None:
        self._seed()
        before = self._totals()
        image_files = [piece_image_store.getImageFile("old-a", r["id"]) for r in piece_image_store.listPieceImages("old-a")]
        self.assertTrue(all(f is not None and f.is_file() for f in image_files))

        removed = storage_maintenance.prunePieceHistory(self.cutoff, self._confirmed(self.records_wm))
        self.assertEqual(3, removed)
        with piece_records._connection() as conn:
            left = sorted(r[0] for r in conn.execute("SELECT uuid FROM piece_records"))
        self.assertEqual(["new", "old-unsent"], left)
        self.assertEqual([], piece_image_store.listPieceImages("old-a"))
        self.assertEqual([], piece_predictions.listForPiece("old-a"))
        self.assertTrue(all(not f.exists() for f in image_files))
        piece_records._aggregates_memo.clear()
        self.assertEqual(before, self._totals())
        # No run may start inside the folded history.
        with self.assertRaises(sorting_runs.RunError):
            sorting_runs.startRun("too early", started_at=self.now - 245 * DAY)
        sorting_runs.startRun("fine", started_at=self.now - 100 * DAY)

    def test_nothing_goes_while_a_targets_state_is_unknown(self) -> None:
        self._seed()
        self.assertEqual(0, storage_maintenance.prunePieceHistory(self.cutoff, self._confirmed(None)))

    def test_without_a_target_age_alone_decides(self) -> None:
        self._seed()
        self.assertEqual(4, storage_maintenance.prunePieceHistory(self.cutoff, None))

    def test_a_piece_with_unsent_images_waits(self) -> None:
        self._seed()
        confirmed = self._confirmed(10**9)
        confirmed[hive_sync.DATA_TYPE_IMAGES] = 0
        storage_maintenance.prunePieceHistory(self.cutoff, confirmed)
        with piece_records._connection() as conn:
            left = sorted(r[0] for r in conn.execute("SELECT uuid FROM piece_records"))
        self.assertEqual(["new", "old-a"], left)

    def test_leftovers_of_unrecorded_pieces_go_by_age(self) -> None:
        old = self.now - 300 * DAY
        piece_predictions.recordPredictions("never", [_live("combined", "part", "1", score=0.1, created_at=old)])
        piece_predictions.recordPredictions("young", [_live("combined", "part", "1", score=0.1, created_at=self.now)])
        piece_image_store._writeImage("never", 0, {"image": FAKE_JPEG_B64, "source": "c4_burst", "created_at": old})
        piece_image_store._writeLinkImage("never", 0, {"image": FAKE_JPEG_B64, "created_at": old})
        deleted = storage_maintenance.pruneUnrecorded(self.cutoff, None)
        # The answer, then its request, the image and the link guess.
        self.assertEqual(4, deleted)
        with piece_records._connection() as conn:
            requests_left = [r[0] for r in conn.execute("SELECT piece_uuid FROM piece_prediction_requests")]
        self.assertEqual(["young"], requests_left)
        self.assertEqual([], piece_predictions.listForPiece("never"))
        self.assertEqual(1, len(piece_predictions.listForPiece("young")))
        self.assertEqual([], piece_image_store.listPieceImages("never"))
        self.assertEqual([], piece_image_store.listPieceLinkImages("never"))

    def test_cycles_and_held_pieces_keep_sixty_days(self) -> None:
        import held_piece_records
        import piece_cycles

        with db.connect(piece_cycles._createTables) as conn:
            conn.execute("INSERT INTO piece_cycles (asked_at) VALUES (?), (?)", (self.now - 61 * DAY, self.now - DAY))
            conn.commit()
        with db.connect(held_piece_records._createTables) as conn:
            conn.execute(
                "INSERT INTO held_pieces (channel, started_at, ended_at, turns, gave_up, outcome) VALUES "
                "(2, ?, ?, 1, 0, 'freed'), (2, ?, ?, 1, 0, 'freed')",
                (self.now - 61 * DAY, self.now - 61 * DAY, self.now - DAY, self.now - DAY),
            )
            conn.commit()
        self.assertEqual(1, piece_cycles.prune(self.now))
        self.assertEqual(1, held_piece_records.prune(self.now))


class BinContentsStorageTests(_DbTestCase):
    def test_old_bin_events_go_unless_the_piece_is_still_in_a_bin(self) -> None:
        now = time.time()
        for i, (bin_index, age) in enumerate(((0, 300), (1, 300), (1, 1))):
            bin_contents.record_piece_distribution({
                "uuid": f"e{i}", "destination_bin": [0, 0, bin_index], "distributed_at": now - age * DAY,
                "part_id": "3001", "color_id": "11",
            })
        bin_contents.clear_current_session_bins(scope="bin", layer_index=0, section_index=0, bin_index=0)
        self.assertEqual(1, bin_contents.pruneOldEvents(now - 180 * DAY))
        self.assertEqual(["e1", "e2"], sorted(p["piece_uuid"] for p in bin_contents.get_current_bin_pieces()))

    def test_pictures_older_versions_stored_are_cleared_once(self) -> None:
        bin_contents.record_piece_distribution({
            "uuid": "x", "destination_bin": [0, 0, 0], "distributed_at": time.time(), "thumbnail": "abc",
        })
        with db.connect(bin_contents._createTables) as conn:
            conn.execute("ALTER TABLE piece_events ADD COLUMN thumbnail TEXT")
            conn.execute("UPDATE piece_events SET thumbnail = 'base64...'")
            conn.commit()
        self.assertTrue(bin_contents.clearStoredImages(pause_s=0))
        with db.connect(bin_contents._createTables) as conn:
            self.assertIsNone(conn.execute("SELECT thumbnail FROM piece_events").fetchone()[0])
            self.assertEqual("1", bin_contents._get_meta(conn, bin_contents._META_KEY_IMAGES_CLEARED))
        snapshot = bin_contents.get_current_bin_contents_snapshot()
        self.assertNotIn("thumbnail", snapshot["bins"][0]["items"][0])


class VacuumTests(_DbTestCase):
    def _fill_and_empty(self) -> None:
        with db.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS filler (id INTEGER PRIMARY KEY, blob TEXT)")
            conn.executemany("INSERT INTO filler (blob) VALUES (?)", [("x" * 4000,) for _ in range(500)])
            conn.commit()
            conn.execute("DELETE FROM filler")
            conn.commit()

    def _maintenance(self, idle_s: float):
        gc = SimpleNamespace(runtime_stats=SimpleNamespace(is_running=False))
        m = storage_maintenance.StorageMaintenance(gc, None)
        m._last_busy = time.monotonic() - idle_s
        return m

    def test_the_switch_waits_for_an_idle_machine(self) -> None:
        self._fill_and_empty()
        self._maintenance(idle_s=10).runOnce()
        self.assertEqual(0, storage_maintenance.autoVacuumMode())

    def test_the_switch_waits_for_room_on_the_card(self) -> None:
        self._fill_and_empty()
        tight = SimpleNamespace(free=1024)
        with patch.object(storage_maintenance.shutil, "disk_usage", lambda _p: tight):
            self._maintenance(idle_s=3600).runOnce()
        self.assertEqual(0, storage_maintenance.autoVacuumMode())

    def _pages(self) -> int:
        with db.connect() as conn:
            return int(conn.execute("PRAGMA page_count").fetchone()[0])

    def test_idle_with_room_switches_then_deletes_give_pages_back(self) -> None:
        self._fill_and_empty()
        pages_before = self._pages()
        self._maintenance(idle_s=3600).runOnce()
        self.assertEqual(storage_maintenance.AUTO_VACUUM_INCREMENTAL, storage_maintenance.autoVacuumMode())
        self.assertLess(self._pages(), pages_before - 100)
        self._fill_and_empty()
        with db.connect() as conn:
            self.assertGreater(conn.execute("PRAGMA freelist_count").fetchone()[0], 100)
        self.assertGreater(storage_maintenance.incrementalVacuum(), 100)
        with db.connect() as conn:
            self.assertEqual(0, conn.execute("PRAGMA freelist_count").fetchone()[0])


class OnDiskBytesTests(unittest.TestCase):
    def test_files_count_whole_blocks(self) -> None:
        self.assertEqual(0, db.on_disk_bytes(0))
        self.assertEqual(4096, db.on_disk_bytes(1))
        self.assertEqual(4096, db.on_disk_bytes(4096))
        self.assertEqual(8192, db.on_disk_bytes(4097))
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE TABLE t (bytes INTEGER)")
            conn.executemany("INSERT INTO t VALUES (?)", [(2048,), (5000,), (None,)])
            self.assertEqual(4096 + 8192, conn.execute(f"SELECT SUM({db.on_disk_bytes_sql()}) FROM t").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
