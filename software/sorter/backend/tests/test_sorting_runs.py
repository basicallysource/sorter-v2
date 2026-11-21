from __future__ import annotations

import threading
import time

import pytest

import piece_records
import sorting_runs
from server import hive_sync


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "local_state.sqlite"))


def _piece(seen_at: float) -> None:
    piece_records.recordPiece(
        {"uuid": f"p-{seen_at}", "classification_status": "classified", "created_at": seen_at},
        run_id="process",
    )


def test_a_run_lasts_until_the_next_starts_and_a_pass_does_not_add_to_its_lot() -> None:
    now = time.time()
    lot = sorting_runs.createLot("Goodwill box")
    first = sorting_runs.startRun("Goodwill", lot_id=lot["id"], started_at=now - 1000)
    for t in (now - 900, now - 800, now - 700):
        _piece(t)
    second = sorting_runs.startRun("Finer pass", lot_id=lot["id"], adds_to_lot=False, started_at=now - 500)
    for t in (now - 400, now - 300):
        _piece(t)

    runs = {r["name"]: r for r in sorting_runs.listRuns()}
    assert runs["Goodwill"]["pieces"] == 3
    assert runs["Goodwill"]["ended_at"] == second["started_at"]
    assert runs["Finer pass"]["pieces"] == 2
    assert runs["Finer pass"]["is_current"] and runs["Finer pass"]["ended_at"] is None
    assert not runs["Goodwill"]["is_current"]
    assert first["lot_name"] == "Goodwill box"

    [goodwill] = sorting_runs.listLots()
    assert (goodwill["pieces"], goodwill["runs"], goodwill["passes"]) == (3, 1, 1)


def test_pieces_before_the_first_run_belong_to_none() -> None:
    now = time.time()
    _piece(now - 100)
    sorting_runs.startRun("Later", started_at=now - 50)
    _piece(now - 10)
    [run] = sorting_runs.listRuns()
    assert run["pieces"] == 1


def test_a_run_names_a_lot_that_exists() -> None:
    with pytest.raises(sorting_runs.RunError):
        sorting_runs.startRun("Nowhere", lot_id="missing")
    with pytest.raises(sorting_runs.RunError):
        sorting_runs.startRun("  ")


def test_changing_a_run_to_a_pass_takes_its_pieces_off_the_lot() -> None:
    now = time.time()
    lot = sorting_runs.createLot("Order 42")
    run = sorting_runs.startRun("Order", lot_id=lot["id"], started_at=now - 100)
    _piece(now - 50)
    assert sorting_runs.getLot(lot["id"])["pieces"] == 1
    sorting_runs.updateRun(run["id"], adds_to_lot=False)
    assert sorting_runs.getLot(lot["id"])["pieces"] == 0
    sorting_runs.updateRun(run["id"], lot_id=None)
    assert sorting_runs.getRun(run["id"])["lot_id"] is None


def test_a_lot_shows_a_part_seen_again_in_a_later_pass() -> None:
    now = time.time()
    lot = sorting_runs.createLot("Goodwill box")
    first = sorting_runs.startRun("Goodwill", lot_id=lot["id"], started_at=now - 1000)
    for i, t in enumerate((now - 900, now - 800)):
        piece_records.recordPiece(
            {"uuid": f"a{i}", "classification_status": "classified", "created_at": t, "part_id": "3001", "color_id": "5"}
        )
    second = sorting_runs.startRun("Finer pass", lot_id=lot["id"], adds_to_lot=False, started_at=now - 500)
    piece_records.recordPiece(
        {"uuid": "b0", "classification_status": "classified", "created_at": now - 400, "part_id": "3001", "color_id": "5"}
    )

    result = sorting_runs.lotParts(lot["id"])
    assert [r["name"] for r in result["runs"]] == ["Goodwill", "Finer pass"]
    [brick] = result["parts"]
    assert brick["counts"] == {first["id"]: 2, second["id"]: 1}
    assert brick["in_lot"] == 2


class _FakeHive:
    """Keeps the last set of lots and runs sent, and answers with its version."""

    def __init__(self) -> None:
        self.sets: list[dict] = []

    def pushSortingRuns(self, sorting_set: dict) -> int:
        self.sets.append(sorting_set)
        return sorting_set["version"]


def _syncer(client: _FakeHive):
    syncer = hive_sync._TargetSyncer.__new__(hive_sync._TargetSyncer)
    syncer._id = "t"
    syncer._client = client
    syncer._gate = hive_sync._ConcurrencyGate(1, 1, lambda: False)
    syncer._wm = {t: 0 for t in hive_sync.DATA_TYPES}
    syncer._stop = threading.Event()
    return syncer


