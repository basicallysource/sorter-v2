"""The queue of things to review: filtered, sorted, keyset-paged, one module.

Both review pages read their list from here: Piece samples (pieces to label,
from the labeling queue) and Channel samples (training samples to review).
What they share lives here once:

  * the machine filter, one machine or several, applied by ``restrict_to_machines``
    in the one query every page of a list is read from, so no path (first page,
    "load more", a sort, a tier of a sort) can return another machine's row;
  * keyset paging: a cursor names the sort, the segment and the sort key of the
    last row served, and the next page starts strictly after it, so page 50 costs
    what page 1 does and nothing shifts under someone scrolling;
  * thumbnails as presigned storage URLs, so a page of cards is not one API
    request per card;
  * counts summed from rows the workers keep, never a count over history.

A list is a short sequence of segments read in order until the page is full.
For pieces see ``piece_segments``. Samples are one walk, newest first, of the
index their filters pick, a bounded stretch per page (``sample_page``).
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Sequence
from uuid import UUID

from sqlalchemy import and_, case, exists, false, func, or_, select, tuple_, union_all
from sqlalchemy.orm import Session

from app.errors import APIError
from app.models.labeling_queue import LabelingQueueCount, LabelingQueueEntry as Q
from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.machine_stats_cache import MachineStatsCache
from app.models.piece_color_label import PieceColorLabel
from app.models.piece_crop_link import PieceCropLink
from app.models.piece_part_label import PiecePartLabel
from app.models.piece_rejection import PieceRejection
from app.models.sample import Sample
from app.models.user import User
from app.services.access_window import api_key_machine_ids, apply_sample_access, piece_scope, scope_to_piece_access
from app.services.labeling_queue import MIN_PIECE_AGE
from app.services.sample_filters import (
    CONDITION_CAPTURE_REASONS,
    SampleFilters,
    apply_sample_filters,
    restrict_to_machines,
)
from app.services.storage_backend import get_backend

__all__ = [
    "PIECE_SORTS",
    "SAMPLE_SORTS",
    "restrict_to_machines",
    "piece_page",
    "piece_cards",
    "piece_count",
    "training_labeled_count",
    "SAMPLE_WINDOW",
    "sample_page",
    "sample_path",
    "sample_counts",
    "thumb_url",
]


# --- Cursor and the segment runner ------------------------------------------------------


def encode_cursor(sort: str, segment: int, key: list[Any]) -> str:
    raw = json.dumps({"o": sort, "s": segment, "k": key}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, sort: str) -> tuple[int, list[Any]]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        if data["o"] != sort:
            raise ValueError("cursor is for another sort")
        segment, key = int(data["s"]), list(data["k"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise APIError(400, "Invalid cursor", "CURSOR_INVALID") from exc
    return segment, key


# A segment reads up to ``limit`` rows strictly after ``after`` (its own cursor
# key, or None from its start), in its order, as (row, cursor key) pairs. None
# in a segment list is a segment the filters leave empty; it is skipped.
Fetch = Callable[[list[Any] | None, int], list[tuple[Any, list[Any]]]]


def read_page(segments: Sequence[Fetch | None], sort: str, limit: int, cursor: str | None) -> tuple[list[Any], str | None]:
    """The next ``limit`` rows after ``cursor`` across the segments, and the
    cursor for the page after that (None at the end of the list)."""
    start_segment, start_key = decode_cursor(cursor, sort) if cursor else (0, None)
    out: list[tuple[int, Any, list[Any]]] = []
    want = limit + 1  # one more than the page, to know whether there is another
    for index, fetch in enumerate(segments):
        if index < start_segment or fetch is None:
            continue
        remaining = want - len(out)
        if remaining <= 0:
            break
        key = start_key if index == start_segment else None
        out.extend((index, row, k) for row, k in fetch(key, remaining))
    has_more = len(out) > limit
    out = out[:limit]
    next_cursor = encode_cursor(sort, out[-1][0], out[-1][2]) if has_more and out else None
    return [row for _, row, _ in out], next_cursor


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _parse_tail(key: list[Any]) -> tuple[datetime, str, str]:
    """The last three entries of a cursor key: a time and two ids."""
    try:
        return datetime.fromisoformat(key[-3]), str(key[-2]), str(key[-1])
    except (ValueError, TypeError, IndexError) as exc:
        raise APIError(400, "Invalid cursor", "CURSOR_INVALID") from exc


def thumb_url(image_key: str | None) -> str | None:
    """A direct storage URL for a thumbnail, when the backend can sign one;
    otherwise None and the client loads it through the API."""
    return get_backend().presigned_get_url(image_key) if image_key else None


# --- Pieces: the labeling queue ----------------------------------------------------------

PIECE_SORTS = (
    "priority",
    "recent",
    "oldest",
    "least_color",
    "most_color",
    "least_crop",
    "most_crop",
    "least_part",
    "most_part",
    "rare_color",
    "unidentified",
    "needs_me",
)

_LABEL_TABLES = {"color": PieceColorLabel, "crop": PieceCropLink, "part": PiecePartLabel}


@dataclass(frozen=True)
class _PieceSegment:
    kind: str  # "walk" | "trained" | "labeled" | "rare"
    label: str | None = None  # the label table the segment is about
    oldest: bool = False  # walk oldest first
    most: bool = False  # labeled: most labels first
    mine: bool | None = None  # labeled: only pieces this user did (True) or did not (False) label
    candidates: bool | None = None  # only pieces with (True) or without (False) same-piece candidates
    filters: tuple = field(default_factory=tuple)


def _piece_plan(sort: str) -> list[_PieceSegment]:
    """A piece sort as segments. A walk reads the queue in arrival order through
    an index and stops at the page size; for a sort about a label count it keeps
    only pieces with no label of that kind, which is nearly all. A labeled
    segment orders the pieces that do have labels (written by people, so few) by
    how many. "rare" walks the least confident colour predictions first.

    A colour from a training run counts as a colour label: the colour walks
    leave out the pieces that have one, and a "trained" segment walks those
    with no person's label (the queue's training indexes) just before the
    labeled ones, as if they had one label. A piece with a person's label is in
    the labeled segment, by its people's labels, whether a run labelled it or not."""
    if sort == "recent":
        return [_PieceSegment("walk")]
    if sort == "oldest":
        return [_PieceSegment("walk", oldest=True)]
    if sort == "priority":
        return [
            _PieceSegment("walk", "color", candidates=True),
            _PieceSegment("trained", "color", candidates=True),
            _PieceSegment("labeled", "color", candidates=True),
            _PieceSegment("walk", "color", candidates=False),
            _PieceSegment("trained", "color", candidates=False),
            _PieceSegment("labeled", "color", candidates=False),
        ]
    if sort == "needs_me":
        return [
            _PieceSegment("walk", "color"),
            _PieceSegment("trained", "color"),
            _PieceSegment("labeled", "color", mine=False),
            _PieceSegment("labeled", "color", mine=True),
        ]
    if sort == "unidentified":
        unident = (Q.unidentified.is_(True),)
        return [_PieceSegment("walk", "part", filters=unident), _PieceSegment("labeled", "part", filters=unident)]
    if sort == "rare_color":
        return [_PieceSegment("rare"), _PieceSegment("walk", filters=(Q.color_confidence.is_(None),))]
    if sort == "least_color":
        return [_PieceSegment("walk", "color"), _PieceSegment("trained", "color"), _PieceSegment("labeled", "color")]
    if sort == "most_color":
        return [
            _PieceSegment("labeled", "color", most=True),
            _PieceSegment("trained", "color"),
            _PieceSegment("walk", "color"),
        ]
    for label in ("crop", "part"):
        if sort == f"least_{label}":
            return [_PieceSegment("walk", label), _PieceSegment("labeled", label)]
        if sort == f"most_{label}":
            return [_PieceSegment("labeled", label, most=True), _PieceSegment("walk", label)]
    raise ValueError(sort)


