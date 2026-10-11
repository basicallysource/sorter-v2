from __future__ import annotations

import time

import pytest

import piece_records
import sorting_runs


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
