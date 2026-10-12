"""The labeling queue and everything served from it: the worker that keeps it,
the piece grid's sort orders and cursor paging, the labelable counts, and the
other per-piece results Hive now keeps instead of recomputing per request."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.labeling_queue import LabelingQueueEntry
from app.models.machine import Machine
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.machine_stats_cache import MachineStatsCache
from app.models.piece_color_label import PieceColorLabel
from app.models.piece_crop_link import PieceCropLink
from app.models.piece_model_output import PieceColorGuess, PieceLinkScore
from app.models.piece_part_label import PiecePartLabel
from app.models.piece_rejection import PieceRejection
from app.models.sample import Sample
from app.models.upload_session import UploadSession
from app.models.user import User
from app.routers import piece_color_labels as labeling_router
from app.services import labeling_queue, link_predictor, piece_color_guess, piece_link_scores
from tests.conftest import refresh_stats

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _now() -> datetime:
    # For rows that "just synced": the worker looks back from its last pass, so
    # these must be stamped when the test runs, not when the module loaded.
    return datetime.now(timezone.utc)


# --- Fixtures --------------------------------------------------------------------


def _user(db: Session, email: str, role: str = "member") -> User:
    user = User(email=email, display_name=email, role=role)
    db.add(user)
    db.commit()
    return user


def _machine(db: Session, owner_id, name: str) -> UUID:
    machine = Machine(owner_id=owner_id, token_hash=f"hash-{name}", token_prefix=name[:8], name=name)
    db.add(machine)
    db.commit()
    return machine.id


def _piece(
    db: Session,
    machine_id: UUID,
    puid: str,
    arrival: datetime,
    *,
    image: bool = True,
    dead: bool = False,
    part_id: str | None = "3001",
    color_id: str | None = "11",
    color_confidence: float | None = None,
    candidate: bool = False,
    created_at: datetime | None = None,
    local_id: int = 1,
) -> None:
    db.add(
        MachinePiece(
            machine_id=machine_id,
            piece_uuid=puid,
            local_id=local_id,
            seen_at=arrival,
            recorded_at=arrival + timedelta(seconds=5),
            dead=dead,
            part_id=part_id,
            color_id=color_id,
            color_confidence=color_confidence,
            created_at=created_at or NOW - timedelta(days=2),
        )
    )
    if image:
        db.add(
            MachinePieceImage(
                machine_id=machine_id,
                piece_uuid=puid,
                seq=0,
                local_id=local_id,
                channel=4,
                image_key=f"{machine_id}/pieces/{puid}/00.jpg",
                created_at=created_at or NOW - timedelta(days=2),
            )
        )
    if candidate:
        _crop(db, machine_id, arrival - timedelta(seconds=10), created_at=created_at or NOW - timedelta(days=2))
    db.commit()


_crop_ids = iter(range(1, 10_000))


def _crop(db: Session, machine_id: UUID, ts: datetime, created_at: datetime | None = None) -> int:
    local_id = next(_crop_ids)
    db.add(
        MachineChannelCrop(
            machine_id=machine_id,
            local_id=local_id,
            channel=3,
            ts=ts,
            image_key=f"{machine_id}/crops/{local_id}.jpg",
            created_at=created_at or _now(),
        )
    )
    db.commit()
    return local_id


def _me(db: Session) -> User:
    return db.query(User).filter(User.email == "member@test.com").one()


@pytest.fixture()
def fleet(client: TestClient, db: Session, test_user: dict) -> dict:
    """Two machines of the logged-in member and one of somebody else, with
    pieces spread over every case the grid distinguishes."""
    me = _me(db)
    other = _user(db, "other@test.com")
    third = _user(db, "third@test.com")
    m1 = _machine(db, me.id, "mine-one")
    m2 = _machine(db, me.id, "mine-two")
    m3 = _machine(db, me.id, "mine-three")
    foreign = _machine(db, other.id, "theirs")

    base = NOW - timedelta(hours=6)
    spec = []
    # 18 labelable pieces two minutes apart (so crop windows never overlap),
    # alternating machines; p05 and p06 share an arrival instant across machines
    # to exercise the cursor's tie-break.
    for i in range(18):
        arrival = base + timedelta(minutes=2 * i)
        if i == 6:
            arrival = base + timedelta(minutes=2 * 5)
        spec.append(
            dict(
                puid=f"p{i:02d}",
                machine=m1 if i % 2 == 0 else m2,
                arrival=arrival,
                candidate=i % 3 != 0,
                part_id=None if i % 4 == 0 else "3001",
                color_id=["11", "5", "86"][i % 3],
                color_confidence=None if i % 5 == 0 else round(0.3 + 0.03 * i, 3),
            )
        )
    for s in spec:
        _piece(
            db,
            s["machine"],
            s["puid"],
            s["arrival"],
            candidate=s["candidate"],
            part_id=s["part_id"],
            color_id=s["color_id"],
            color_confidence=s["color_confidence"],
        )
    # Not labelable: dead, no crop in storage, too young; and a foreign machine.
    _piece(db, m1, "dead", base, dead=True)
    _piece(db, m1, "no-image", base, image=False)
    _piece(db, m1, "young", NOW - timedelta(minutes=2))
    _piece(db, foreign, "foreign", base)

    # Labels: colour counts 1..3 on a few, some by me; crop links; part labels.
    def color(puid, mid, who):
        db.add(PieceColorLabel(machine_id=mid, piece_uuid=puid, labeler_id=who.id, color_id=11))

    by = {s["puid"]: s["machine"] for s in spec}
    color("p01", by["p01"], me)
    color("p02", by["p02"], other)
    color("p02", by["p02"], third)
    color("p03", by["p03"], other)
    color("p03", by["p03"], third)
    color("p03", by["p03"], me)
    color("p07", by["p07"], other)
    db.add(PieceCropLink(machine_id=by["p04"], piece_uuid="p04", labeler_id=other.id))
    db.add(PieceCropLink(machine_id=by["p05"], piece_uuid="p05", labeler_id=me.id))
    db.add(PieceCropLink(machine_id=by["p05"], piece_uuid="p05", labeler_id=other.id))
    db.add(PiecePartLabel(machine_id=by["p08"], piece_uuid="p08", labeler_id=other.id, part_num="3001"))
    db.add(PiecePartLabel(machine_id=by["p12"], piece_uuid="p12", labeler_id=me.id, part_num="3001"))
    # I rejected p09: it leaves my queue.
    db.add(PieceRejection(machine_id=by["p09"], piece_uuid="p09", labeler_id=me.id, reasons=["no_piece"]))
    db.commit()

    # A third machine of mine, interleaved in time with the others, labeled
    # and unlabeled, with and without candidates: a machine filter that leaked
    # in any sort, tier or page would show one of these.
    for j in range(6):
        arrival = base + timedelta(minutes=2 * j + 1)
        puid = f"q{j:02d}"
        _piece(
            db,
            m3,
            puid,
            arrival,
            candidate=j % 2 == 0,
            part_id=None if j % 3 == 0 else "3001",
            color_id=["11", "5", "86"][j % 3],
            color_confidence=None if j == 5 else round(0.2 + 0.05 * j, 3),
        )
        spec.append(
            dict(
                puid=puid,
                machine=m3,
                arrival=arrival,
                candidate=j % 2 == 0,
                part_id=None if j % 3 == 0 else "3001",
                color_id=["11", "5", "86"][j % 3],
                color_confidence=None if j == 5 else round(0.2 + 0.05 * j, 3),
            )
        )
    db.add(PieceColorLabel(machine_id=m3, piece_uuid="q01", labeler_id=other.id, color_id=5))
    db.add(PieceColorLabel(machine_id=m3, piece_uuid="q02", labeler_id=me.id, color_id=5))
    db.add(PieceCropLink(machine_id=m3, piece_uuid="q03", labeler_id=other.id))
    db.add(PiecePartLabel(machine_id=m3, piece_uuid="q03", labeler_id=other.id, part_num="3001"))
    db.commit()

    labeling_queue.run_pass(db)
    return {"spec": spec, "m1": m1, "m2": m2, "m3": m3, "foreign": foreign, "me": me, "other": other}


def _expected(db: Session, fleet: dict, sort: str, *, machine_id=None, with_candidates=False, rare=None) -> list[str]:
    machines = None if machine_id is None else ({machine_id} if isinstance(machine_id, UUID) else set(machine_id))
    """The grid's order computed the slow, obvious way, for comparison."""
    me = fleet["me"]
    entries = {(e.machine_id, e.piece_uuid): e for e in db.query(LabelingQueueEntry)}
    rows = []
    for s in fleet["spec"]:
        key = (s["machine"], s["puid"])
        if s["puid"] == "p09":  # rejected by me
            continue
        if machines is not None and s["machine"] not in machines:
            continue
        has_c = entries[key].has_candidates
        if with_candidates and not has_c:
            continue

        def n(model):
            return db.query(model).filter(model.machine_id == s["machine"], model.piece_uuid == s["puid"]).count()

        mine = (
            db.query(PieceColorLabel)
            .filter(
                PieceColorLabel.machine_id == s["machine"],
                PieceColorLabel.piece_uuid == s["puid"],
                PieceColorLabel.labeler_id == me.id,
            )
            .count()
            > 0
        )
        rows.append(dict(s, has_c=has_c, color=n(PieceColorLabel), crop=n(PieceCropLink), part=n(PiecePartLabel), mine=mine))

    if sort == "unidentified":
        rows = [r for r in rows if r["part_id"] is None]
    if sort == "rare_color":
        rows = [r for r in rows if r["color_id"] in rare]

    # Newest first, ties by machine then piece, descending: the secondary order
    # of every sort but "oldest". Python's sort is stable, so the primary key is
    # applied after.
    oldest = sort == "oldest"
    rows.sort(key=lambda r: (r["arrival"], r["machine"], r["puid"]), reverse=not oldest)
    primary = {
        "priority": lambda r: (not r["has_c"], r["color"]),
        "least_color": lambda r: r["color"],
        "most_color": lambda r: -r["color"],
        "least_crop": lambda r: r["crop"],
        "most_crop": lambda r: -r["crop"],
        "least_part": lambda r: r["part"],
        "most_part": lambda r: -r["part"],
        "needs_me": lambda r: (r["mine"], r["color"]),
        "unidentified": lambda r: r["part"],
        "rare_color": lambda r: (r["color_confidence"] is None, r["color_confidence"] or 0.0),
    }.get(sort)
    if primary is not None:
        rows.sort(key=primary)
    return [r["puid"] for r in rows]