def _piece_key(row: Any) -> list[Any]:
    return [_utc(row.arrival_at).isoformat(), str(row.machine_id), row.piece_uuid]


def piece_page(
    db: Session,
    user: User,
    *,
    sort: str,
    limit: int,
    cursor: str | None,
    machine_ids: Sequence[UUID] | None,
    with_candidates: bool,
    rare_color_ids: set[str] | None,
    with_palette: bool = False,
) -> tuple[list[Any], str | None]:
    """The next page of queue rows (machine_id, piece_uuid, arrival_at,
    has_candidates, color_confidence, has_palette, has_training_label) in ``sort`` order, and the
    next cursor. ``with_palette`` keeps the pieces with the colour reference
    palette in view near them, read through the queue's palette indexes.

    A member's grid is their own machines' pieces: given as the machine filter,
    so a member with one machine walks that machine's index rather than the
    fleet's, reading the rest of the fleet past to find theirs."""
    if machine_ids is None:
        machine_ids = known_machines(db, user, archived=True)
        if machine_ids is not None and not machine_ids:
            return [], None
    cutoff = datetime.now(timezone.utc) - MIN_PIECE_AGE
    one_machine = machine_ids is not None and len(machine_ids) == 1
    my_rejection = exists().where(
        and_(
            PieceRejection.machine_id == Q.machine_id,
            PieceRejection.piece_uuid == Q.piece_uuid,
            PieceRejection.labeler_id == user.id,
        )
    )

    def base(agg=None):
        # Every segment of every piece sort is read from this query, so the
        # machine filter and the access scope cannot be missed by any of them.
        columns = [
            Q.machine_id, Q.piece_uuid, Q.arrival_at, Q.has_candidates, Q.color_confidence, Q.has_palette,
            Q.has_training_label,
        ]
        if agg is not None:
            columns.append(agg.c.n)
        q = (
            db.query(*columns)
            .select_from(Q)
            .join(MachinePiece, and_(MachinePiece.machine_id == Q.machine_id, MachinePiece.piece_uuid == Q.piece_uuid))
        )
        if agg is not None:
            q = q.join(agg, and_(agg.c.mid == Q.machine_id, agg.c.puid == Q.piece_uuid))
        # The join keeps out a piece that died after the worker last saw it.
        q = q.filter(MachinePiece.dead.is_(False), Q.arrival_at <= cutoff, ~my_rejection)
        q = restrict_to_machines(q, Q.machine_id, machine_ids)
        if with_candidates:
            q = q.filter(Q.has_candidates.is_(True))
        if with_palette:
            # As the partial indexes' predicate is written, so they serve the walks.
            q = q.filter(Q.has_palette.is_(True))
        if rare_color_ids is not None:
            q = q.filter(Q.color_id.in_(rare_color_ids)) if rare_color_ids else q.filter(false())
        return scope_to_piece_access(db, q, user, Q.machine_id, Q.piece_uuid)

    def after_arrival(key: list[Any], oldest: bool = False):
        # With one machine the machine column is constant, so the comparison
        # leaves it out and the (machine_id, arrival_at, piece_uuid) index can
        # start right at the cursor.
        arrival, mid, puid = _parse_tail(key)
        if one_machine:
            left, right = tuple_(Q.arrival_at, Q.piece_uuid), (arrival, puid)
        else:
            left, right = tuple_(Q.arrival_at, Q.machine_id, Q.piece_uuid), (arrival, UUID(mid), puid)
        return left > right if oldest else left < right

    def newest_first(oldest: bool = False, constant_machine: bool = one_machine) -> list:
        cols = [Q.arrival_at] + ([] if constant_machine else [Q.machine_id]) + [Q.piece_uuid]
        return [c.asc() for c in cols] if oldest else [c.desc() for c in cols]

    def unlabeled(q, label: str):
        table = _LABEL_TABLES[label]
        return q.filter(~exists().where(and_(table.machine_id == Q.machine_id, table.piece_uuid == Q.piece_uuid)))

    def walk(seg: _PieceSegment, extra: list) -> Fetch:
        def fetch(key, limit):
            q = base().filter(*extra)
            if seg.label is not None:
                q = unlabeled(q, seg.label)
            if seg.label == "color":
                # A training run's colour is a colour label: those pieces come
                # in the trained segment.
                q = q.filter(Q.has_training_label.is_(False))
            if key is not None:
                q = q.filter(after_arrival(key, seg.oldest))
            rows = q.order_by(*newest_first(seg.oldest)).limit(limit).all()
            return [(r, _piece_key(r)) for r in rows]

        return fetch

    def trained(seg: _PieceSegment, extra: list) -> Fetch:
        # The pieces a training run labelled and no person has, newest first,
        # read through the training indexes (the predicate as they write it).
        def fetch(key, limit):
            q = unlabeled(base().filter(*extra, Q.has_training_label.is_(True)), seg.label)
            if key is not None:
                q = q.filter(after_arrival(key))
            rows = q.order_by(*newest_first()).limit(limit).all()
            return [(r, _piece_key(r)) for r in rows]

        return fetch

    def labeled(seg: _PieceSegment, extra: list) -> Fetch:
        def fetch(key, limit):
            table = _LABEL_TABLES[seg.label]
            agg = (
                db.query(
                    table.machine_id.label("mid"),
                    table.piece_uuid.label("puid"),
                    func.count().label("n"),
                    func.max(case((table.labeler_id == user.id, 1), else_=0)).label("mine"),
                )
                .group_by(table.machine_id, table.piece_uuid)
                .subquery()
            )
            q = base(agg).filter(*extra)
            if seg.mine is not None:
                q = q.filter(agg.c.mine == (1 if seg.mine else 0))
            if key is not None:
                n = int(key[0])
                arrival, mid, puid = _parse_tail(key)
                tail = tuple_(Q.arrival_at, Q.machine_id, Q.piece_uuid) < (arrival, UUID(mid), puid)
                q = q.filter(or_(agg.c.n < n if seg.most else agg.c.n > n, and_(agg.c.n == n, tail)))
            order = agg.c.n.desc() if seg.most else agg.c.n.asc()
            rows = q.order_by(order, *newest_first(constant_machine=False)).limit(limit).all()
            return [(r, [int(r.n), *_piece_key(r)]) for r in rows]

        return fetch

    def rare() -> Fetch:
        def fetch(key, limit):
            q = base().filter(Q.color_confidence.isnot(None))
            if key is not None:
                conf = float(key[0])
                arrival, mid, puid = _parse_tail(key)
                tail = tuple_(Q.arrival_at, Q.machine_id, Q.piece_uuid) < (arrival, UUID(mid), puid)
                q = q.filter(Q.color_confidence >= conf, or_(Q.color_confidence > conf, tail))
            rows = q.order_by(Q.color_confidence.asc(), *newest_first(constant_machine=False)).limit(limit).all()
            return [(r, [float(r.color_confidence), *_piece_key(r)]) for r in rows]

        return fetch

    segments: list[Fetch | None] = []
    for seg in _piece_plan(sort):
        if with_candidates and seg.candidates is False:
            segments.append(None)  # empty by definition; walking it would read the whole index
            continue
        extra = list(seg.filters)
        if seg.candidates is not None:
            extra.append(Q.has_candidates.is_(seg.candidates))
        make = {"walk": walk, "trained": trained, "labeled": labeled}.get(seg.kind)
        segments.append(make(seg, extra) if make is not None else rare())
    return read_page(segments, sort, limit, cursor)


