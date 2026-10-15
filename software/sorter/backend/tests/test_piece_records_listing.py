"""The records list: a listing that holds still while the machine records more
pieces, pages that survive a piece changing under them, a search over what a
piece is called, the filters, and queries that stay on their indexes."""

from __future__ import annotations

import csv
import io
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
import piece_records
import sorting_runs
from server.routers import pieces

NOW = 1_760_000_000.0


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "local_state.sqlite"))
    monkeypatch.setattr(piece_records, "_estValue", lambda gc, part_id, color_id: None)


def _piece(
    uuid: str,
    seen_at: float,
    *,
    part_id: str = "3001",
    part_name: str = "Brick 2 x 4",
    color_id: str = "5",
    color_name: str = "Red",
    status: str = "classified",
    bin: tuple[int, int, int] | None = None,
    dead: bool = False,
) -> None:
    piece_records.recordPiece(
        {
            "uuid": uuid,
            "created_at": seen_at,
            "distributed_at": seen_at + 1,
            "classification_status": status,
            "part_id": part_id,
            "part_name": part_name,
            "color_id": color_id,
            "color_name": color_name,
            "destination_bin": list(bin) if bin else None,
            "dead": dead,
        }
    )


def _uuids(listing: dict) -> list[str]:
    return [item["uuid"] for item in listing["items"]]


def _many(count: int, start: int = 0) -> None:
    for i in range(start, start + count):
        _piece(f"p{i:03d}", NOW + i)


def test_a_listing_holds_still_while_the_machine_records_more() -> None:
    _many(7)
    first = piece_records.listPieces(None, limit=3)
    assert _uuids(first) == ["p006", "p005", "p004"]
    assert (first["total"], first["newer"], first["anchor"]) == (7, 0, 7)

    _many(2, start=7)  # the machine goes on sorting

    second = piece_records.listPieces(None, limit=3, cursor=int(first["next_cursor"]), anchor=first["anchor"])
    assert _uuids(second) == ["p003", "p002", "p001"]
    assert (second["total"], second["newer"]) == (7, 2)
    third = piece_records.listPieces(None, limit=3, cursor=int(second["next_cursor"]), anchor=first["anchor"])
    assert _uuids(third) == ["p000"]
    assert third["next_cursor"] is None

    # A fresh search starts at the newest again.
    fresh = piece_records.listPieces(None, limit=3)
    assert _uuids(fresh) == ["p008", "p007", "p006"]
    assert (fresh["total"], fresh["newer"]) == (9, 0)


def test_a_page_jumped_to_is_the_page_a_walk_reaches() -> None:
    _many(11)
    anchor = piece_records.listPieces(None, limit=1)["anchor"]
    walked: list[list[str]] = []
    cursor = None
    while True:
        page = piece_records.listPieces(None, limit=4, cursor=cursor, anchor=anchor)
        walked.append(_uuids(page))
        if page["next_cursor"] is None:
            break
        cursor = int(page["next_cursor"])
    assert [len(p) for p in walked] == [4, 4, 3]
    for index, expected in enumerate(walked):
        jumped = piece_records.listPieces(None, limit=4, offset=index * 4, anchor=anchor)
        assert _uuids(jumped) == expected


def test_oldest_first_walks_up_from_the_start() -> None:
    _many(5)
    first = piece_records.listPieces(None, limit=2, sort="oldest")
    assert _uuids(first) == ["p000", "p001"]
    second = piece_records.listPieces(
        None, limit=2, sort="oldest", cursor=int(first["next_cursor"]), anchor=first["anchor"]
    )
    assert _uuids(second) == ["p002", "p003"]


def test_a_page_may_hold_as_many_as_the_list_shows() -> None:
    _many(260)
    page = piece_records.listPieces(None, limit=250)
    assert len(page["items"]) == 250
    assert page["next_cursor"] is not None
    last = piece_records.listPieces(None, limit=250, cursor=int(page["next_cursor"]), anchor=page["anchor"])
    assert len(last["items"]) == 10 and last["next_cursor"] is None
    # Not without bound.
    assert len(piece_records.listPieces(None, limit=100000)["items"]) == 260