def _walk(client: TestClient, sort: str, limit: int, machines=None, **params) -> list[str]:
    seen: list[str] = []
    cursor = None
    for _ in range(100):
        query = {"sort": sort, "limit": limit, **params}
        if machines is not None:
            query["machine_id"] = [str(m) for m in machines]
        if cursor:
            query["cursor"] = cursor
        resp = client.get("/api/labeling/pieces", params=query)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["items"]) <= limit
        if machines is not None:
            allowed = {str(m) for m in machines}
            assert all(it["machine_id"] in allowed for it in body["items"]), body["items"]
        seen.extend(it["piece_uuid"] for it in body["items"])
        assert body["has_more"] == (body["next_cursor"] is not None)
        if not body["has_more"]:
            return seen
        cursor = body["next_cursor"]
    raise AssertionError("paging never ended")


# --- The worker ---------------------------------------------------------------------


def test_queue_holds_exactly_the_labelable_pieces(db, fleet):
    queued = {e.piece_uuid: e for e in db.query(LabelingQueueEntry)}
    expected = {s["puid"] for s in fleet["spec"]} | {"young", "foreign"}
    assert set(queued) == expected  # dead and image-less pieces never enter
    for s in fleet["spec"]:
        entry = queued[s["puid"]]
        assert entry.has_candidates == s["candidate"], s["puid"]
        assert entry.unidentified == (s["part_id"] is None)
        assert entry.color_confidence == s["color_confidence"]