def piece_cards(db: Session, user: User, rows: list[Any]) -> list[dict]:
    """The grid cards for one page of queue rows: a few keyed reads, no scan."""
    if not rows:
        return []
    keys = {(r.machine_id, r.piece_uuid) for r in rows}
    machine_ids = list({r.machine_id for r in rows})
    piece_uuids = list({r.piece_uuid for r in rows})

    def _page_filter(q, model):
        # Both columns as IN lists so the (machine_id, piece_uuid) indexes serve
        # it; the exact pairs are matched below.
        return q.filter(model.machine_id.in_(machine_ids), model.piece_uuid.in_(piece_uuids))

    pieces = {
        (p.machine_id, p.piece_uuid): p
        for p in _page_filter(
            db.query(
                MachinePiece.machine_id,
                MachinePiece.piece_uuid,
                MachinePiece.part_id,
                MachinePiece.part_name,
                MachinePiece.recorded_at,
                MachinePiece.seen_at,
            ),
            MachinePiece,
        )
    }
    machine_names = dict(db.query(Machine.id, Machine.name).filter(Machine.id.in_(machine_ids)).all())

    def _counts(model) -> dict[tuple, tuple[int, bool]]:
        q = db.query(model.machine_id, model.piece_uuid, func.count(), func.max(case((model.labeler_id == user.id, 1), else_=0)))
        return {
            (mid, puid): (int(n), bool(mine))
            for mid, puid, n, mine in _page_filter(q, model).group_by(model.machine_id, model.piece_uuid)
        }

    color_counts = _counts(PieceColorLabel)
    crop_counts = _counts(PieceCropLink)
    part_counts = _counts(PiecePartLabel)

    # Lowest available seq per piece is the card's thumbnail.
    thumbs: dict[tuple, tuple[int, str]] = {}
    for mid, puid, seq, key in _page_filter(
        db.query(MachinePieceImage.machine_id, MachinePieceImage.piece_uuid, MachinePieceImage.seq, MachinePieceImage.image_key),
        MachinePieceImage,
    ).filter(MachinePieceImage.image_key.isnot(None)).order_by(MachinePieceImage.seq.asc()):
        if (mid, puid) in keys:
            thumbs.setdefault((mid, puid), (seq, key))

    items = []
    for r in rows:
        k = (r.machine_id, r.piece_uuid)
        p = pieces.get(k)
        if p is None:
            continue
        ccnt, mc = color_counts.get(k, (0, False))
        xcnt, mx = crop_counts.get(k, (0, False))
        pcnt, mp = part_counts.get(k, (0, False))
        thumb = thumbs.get(k)
        items.append(
            {
                "machine_id": str(r.machine_id),
                "machine_name": machine_names.get(r.machine_id),
                "piece_uuid": r.piece_uuid,
                "part": {"part_id": p.part_id, "part_name": p.part_name},
                "recorded_at": p.recorded_at.isoformat() if p.recorded_at else None,
                "seen_at": p.seen_at.isoformat() if p.seen_at else None,
                "color_label_count": ccnt,
                "crop_link_count": xcnt,
                "part_label_count": pcnt,
                "my_color": mc,
                "my_crop": mx,
                "my_part": mp,
                "has_candidates": bool(r.has_candidates),
                "has_palette": bool(r.has_palette),
                # A training run's colour counts as a colour label here.
                "has_training_label": bool(r.has_training_label),
                "thumb_seq": thumb[0] if thumb else None,
                "thumb_url": thumb_url(thumb[1]) if thumb else None,
            }
        )
    return items