def test_lots_and_runs_go_to_hive_whole_when_they_change() -> None:
    client = _FakeHive()
    syncer = _syncer(client)
    # Nothing to send before there is a lot or a run.
    assert not syncer._drainSortingRuns()

    lot = sorting_runs.createLot("Big box")
    run = sorting_runs.startRun("Big box", lot_id=lot["id"], started_at=time.time() - 100)
    assert syncer._drainSortingRuns()
    [sent] = client.sets
    assert [(l["id"], l["name"]) for l in sent["lots"]] == [(lot["id"], "Big box")]
    assert [(r["id"], r["lot_id"], r["adds_to_lot"]) for r in sent["runs"]] == [(run["id"], lot["id"], True)]
    # Hive has this set: nothing goes until something changes.
    assert not syncer._drainSortingRuns()

    # Taken out of its lot: the whole set goes again, with a new version.
    sorting_runs.updateRun(run["id"], lot_id=None, adds_to_lot=False)
    assert syncer._drainSortingRuns()
    assert client.sets[-1]["runs"][0]["lot_id"] is None
    assert client.sets[-1]["version"] != sent["version"]


def _binned(uuid: str, seen_at: float, place: tuple[int, int, int], part_id: str = "3001") -> None:
    piece_records.recordPiece(
        {
            "uuid": uuid,
            "classification_status": "classified",
            "created_at": seen_at,
            "part_id": part_id,
            "color_id": "5",
            "destination_bin": list(place),
        }
    )


def test_pieces_sent_back_leave_their_lot_and_count_again_when_seen_next() -> None:
    now = time.time()
    lot = sorting_runs.createLot("Second-hand box")
    run = sorting_runs.startRun("Second-hand box", lot_id=lot["id"], started_at=now - 1000)
    _binned("a", now - 900, (0, 1, 0))
    _binned("b", now - 890, (0, 1, 2))
    _binned("c", now - 880, (0, 1, 3), part_id="3003")
    _binned("d", now - 870, (1, 1, 0), part_id="3003")
    sorting_runs.startRun("finer pass", lot_id=lot["id"], adds_to_lot=False, started_at=now - 500)
    _binned("e", now - 400, (0, 1, 0))
    assert sorting_runs.getLot(lot["id"])["pieces"] == 4

    answer = sorting_runs.sendBack(lot["id"], [(0, 1, 0), (0, 1, 1), (0, 1, 2)], " being sorted again ")
    assert answer["sent_back"] == 2
    assert answer["lot"]["pieces"] == 2
    assert (sorting_runs.getRun(run["id"])["pieces"], sorting_runs.getRun(run["id"])["distributed_pieces"]) == (2, 2)
    [brick] = [p for p in sorting_runs.lotParts(lot["id"])["parts"] if p["part_id"] == "3001"]
    assert brick["in_lot"] == 0
    # The records stay; a listing of the lot leaves them out, as its count does.
    assert len(piece_records.listPieces(None)["items"]) == 5
    lot_ranges = sorting_runs.seenRanges(lot_id=lot["id"])
    assert sorted(p["uuid"] for p in piece_records.listPieces(None, seen_ranges=lot_ranges)["items"]) == ["c", "d"]
    with piece_records._connection() as conn:
        rows = conn.execute("SELECT piece_uuid, lot_id, note FROM sent_back_pieces ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("a", lot["id"], "being sorted again"), ("b", lot["id"], "being sorted again")]

    # Nothing is sent back twice, and the pass's piece in the same bin was never the lot's.
    assert sorting_runs.sendBack(lot["id"], [(0, 1, 0)])["sent_back"] == 0
    # Sorted again in an adding run: they count once more.
    sorting_runs.startRun("Second-hand box 2", lot_id=lot["id"], started_at=now - 100)
    _binned("a2", now - 50, (2, 0, 0))
    _binned("b2", now - 40, (0, 1, 2))
    assert sorting_runs.getLot(lot["id"])["pieces"] == 4

    with pytest.raises(sorting_runs.RunError):
        sorting_runs.sendBack("missing", [(0, 1, 0)])
    with pytest.raises(sorting_runs.RunError):
        sorting_runs.sendBack(lot["id"], [])


class _FakeSentBackHive:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def pushSentBackPieces(self, rows: list[dict]) -> int:
        self.rows.extend(rows)
        return max(r["local_id"] for r in rows)


def test_pieces_sent_back_go_to_hive_once() -> None:
    now = time.time()
    lot = sorting_runs.createLot("Big box")
    sorting_runs.startRun("Big box", lot_id=lot["id"], started_at=now - 100)
    _binned("a", now - 50, (0, 0, 0))
    client = _FakeSentBackHive()
    syncer = _syncer(client)
    assert not syncer._drainSentBack()
    sorting_runs.sendBack(lot["id"], [(0, 0, 0)], "back in the hopper")
    assert syncer._drainSentBack()
    [row] = client.rows
    assert (row["piece_uuid"], row["lot_id"], row["note"], row["local_id"]) == ("a", lot["id"], "back in the hopper", 1)
    assert not syncer._drainSentBack()