def test_incremental_pass_picks_up_new_pieces_late_images_and_late_crops(db, fleet):
    m1 = fleet["m1"]
    arrival = NOW - timedelta(hours=1)
    # A record that arrives before its crop is in storage stays out...
    _piece(db, m1, "late", arrival, image=False, created_at=_now())
    labeling_queue.run_pass(db)
    assert db.get(LabelingQueueEntry, (m1, "late")) is None
    # ...until the crop syncs.
    db.add(
        MachinePieceImage(machine_id=m1, piece_uuid="late", seq=0, local_id=9, image_key="k.jpg", created_at=_now())
    )
    db.commit()
    labeling_queue.run_pass(db)
    entry = db.get(LabelingQueueEntry, (m1, "late"))
    assert entry is not None and entry.has_candidates is False

    # A channel crop that syncs later, inside the piece's arrival window, gives it candidates.
    _crop(db, m1, arrival - timedelta(seconds=30))
    labeling_queue.run_pass(db)
    db.refresh(entry)
    assert entry.has_candidates is True

    # One outside every window changes nothing.
    p00 = db.get(LabelingQueueEntry, (m1, "p00"))
    assert p00.has_candidates is False
    _crop(db, m1, p00.arrival_at.replace(tzinfo=timezone.utc) - timedelta(seconds=61))
    labeling_queue.run_pass(db)
    db.refresh(p00)
    assert p00.has_candidates is False