def piece_count(db: Session, user: User, machine_ids: Sequence[UUID] | None) -> int:
    """How many pieces this user may label on these machines: a sum over the
    per-machine counts the labeling-queue worker keeps. A reviewer's window adds
    the window's queued pieces on machines they do not own, a count bounded by
    the window size."""
    scope = piece_scope(db, user)

    def _restrict(q, col):
        q = restrict_to_machines(q, col, machine_ids)
        return restrict_to_machines(q, col, scope.machine_ids) if scope.machine_ids is not None else q

    counts = _restrict(db.query(func.coalesce(func.sum(LabelingQueueCount.labelable), 0)), LabelingQueueCount.machine_id)
    if scope.machine_ids is not None and not scope.machine_ids:
        return 0  # an API key limited to no machine sees nothing
    if scope.unrestricted:
        return int(counts.scalar() or 0)
    owned_total = int(counts.filter(LabelingQueueCount.machine_id.in_(scope.owned)).scalar() or 0)
    if scope.window_keys is None:
        return owned_total
    window_extra = (
        _restrict(db.query(func.count()).select_from(Q), Q.machine_id)
        .filter(
            tuple_(Q.machine_id, Q.piece_uuid).in_(scope.window_keys),
            ~Q.machine_id.in_(scope.owned),
            Q.arrival_at <= datetime.now(timezone.utc) - MIN_PIECE_AGE,
        )
        .scalar()
    )
    return owned_total + int(window_extra or 0)