def test_the_counts_can_be_asked_without_a_page() -> None:
    _many(4)
    counts = piece_records.listPieces(None, limit=0, anchor=2)
    assert counts["items"] == [] and counts["next_cursor"] is None
    assert (counts["total"], counts["newer"], counts["anchor"]) == (2, 2, 2)


def test_a_piece_reviewed_while_paging_does_not_make_the_next_page_skip() -> None:
    _many(8)
    unreviewed = piece_records.listPieces(None, limit=3, reviewed=False)
    assert _uuids(unreviewed) == ["p007", "p006", "p005"]
    # The operator reviews two of the pieces on this page: they leave the filter.
    piece_records.setPieceCorrection("p007", set_part=True, part_correct=True)
    piece_records.setPieceCorrection("p006", set_part=True, part_correct=False)
    nxt = piece_records.listPieces(
        None, limit=3, reviewed=False, cursor=int(unreviewed["next_cursor"]), anchor=unreviewed["anchor"]
    )
    # The cursor starts after the last piece seen; an offset of 3 would skip two.
    assert _uuids(nxt) == ["p004", "p003", "p002"]
    by_offset = piece_records.listPieces(None, limit=3, reviewed=False, offset=3, anchor=unreviewed["anchor"])
    assert _uuids(by_offset) == ["p002", "p001", "p000"]


def test_a_search_finds_a_piece_by_what_it_is_called() -> None:
    _piece("aaaa1111-0000-0000-0000-000000000000", NOW, part_id="3023", part_name="Plate 1 x 2", color_id="34", color_name="Lime")
    _piece("bbbb2222-0000-0000-0000-000000000000", NOW + 1, part_id="3024", part_name="Plate 1 x 1", color_id="5", color_name="Red")
    _piece("cccc3333-0000-0000-0000-000000000000", NOW + 2, part_id="3626bpb0123", part_name="Minifigure, Head", color_id="34", color_name="Lime")
    _piece("dddd4444-0000-0000-0000-000000000000", NOW + 3, part_id="32054", part_name="Technic, Pin 100% Long_ish", color_id="11", color_name="Black")

    def found(query: str) -> list[str]:
        return [u[:4] for u in _uuids(piece_records.listPieces(None, query=query))]

    assert found("3023") == ["aaaa"]  # a part number, from its start
    assert found("302") == ["bbbb", "aaaa"]
    assert found("pbb") == []  # not from the middle of a part number
    assert found("plate") == ["bbbb", "aaaa"]  # a name, anywhere in it
    assert found("HEAD") == ["cccc"]  # in any case
    assert found("lime") == ["cccc", "aaaa"]  # a colour name
    assert found("plate lime") == ["aaaa"]  # every word must match something
    assert found("cccc33") == ["cccc"]  # a uuid, from its start
    assert found("ccc3") == []  # not from the middle of one
    assert found("100%") == ["dddd"]  # characters that mean something to LIKE are plain here
    assert found("%") == ["dddd"]
    assert found("_ish") == ["dddd"]
    assert found("a_") == []
    assert found("   ") == [u[:4] for u in _uuids(piece_records.listPieces(None))]


def test_the_filters() -> None:
    _piece("a", NOW, status="classified", bin=(0, 1, 2))
    _piece("b", NOW + 10, status="unknown")
    _piece("c", NOW + 20, status="classified", bin=(0, 1, 3))
    _piece("d", NOW + 30, status="pending", dead=True)
    piece_records.setPieceCorrection("c", set_color=True, color_corrected_id="11")

    def ids(**filters) -> list[str]:
        return _uuids(piece_records.listPieces(None, **filters))

    assert ids(status=["classified"]) == ["c", "a"]
    assert ids(status=["unknown", "pending"]) == ["d", "b"]
    assert ids(dead=True) == ["d"]
    assert ids(bin_ref=(0, 1, 2)) == ["a"]
    assert ids(bin_ref=(9, 9, 9)) == []
    assert ids(reviewed=True) == ["c"]
    assert ids(reviewed=False) == ["d", "b", "a"]
    assert ids(date_from=NOW + 5, date_to=NOW + 25) == ["c", "b"]
    assert ids(seen_ranges=[(NOW + 5, NOW + 25)]) == ["c", "b"]
    assert ids(seen_ranges=[(NOW - 1, NOW + 5), (NOW + 25, None)]) == ["d", "a"]
    assert ids(seen_ranges=[]) == []
    assert ids(status=["classified"], query="", bin_ref=(0, 1, 3)) == ["c"]