def test_a_piece_that_dies_leaves_the_grid_at_once_and_the_queue_at_reconcile(client, db, fleet):
    m1 = fleet["m1"]
    db.query(MachinePiece).filter(MachinePiece.machine_id == m1, MachinePiece.piece_uuid == "p00").update({"dead": True})
    db.commit()
    assert "p00" not in _walk(client, "recent", 50)
    assert db.get(LabelingQueueEntry, (m1, "p00")) is not None
    labeling_queue.run_pass(db, now=datetime.now(timezone.utc) + timedelta(days=2))  # reconcile is due
    assert db.get(LabelingQueueEntry, (m1, "p00")) is None


# --- The grid -----------------------------------------------------------------------


SORTS = [
    "priority",
    "recent",
    "oldest",
    "least_color",
    "most_color",
    "least_crop",
    "most_crop",
    "least_part",
    "most_part",
    "needs_me",
    "unidentified",
]


@pytest.mark.parametrize("sort", SORTS)
@pytest.mark.parametrize("limit", [1, 4, 200])
def test_every_sort_pages_through_the_same_order(client, db, fleet, sort, limit):
    assert _walk(client, sort, limit) == _expected(db, fleet, sort)


@pytest.mark.parametrize("sort", SORTS + ["rare_color"])
@pytest.mark.parametrize("which", ["one", "two"])
@pytest.mark.parametrize("candidates", [False, True])
def test_a_machine_filter_never_returns_another_machines_piece(client, db, fleet, monkeypatch, sort, which, candidates):
    """Every sort, every tier of it, every page: one machine or several, with
    and without the candidates filter, only the chosen machines' pieces."""
    rare = {"5", "86"}
    monkeypatch.setattr(labeling_router, "_rare_candidate_color_ids", lambda *a: rare)
    machines = [fleet["m2"]] if which == "one" else [fleet["m1"], fleet["m3"]]
    params = {"with_candidates": "true"} if candidates else {}
    got = _walk(client, sort, 3, machines=machines, **params)
    expected = _expected(db, fleet, sort, machine_id=machines, with_candidates=candidates, rare=rare)
    assert got == expected
    if which == "two":
        assert got  # the fixture gives the two-machine case something in every sort


def test_admin_machine_filter_keeps_out_the_rest_of_the_fleet(client, db, fleet):
    me = _me(db)
    me.role = "admin"
    db.commit()
    got = _walk(client, "recent", 4, machines=[fleet["m1"]])
    assert "foreign" not in got and not any(p.startswith("q") for p in got)


def test_counts_follow_the_machine_filter(client, db, fleet):
    one = client.get("/api/labeling/stats", params={"machine_id": [str(fleet["m3"])]}).json()
    assert one["total_labelable"] == 6
    two = client.get("/api/labeling/stats", params={"machine_id": [str(fleet["m1"]), str(fleet["m3"])]}).json()
    assert two["total_labelable"] == 9 + 6
    assert two["color_labeled_pieces"] == 3  # p02 on mine-one; q01 and q02 on mine-three