def training_labeled_count(db: Session, user: User, machine_ids: Sequence[UUID] | None) -> int:
    """How many pieces training runs labelled with a colour that counts, on the
    machines this user may label: a sum over the per-machine counts the
    labeling-queue worker keeps (from the counts kept on each run, excluded
    runs left out). Runs count per machine, so a reviewer's window of other
    machines' pieces adds none."""
    scope = piece_scope(db, user)
    if scope.machine_ids is not None and not scope.machine_ids:
        return 0
    q = db.query(func.coalesce(func.sum(LabelingQueueCount.training_labeled), 0))
    q = restrict_to_machines(q, LabelingQueueCount.machine_id, machine_ids)
    if scope.machine_ids is not None:
        q = restrict_to_machines(q, LabelingQueueCount.machine_id, scope.machine_ids)
    if not scope.unrestricted:
        q = q.filter(LabelingQueueCount.machine_id.in_(scope.owned))
    return int(q.scalar() or 0)


# --- Samples: the Channel samples list and its review queue --------------------------------

SAMPLE_SORTS = ("recent",)

# The most samples one page looks at, along the index it walks, to find its
# rows. A page whose filters are rare in that stretch comes back short, even
# empty, with a cursor to go on from, and the client asks again: however rare
# the filters, no request reads further back than this.
SAMPLE_WINDOW = 2000

