"""piece_images is ground truth (C4 burst -> Hive -> training data). The
piece-link model's guesses must be structurally unable to enter it — that
failing once put crops of entirely different pieces into Hive's labeling
galleries as 'this IS the piece'."""

import base64
import importlib
import time

import pytest

import piece_image_store


FAKE_JPEG = base64.b64encode(b"\xff\xd8\xff\xe0 not really a jpeg").decode()


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import local_state

    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "local_state.sqlite"))
    importlib.reload(local_state)
    importlib.reload(piece_image_store)
    yield piece_image_store
    importlib.reload(local_state)
    importlib.reload(piece_image_store)


def _drain(store_mod, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if store_mod._queue.empty():
            time.sleep(0.1)
            return
        time.sleep(0.02)


class TestGroundTruthGuard:
    def test_link_match_entries_never_reach_piece_images(self, store) -> None:
        # Even if a caller wrongly puts link guesses into recognition_image_set
        # (exactly the bug that poisoned Hive), the store refuses them.
        store.enqueueKnownObjectImages(
            {
                "uuid": "piece-1",
                "recognition_image_set": [
                    {"image": FAKE_JPEG, "source": "c4_burst", "channel": 4, "ts": 1.0},
                    {"image": FAKE_JPEG, "source": "link_match", "channel": 2, "ts": 0.5},
                    {"image": FAKE_JPEG, "source": "link_match", "channel": 3, "ts": 0.6},
                ],
            }
        )
        _drain(store)
        rows = store.listPieceImages("piece-1")
        assert [r["source"] for r in rows] == ["c4_burst"]

    def test_link_images_go_to_their_own_table_and_directory(self, store) -> None:
        store.enqueueKnownObjectLinkImages(
            {
                "uuid": "piece-2",
                "link_match_image_set": [
                    {
                        "image": FAKE_JPEG,
                        "channel": 2,
                        "ts": 1.0,
                        "score": 0.97,
                        "used": True,
                    },
                    {"image": FAKE_JPEG, "channel": 3, "ts": 1.1, "score": 0.66},
                ],
            }
        )
        _drain(store)
        link_rows = store.listPieceLinkImages("piece-2")
        assert len(link_rows) == 2
        assert link_rows[0]["score"] == pytest.approx(0.97)
        assert link_rows[0]["used"] is True
        # Nothing leaked into the ground-truth table.
        assert store.listPieceImages("piece-2") == []
        # Files live in the separate tree with the distinct name shape.
        path = store.getLinkImageFileById(link_rows[0]["id"])
        assert path is not None
        assert "piece_link_images" in str(path)
        assert path.name.endswith("_linkguess.jpg")
        assert not (store.piece_images_dir() / "piece-2").exists()

    def test_link_rows_have_no_sync_surface(self, store) -> None:
        # The hive uploader iterates listImagesAfter (piece_images only); link
        # rows must be invisible to it entirely.
        store.enqueueKnownObjectLinkImages(
            {
                "uuid": "piece-3",
                "link_match_image_set": [
                    {"image": FAKE_JPEG, "channel": 2, "ts": 1.0, "score": 0.9}
                ],
            }
        )
        _drain(store)
        assert store.listPieceLinkImages("piece-3")
        assert store.listImagesAfter(0, 100) == []
        assert store.getMaxImageId() == 0