def test_rare_color_sort(client, db, fleet, monkeypatch):
    rare = {"5", "86"}
    monkeypatch.setattr(labeling_router, "_rare_candidate_color_ids", lambda *a: rare)
    assert _walk(client, "rare_color", 2) == _expected(db, fleet, "rare_color", rare=rare)


def test_labeling_while_paging_skips_nothing(client, db, fleet):
    first = client.get("/api/labeling/pieces", params={"sort": "least_color", "limit": 5}).json()
    # Label the first piece served: it moves to the labeled tier, which comes later.
    top = first["items"][0]
    db.add(
        PieceColorLabel(
            machine_id=UUID(top["machine_id"]), piece_uuid=top["piece_uuid"], labeler_id=fleet["other"].id, color_id=5
        )
    )
    db.commit()
    rest = _walk_from(client, "least_color", 5, first["next_cursor"])
    served = [it["piece_uuid"] for it in first["items"]] + rest
    # Keyset paging carries on from the last piece served, so the label shifts
    # nothing under the reader: every piece is still served, and the one just
    # labeled shows up once more, in its new place among the labeled.
    assert set(served) == set(_expected(db, fleet, "least_color"))
    assert served.count(top["piece_uuid"]) == 2
    assert len(served) == len(set(served)) + 1


def _walk_from(client, sort, limit, cursor):
    seen = []
    while cursor:
        body = client.get("/api/labeling/pieces", params={"sort": sort, "limit": limit, "cursor": cursor}).json()
        seen.extend(it["piece_uuid"] for it in body["items"])
        cursor = body["next_cursor"]
    return seen


def test_cards_carry_counts_and_my_flags(client, db, fleet):
    items = {it["piece_uuid"]: it for it in client.get("/api/labeling/pieces", params={"sort": "recent", "limit": 200}).json()["items"]}
    assert items["p03"]["color_label_count"] == 3 and items["p03"]["my_color"] is True
    assert items["p02"]["color_label_count"] == 2 and items["p02"]["my_color"] is False
    assert items["p05"]["crop_link_count"] == 2 and items["p05"]["my_crop"] is True
    assert items["p12"]["part_label_count"] == 1 and items["p12"]["my_part"] is True
    assert items["p00"]["thumb_seq"] == 0
    assert items["p00"]["thumb_url"] is None  # local storage: the card falls back to the image route
    assert "foreign" not in items and "young" not in items and "p09" not in items


def test_cards_use_a_direct_storage_url_when_there_is_one(client, db, fleet, monkeypatch):
    class _Signing:
        def presigned_get_url(self, key):
            return f"https://store.example/{key}?sig=1"

    from app.services import review_queue

    monkeypatch.setattr(review_queue, "get_backend", lambda: _Signing())
    item = client.get("/api/labeling/pieces", params={"sort": "recent", "limit": 1}).json()["items"][0]
    assert item["thumb_url"].startswith("https://store.example/") and item["piece_uuid"] in item["thumb_url"]


def test_a_bad_cursor_is_a_400(client, fleet):
    resp = client.get("/api/labeling/pieces", params={"sort": "recent", "cursor": "not-a-cursor"})
    assert resp.status_code == 400
    page = client.get("/api/labeling/pieces", params={"sort": "recent", "limit": 1}).json()
    resp = client.get("/api/labeling/pieces", params={"sort": "oldest", "cursor": page["next_cursor"]})
    assert resp.status_code == 400  # a cursor belongs to its sort


# --- Counts ------------------------------------------------------------------------


def test_labelable_count_is_a_sum_of_the_worker_counts(client, db, fleet):
    stats = client.get("/api/labeling/stats").json()
    # The member's 24 pieces, rejected one included; not the foreign or young ones.
    assert stats["total_labelable"] == 24
    one = client.get("/api/labeling/stats", params={"machine_id": str(fleet["m1"])}).json()
    assert one["total_labelable"] == 9
    # The count is the worker's: a new piece shows up after a pass, not before.
    _piece(db, fleet["m1"], "new", NOW - timedelta(hours=1), created_at=_now())
    assert client.get("/api/labeling/stats").json()["total_labelable"] == 24
    labeling_queue.run_pass(db)
    assert client.get("/api/labeling/stats").json()["total_labelable"] == 25