ARCHIVED_VIEWS = ("active", "archived", "all")
REVIEWED_STATES = ("in_review", "accepted", "rejected", "conflict")

_NEWEST_FIRST = (Sample.uploaded_at.desc(), Sample.id.desc())
# Written as the partial indexes write it, so the planner matches them.
_TEACHER_CHECKED = Sample.extra_metadata["teacher_rerun"].isnot(None)


@dataclass(frozen=True)
class SamplePath:
    """The index a page of samples walks, newest first. Every sample the
    filters can show is on it, so a page reads its rows from this index alone:
    ``where`` is the index's predicate (as the index writes it, so the planner
    picks it), and ``column`` its leading column, walked once per value in
    ``values`` and merged."""

    index: str
    where: tuple = ()
    column: Any = None
    values: tuple = ()


def sample_path(filters: SampleFilters, *, archived: str, machine_ids: Sequence[UUID] | None) -> SamplePath:
    """The narrowest index whose rows include everything the filters show.

    The most selective filter leads: a review state (few samples ever get
    one), then the machines (a filter's, or the caller's own), the source, the
    capture reason. Each of those has a teacher-checked twin, because that is
    the list's default view and the newest samples are rarely checked yet: a
    walk of all samples would read through all of them first. Archived samples
    have their own index; "archived and active" walks every sample."""
    if archived == "archived":
        return SamplePath("ix_samples_archived_uploaded_at", (Sample.archived_at.isnot(None),))
    if archived == "all":
        return SamplePath("ix_samples_uploaded_at_id")
    active = (Sample.archived_at.is_(None),)
    if filters.review_status in REVIEWED_STATES:
        return SamplePath(
            "ix_samples_reviewed_uploaded_at",
            active + (Sample.review_status != "unreviewed",),
            Sample.review_status,
            (filters.review_status,),
        )
    teacher = filters.annotated == "teacher"

    def by(name: str, column: Any, values: Sequence[Any]) -> SamplePath:
        if teacher:
            return SamplePath(f"ix_samples_{name}_teacher_uploaded_at", active + (_TEACHER_CHECKED,), column, tuple(values))
        return SamplePath(f"ix_samples_{name}_uploaded_at", active, column, tuple(values))

    if machine_ids is not None:
        return by("machine", Sample.machine_id, list(dict.fromkeys(machine_ids)))
    if filters.source_role:
        return by("role", Sample.source_role, [filters.source_role])
    if filters.capture_reason:
        return by("reason", Sample.capture_reason, [filters.capture_reason])
    if filters.kind == "condition":
        return by("reason", Sample.capture_reason, CONDITION_CAPTURE_REASONS)
    if teacher:
        return SamplePath("ix_samples_teacher_uploaded_at", active + (_TEACHER_CHECKED,))
    return SamplePath("ix_samples_uploaded_at_id", active)