def test_a_run_and_a_lot_are_the_pieces_seen_while_they_lasted() -> None:
    lot = sorting_runs.createLot("Goodwill box")
    first = sorting_runs.startRun("First", lot_id=lot["id"], started_at=NOW)
    second = sorting_runs.startRun("Pass", lot_id=lot["id"], adds_to_lot=False, started_at=NOW + 100)
    third = sorting_runs.startRun("Second", lot_id=lot["id"], started_at=NOW + 200)
    for uuid, offset in (("a", 10), ("b", 50), ("c", 110), ("d", 210), ("e", 300)):
        _piece(uuid, NOW + offset)

    def ids(**which) -> list[str]:
        ranges = sorting_runs.seenRanges(**which)
        return _uuids(piece_records.listPieces(None, seen_ranges=ranges))

    assert ids(run_id=first["id"]) == ["b", "a"]
    assert ids(run_id=second["id"]) == ["c"]
    assert ids(run_id=third["id"]) == ["e", "d"]  # the current run has no end
    assert ids(lot_id=lot["id"]) == ["e", "d", "b", "a"]  # the lot counts the runs that add to it
    with pytest.raises(sorting_runs.RunError):
        sorting_runs.seenRanges(run_id="missing")
    with pytest.raises(sorting_runs.RunError):
        sorting_runs.seenRanges(lot_id="missing")


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(pieces.router)
    return TestClient(app)


def test_the_endpoint_names_the_anchor_and_what_came_after_it() -> None:
    _many(5)
    client = _client()
    first = client.get("/api/pieces", params={"limit": 2}).json()
    assert [i["uuid"] for i in first["items"]] == ["p004", "p003"]
    assert (first["total"], first["anchor"], first["newer"]) == (5, 5, 0)
    _many(3, start=5)
    again = client.get(
        "/api/pieces",
        params={"limit": 2, "cursor": first["next_cursor"], "anchor": first["anchor"]},
    ).json()
    assert [i["uuid"] for i in again["items"]] == ["p002", "p001"]
    assert (again["total"], again["newer"]) == (5, 3)
    counts = client.get("/api/pieces", params={"limit": 0, "anchor": first["anchor"]}).json()
    assert (counts["items"], counts["newer"]) == ([], 3)


def test_the_endpoint_filters_by_search_status_and_sorting_run() -> None:
    lot = sorting_runs.createLot("Box")
    run = sorting_runs.startRun("Run", lot_id=lot["id"], started_at=NOW)
    _piece("a", NOW + 1, part_name="Plate 1 x 2", color_name="Lime")
    _piece("b", NOW + 2, part_name="Plate 1 x 2", color_name="Red", status="unknown")
    # Recorded last, seen before the run: the list is in the order of recording.
    _piece("c", NOW - 50, part_name="Plate 1 x 2", color_name="Lime")
    client = _client()

    def uuids(**params) -> list[str]:
        response = client.get("/api/pieces", params=params)
        assert response.status_code == 200, response.text
        return [i["uuid"] for i in response.json()["items"]]

    assert uuids(q="plate lime") == ["c", "a"]
    assert uuids(q="plate", status="unknown") == ["b"]
    assert uuids(q="plate", sorting_run_id=run["id"]) == ["b", "a"]
    assert uuids(lot_id=lot["id"]) == ["b", "a"]
    assert uuids(bin_x=0, bin_y=0, bin_z=0) == []
    assert client.get("/api/pieces", params={"lot_id": "missing"}).status_code == 404
    assert client.get("/api/pieces", params={"sort": "sideways"}).status_code == 400