def test_admin_count_covers_the_fleet(client, db, fleet):
    me = _me(db)
    me.role = "admin"
    db.commit()
    assert client.get("/api/labeling/stats").json()["total_labelable"] == 25


# --- Dashboard overview ----------------------------------------------------------------


def test_overview_sums_the_cached_review_counts(client, db, test_user):
    me = _me(db)
    mine = _machine(db, me.id, "samples-mine")
    archived = _machine(db, me.id, "samples-old")
    theirs = _machine(db, _user(db, "x@test.com").id, "samples-theirs")
    db.get(Machine, archived).archived_at = NOW
    db.commit()
    for mid, statuses in ((mine, ["unreviewed", "unreviewed", "accepted", "rejected", "conflict", "in_review"]), (archived, ["unreviewed"]), (theirs, ["accepted"])):
        session = UploadSession(machine_id=mid, source_session_id=f"s-{mid}", name="s")
        db.add(session)
        db.flush()
        for i, status in enumerate(statuses):
            db.add(Sample(machine_id=mid, upload_session_id=session.id, local_sample_id=f"{mid}-{i}", image_path="x.jpg", review_status=status))
    db.commit()
    refresh_stats()

    row = db.get(MachineStatsCache, mine)
    assert (row.unreviewed_samples, row.in_review_samples, row.rejected_samples, row.conflict_samples) == (2, 1, 1, 1)

    body = client.get("/api/stats/overview").json()
    assert body["total_samples"] == 6
    assert body["unreviewed_samples"] == 2
    assert body["in_review_samples"] == 1
    assert body["accepted_samples"] == 1
    assert body["rejected_samples"] == 1
    assert body["conflict_samples"] == 1
    assert body["total_machines"] == 1
    assert body["computed_at"] is not None


# --- Stored link scores and colour guesses ------------------------------------------------


class _Model:
    name = "link-test"
    sha256 = "a" * 64
    threshold = 0.9
    threshold_source = "published"


def test_possible_crops_scores_once_per_model_and_reports_the_threshold(client, db, fleet, monkeypatch):
    m1 = fleet["m1"]
    reads: list[list[str]] = []
    scored: list[int] = []

    monkeypatch.setattr(link_predictor, "active_model", lambda db: _Model())

    def _read_many(keys):
        reads.append(list(keys))
        return {k: b"bytes" for k in keys}

    def _score(model, anchor, crops):
        scored.append(len(crops))
        return {int(c["local_id"]): (0.95 if i == 0 else 0.5) for i, (c, _) in enumerate(crops)}

    monkeypatch.setattr(piece_link_scores, "read_many", _read_many)
    monkeypatch.setattr(link_predictor, "score_crops", _score)

    first = client.get(f"/api/labeling/possible-crops/{m1}/p02").json()
    assert first["prediction_source"] == "model"
    assert first["link_threshold"] == 0.9
    assert first["link_model"] == "link-test"
    picks = [c for c in first["candidates"] if c["model_same"]]
    assert len(picks) == 1 and picks[0]["model_score"] == 0.95
    assert all("image_key" not in c for c in first["candidates"])
    assert len(reads) == 1 and scored == [1]

    # Opening it again reads the stored scores: no storage reads, no model run.
    again = client.get(f"/api/labeling/possible-crops/{m1}/p02").json()
    assert again["candidates"] == first["candidates"]
    assert len(reads) == 1 and scored == [1]
    assert db.query(PieceLinkScore).count() == 1

    # A crop that synced since is scored on the next open and merged in.
    arrival = db.get(LabelingQueueEntry, (m1, "p02")).arrival_at.replace(tzinfo=timezone.utc)
    _crop(db, m1, arrival - timedelta(seconds=5))
    third = client.get(f"/api/labeling/possible-crops/{m1}/p02").json()
    assert len(third["candidates"]) == 2
    assert scored == [1, 1]
    assert all(c["model_score"] is not None for c in third["candidates"])