def known_machines(db: Session, user: User, *, mine_only: bool = False, archived: bool = False) -> list[UUID] | None:
    """The machines a caller may see when they are a known few: an API key's,
    or their own (a member, or anyone asking for "mine"; archived ones too when
    ``archived``). None for admins and reviewers, who see the fleet. A walk of
    one machine follows that machine's index instead of the fleet's."""
    key_machines = api_key_machine_ids(user)
    if key_machines is not None:
        return key_machines
    if mine_only or user.role not in ("admin", "reviewer"):
        owned = db.query(Machine.id).filter(Machine.owner_id == user.id)
        if not archived:
            owned = owned.filter(Machine.archived_at.is_(None))
        return [mid for (mid,) in owned]
    return None


def _on_path(query, path: SamplePath):
    query = query.filter(*path.where)
    if path.column is None:
        return query
    if len(path.values) == 1:
        return query.filter(path.column == path.values[0])
    return query.filter(path.column.in_(path.values))


def _window_end(db: Session, path: SamplePath, after: tuple | None, since: datetime | None) -> tuple | None:
    """The key of the SAMPLE_WINDOW-th sample along ``path`` after ``after``,
    or None when the path ends sooner: read from the index alone (several
    values are walked one by one and merged)."""

    def walk(value: Any = None):
        q = select(Sample.uploaded_at, Sample.id).where(*path.where)
        if path.column is not None:
            q = q.where(path.column == value)
        if after is not None:
            q = q.where(tuple_(Sample.uploaded_at, Sample.id) < after)
        if since is not None:
            q = q.where(Sample.uploaded_at >= since)
        return q.order_by(*_NEWEST_FIRST)

    if path.column is None:
        q = walk()
    elif len(path.values) == 1:
        q = walk(path.values[0])
    else:
        parts = [walk(value).limit(SAMPLE_WINDOW).subquery() for value in path.values]
        merged = union_all(*(select(p.c.uploaded_at, p.c.id) for p in parts)).subquery()
        q = select(merged.c.uploaded_at, merged.c.id).order_by(merged.c.uploaded_at.desc(), merged.c.id.desc())
    row = db.execute(q.offset(SAMPLE_WINDOW - 1).limit(1)).first()
    return (row[0], row[1]) if row is not None else None


def _sample_key(uploaded_at: datetime, sample_id: Any) -> list[str]:
    return [_utc(uploaded_at).isoformat(), str(sample_id)]