def test_a_piece_still_in_memory_shows_what_the_operator_answered(monkeypatch) -> None:
    _piece("live", NOW, part_name="Plate", color_name="Lime")
    piece_records.setPieceCorrection(
        "live",
        set_part=True,
        part_correct=False,
        set_rejection_reasons=True,
        rejection_reasons=["not_lego"],
    )
    payload = {
        "uuid": "live",
        "created_at": NOW,
        "updated_at": NOW + 1,
        "stage": "distributed",
        "classification_status": "classified",
    }
    stats = SimpleNamespace(lookupKnownObject=lambda uuid: payload if uuid == "live" else None)
    monkeypatch.setattr(pieces.shared_state, "gc_ref", SimpleNamespace(runtime_stats=stats))
    monkeypatch.setattr(pieces.piece_predictions, "recent", lambda uuid: [])

    answer = _client().get("/api/pieces/live").json()

    assert answer["origin"] == "memory"
    assert answer["summary"]["part_correct"] is False
    assert answer["summary"]["rejection_reasons"] == ["not_lego"]


def test_the_csv_is_the_list_it_was_asked_for() -> None:
    _piece("a", NOW, part_name="Plate", color_name="Lime")
    _piece("b", NOW + 1, part_name="Brick", color_name="Lime")
    anchor = piece_records.listPieces(None, limit=1)["anchor"]
    _piece("c", NOW + 2, part_name="Plate", color_name="Lime")  # after the listing's anchor
    response = _client().get("/api/pieces/export.csv", params={"q": "plate", "anchor": anchor})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [r["uuid"] for r in rows] == ["a"]


class _Plans:
    """Runs a listing and says how SQLite reads the page's rows."""

    def __init__(self, monkeypatch) -> None:
        self.statements: list[str] = []
        real = piece_records._connection

        @contextmanager
        def traced():
            with real() as conn:
                conn.set_trace_callback(self.statements.append)
                yield conn

        monkeypatch.setattr(piece_records, "_connection", traced)
        self._real = real

    def of(self, **filters) -> str:
        self.statements.clear()
        piece_records.listPieces(None, limit=50, **filters)
        page = [s for s in self.statements if s.startswith("SELECT id FROM piece_records")]
        assert page, self.statements
        with self._real() as conn:
            plan = conn.execute("EXPLAIN QUERY PLAN " + page[0]).fetchall()
        return " | ".join(str(row["detail"]) for row in plan)


def _grow(rows: int = 3000) -> None:
    with db.connect(piece_records._createTables) as conn:
        conn.executemany(
            "INSERT INTO piece_records (uuid, seen_at, classification_status, part_id, part_name, color_name, "
            "bin_x, bin_y, bin_z, dead, correction_updated_at) VALUES (?, ?, 'classified', ?, ?, 'Red', ?, ?, ?, 0, ?)",
            [
                (f"u{i}", NOW + i, str(3000 + i % 50), f"Brick {i % 50}", i % 3, i % 5, i % 7, NOW if i % 97 == 0 else None)
                for i in range(rows)
            ],
        )
        conn.commit()


def test_a_page_is_read_by_the_index_that_fits_the_filters(monkeypatch) -> None:
    _grow()
    plans = _Plans(monkeypatch)

    newest = plans.of()
    assert "USE TEMP B-TREE" not in newest and "SCAN piece_records" not in newest, newest

    by_bin = plans.of(bin_ref=(1, 2, 3))
    assert "idx_piece_records_bin" in by_bin and "USE TEMP B-TREE" not in by_bin, by_bin

    reviewed = plans.of(reviewed=True)
    assert "idx_piece_records_reviewed" in reviewed and "USE TEMP B-TREE" not in reviewed, reviewed

    # A search reads in id order, newest first, and stops at the page: it scans
    # but never sorts.
    searched = plans.of(query="brick 7")
    assert "USE TEMP B-TREE" not in searched, searched