def test_published_threshold_wins_over_the_default(db, monkeypatch):
    from app.models.detection_model import DetectionModel
    from app.models.link_model import LinkModel

    row = LinkModel(name="link-v9", encoder_filename="e.onnx", head_filename="h.onnx", sha256="b" * 64, is_active=True, meta={})
    db.add(row)
    db.commit()
    assert link_predictor.active_model(db).threshold == link_predictor.DEFAULT_PREDICT_THRESHOLD
    row.meta = {"hive.predict_threshold": "0.8"}
    db.commit()
    assert (link_predictor.active_model(db).threshold, link_predictor.active_model(db).threshold_source) == (0.8, "model file")
    db.add(
        DetectionModel(
            slug="link-v9", version=1, name="link-v9", model_family="piece_link_matcher", purpose="piece_link",
            training_metadata={"predict_threshold": 0.97}, is_public=True, published_at=NOW, updated_at=NOW,
        )
    )
    db.commit()
    model = link_predictor.active_model(db)
    assert (model.threshold, model.threshold_source) == (0.97, "published")


def test_piece_detail_guesses_colour_once(client, db, fleet, monkeypatch):
    m1 = fleet["m1"]
    reads: list[list[str]] = []

    def _read_many(keys):
        reads.append(list(keys))
        return {k: b"bytes" for k in keys}

    monkeypatch.setattr(piece_color_guess, "read_many", _read_many)
    monkeypatch.setattr(
        piece_color_guess.pixel_color, "guess_from_bytes", lambda blobs: {"method": "pixel_average", "color_id": 11, "rgb": "AABBCC", "sample_count": len(blobs)}
    )
    first = client.get(f"/api/labeling/piece/{m1}/p00").json()
    assert first["pixel_guess"]["color_id"] == 11
    assert first["model_prediction"] is None  # no colour model active
    assert first["images"][0]["url"] is None  # local storage
    assert len(reads) == 1
    again = client.get(f"/api/labeling/piece/{m1}/p00").json()
    assert again["pixel_guess"] == first["pixel_guess"]
    assert len(reads) == 1
    assert db.query(PieceColorGuess).count() == 1

    # A new usable crop means a new guess.
    db.add(MachinePieceImage(machine_id=m1, piece_uuid="p00", seq=1, local_id=2, image_key="k2.jpg", used=True))
    db.commit()
    client.get(f"/api/labeling/piece/{m1}/p00")
    assert len(reads) == 2 and reads[-1] == ["k2.jpg"]


def test_unreadable_crops_are_not_stored(client, db, fleet, monkeypatch):
    monkeypatch.setattr(piece_color_guess, "read_many", lambda keys: {k: None for k in keys})
    body = client.get(f"/api/labeling/piece/{fleet['m1']}/p00").json()
    assert body["pixel_guess"] is None
    assert db.query(PieceColorGuess).count() == 0


def test_cursor_order_survives_identical_arrivals(client, db, fleet):
    # p05 and p06 arrived at the same instant on different machines.
    order = _walk(client, "recent", 1)
    i5, i6 = order.index("p05"), order.index("p06")
    assert abs(i5 - i6) == 1


def test_redaction_blanks_keys_in_urls():
    from app.services.redact import redact_secrets

    text = "403 Client Error for url: https://api.example/v1/x?currency=USD&api_key=SECRET123&page=2 key=abc token=t0k"
    out = redact_secrets(text)
    assert "SECRET123" not in out and "abc" not in out and "t0k" not in out
    assert "currency=USD" in out and "page=2" in out


def test_read_many_reads_concurrently_and_maps_missing_to_none(tmp_path, monkeypatch):
    from app.services import storage_backend

    for i in range(20):
        (tmp_path / f"{i}.jpg").write_bytes(bytes([i]))
    monkeypatch.setattr(storage_backend, "get_backend", lambda: storage_backend.LocalStorageBackend(str(tmp_path)))
    keys = [f"{i}.jpg" for i in range(20)] + ["missing.jpg", "0.jpg"]
    got = storage_backend.read_many(keys)
    assert got["missing.jpg"] is None
    assert all(got[f"{i}.jpg"] == bytes([i]) for i in range(20))
    assert len(got) == 21