def sample_page(
    db: Session,
    viewer: User,
    filters: SampleFilters,
    *,
    limit: int,
    cursor: str | None,
    mine_only: bool = False,
    archived: str = "active",
) -> tuple[list[Sample], str | None]:
    """The next page of samples, newest first, after ``cursor``, and the cursor
    for the page after it (None at the end of the list).

    The page walks one index (``sample_path``) and looks at no more than
    SAMPLE_WINDOW samples on it: first the key of the last of them is read
    from the index alone, then the page's rows are the ones in that stretch the
    filters keep. When fewer than ``limit`` are there, the page is short and
    its cursor is the end of the stretch, so the next request goes on from
    there. A page can therefore be short, or empty, and still have a next
    cursor; the list ends when the cursor is None.

    ``archived`` is "active" (the default), "archived" or "all"; the filters
    are applied through ``apply_sample_filters``, like every other path that
    acts on the filtered samples."""
    if archived not in ARCHIVED_VIEWS:
        raise ValueError(archived)
    after = None
    if cursor:
        _, key = decode_cursor(cursor, "recent")
        try:
            after = (datetime.fromisoformat(key[0]), UUID(key[1]))
        except (ValueError, TypeError, IndexError) as exc:
            raise APIError(400, "Invalid cursor", "CURSOR_INVALID") from exc
    machines = list(filters.machine_ids) if filters.machine_ids else known_machines(db, viewer, mine_only=mine_only)
    if machines is not None and not machines:
        return [], None
    path = sample_path(filters, archived=archived, machine_ids=machines)
    since = None
    if filters.max_age_hours is not None and filters.max_age_hours > 0:
        since = datetime.now(timezone.utc) - timedelta(hours=filters.max_age_hours)
    end = _window_end(db, path, after, since)

    base = visible_samples(db, viewer, mine_only=mine_only, include_archived=archived != "active")
    q = _on_path(apply_sample_filters(base, filters, viewer.id), path)
    if after is not None:
        q = q.filter(tuple_(Sample.uploaded_at, Sample.id) < after)
    if end is not None:
        q = q.filter(tuple_(Sample.uploaded_at, Sample.id) >= end)
    rows = q.order_by(*_NEWEST_FIRST).limit(limit + 1).all()
    if len(rows) > limit:
        rows = rows[:limit]
        next_key = _sample_key(rows[-1].uploaded_at, rows[-1].id)
    elif end is not None:
        next_key = _sample_key(*end)
    else:
        next_key = None
    return rows, encode_cursor("recent", 0, next_key) if next_key else None


def sample_counts(db: Session, user: User, *, mine_only: bool, machine_ids: Sequence[UUID] | None) -> dict[str, Any]:
    """Sample counts by review state over the machines the user may see (their
    own for members or with ``mine_only``), archived machines left out: a sum of
    the per-machine rows the stats worker keeps (hourly), never a count of
    samples. Also the sources and capture reasons the filters offer."""
    machines = db.query(Machine.id).filter(Machine.archived_at.is_(None))
    if mine_only or user.role not in ("admin", "reviewer"):
        machines = machines.filter(Machine.owner_id == user.id)
    key_machines = piece_scope(db, user).machine_ids  # an API key's own machine list
    if key_machines is not None:
        machines = machines.filter(Machine.id.in_(key_machines))
    machines = restrict_to_machines(machines, Machine.id, machine_ids)
    rows = db.query(MachineStatsCache).filter(MachineStatsCache.machine_id.in_(machines)).all()
    out: dict[str, Any] = {
        name: sum(int(getattr(r, name) or 0) for r in rows)
        for name in (
            "total_samples",
            "unreviewed_samples",
            "in_review_samples",
            "accepted_samples",
            "rejected_samples",
            "conflict_samples",
        )
    }
    out["total_machines"] = machines.count()
    oldest = min((r.computed_at for r in rows if r.computed_at is not None), default=None)
    out["computed_at"] = oldest.isoformat() if oldest is not None else None
    sources: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for r in rows:
        dist = r.distributions or {}
        for value, n in (dist.get("sample_sources") or {}).items():
            sources[value] = sources.get(value, 0) + int(n)
        for value, n in (dist.get("sample_capture_reasons") or {}).items():
            reasons[value] = reasons.get(value, 0) + int(n)
    out["source_role_counts"] = sources
    out["capture_reason_counts"] = reasons
    return out


def visible_samples(db: Session, user: User, *, mine_only: bool, include_archived: bool = False):
    """The samples a user may list: never an archived machine's; archived
    samples only on request (admins); a member's own machines only."""
    query = db.query(Sample).filter(Sample.machine.has(Machine.archived_at.is_(None)))
    if not include_archived:
        query = query.filter(Sample.archived_at.is_(None))
    if mine_only:
        query = query.filter(Sample.machine.has(owner_id=user.id))
    return apply_sample_access(db, query, user)
