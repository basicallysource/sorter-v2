"""The piece grid on the labeling page: one page of the queue, in a sort's order.

Every sort is a short list of segments read one after another until the page is
full. A segment is one of three shapes, each cheap at any fleet size:

  * ``walk``: queue rows in arrival order (newest first, or oldest first), read
    by walking an index on labeling_queue and stopping at the page size. When the
    sort is about a label count, the walk keeps only pieces with no label of
    that kind, which is nearly all of them.
  * ``labeled``: pieces that do have labels of the sort's kind, ordered by how
    many, then newest. Labels are written by people, so this set is small (about
    1,500 pieces with a colour label today), and sorting it is cheap.
  * ``rare``: the "likely a rare color" sort, least confident colour prediction
    first, by walking its own index.

For example "priority" (pieces with same-piece candidates first, then the least
colour-labeled, then newest) is: candidates with no colour label (walk),
candidates with colour labels (labeled), then the same two without candidates.

Paging is by a keyset cursor: the segment and the sort key of the last piece
served. The next page starts strictly after it, so "load more" costs the same
as the first page however deep the list goes, and a piece that gets labeled
while someone scrolls cannot shift the rest of the list under them.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, exists, false, func, or_, tuple_
from sqlalchemy.orm import Session

from app.errors import APIError
from app.models.labeling_queue import LabelingQueueEntry as Q
from app.models.machine_piece import MachinePiece
from app.models.piece_color_label import PieceColorLabel
from app.models.piece_crop_link import PieceCropLink
from app.models.piece_part_label import PiecePartLabel
from app.models.piece_rejection import PieceRejection
from app.models.user import User
from app.services.access_window import scope_to_piece_access
from app.services.labeling_queue import MIN_PIECE_AGE

SORTS = (
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
class Segment:
    kind: str  # "walk" | "labeled" | "rare"
    label: str | None = None  # the label table this segment is about
    oldest: bool = False  # walk oldest first
    most: bool = False  # labeled: most labels first
    mine: bool | None = None  # labeled: only pieces this user did (True) or did not (False) label
    candidates: bool | None = None  # only pieces with (True) or without (False) same-piece candidates
    filters: tuple = field(default_factory=tuple)


def segments_for(sort: str) -> list[Segment]:
    if sort == "recent":
        return [Segment("walk")]
    if sort == "oldest":
        return [Segment("walk", oldest=True)]
    if sort == "priority":
        return [
            Segment("walk", "color", candidates=True),
            Segment("labeled", "color", candidates=True),
            Segment("walk", "color", candidates=False),
            Segment("labeled", "color", candidates=False),
        ]
    if sort == "needs_me":
        return [
            Segment("walk", "color"),
            Segment("labeled", "color", mine=False),
            Segment("labeled", "color", mine=True),
        ]
    if sort == "unidentified":
        unident = (Q.unidentified.is_(True),)
        return [Segment("walk", "part", filters=unident), Segment("labeled", "part", filters=unident)]
    if sort == "rare_color":
        return [Segment("rare"), Segment("walk", filters=(Q.color_confidence.is_(None),))]
    for label in ("color", "crop", "part"):
        if sort == f"least_{label}":
            return [Segment("walk", label), Segment("labeled", label)]
        if sort == f"most_{label}":
            return [Segment("labeled", label, most=True), Segment("walk", label)]
    raise ValueError(sort)


# --- Cursor -------------------------------------------------------------------------


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


def _key_tail(row: Any) -> list[Any]:
    return [_utc(row.arrival_at).isoformat(), str(row.machine_id), row.piece_uuid]


def _parse_tail(key: list[Any]) -> tuple[datetime, UUID, str]:
    try:
        return datetime.fromisoformat(key[-3]), UUID(key[-2]), str(key[-1])
    except (ValueError, TypeError, IndexError) as exc:
        raise APIError(400, "Invalid cursor", "CURSOR_INVALID") from exc


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# --- Reading a page -------------------------------------------------------------------


@dataclass
class PageRow:
    machine_id: UUID
    piece_uuid: str
    has_candidates: bool
    cursor_key: list[Any]
    segment: int


def _after(machine_filtered: bool, key: list[Any], oldest: bool = False):
    """Strictly after the cursor in arrival order. With one machine the machine
    column is constant, so the comparison leaves it out and the index on
    (machine_id, arrival_at, piece_uuid) can start right at the cursor."""
    arrival, machine_id, piece_uuid = _parse_tail(key)
    if machine_filtered:
        left, right = tuple_(Q.arrival_at, Q.piece_uuid), (arrival, piece_uuid)
    else:
        left, right = tuple_(Q.arrival_at, Q.machine_id, Q.piece_uuid), (arrival, machine_id, piece_uuid)
    return left > right if oldest else left < right


def _newest_first(machine_filtered: bool, oldest: bool = False) -> list:
    cols = [Q.arrival_at] + ([] if machine_filtered else [Q.machine_id]) + [Q.piece_uuid]
    return [c.asc() for c in cols] if oldest else [c.desc() for c in cols]


def read_page(
    db: Session,
    user: User,
    sort: str,
    limit: int,
    cursor: str | None,
    machine_id: UUID | None,
    with_candidates: bool,
    rare_color_ids: set[str] | None,
) -> tuple[list[PageRow], str | None]:
    """The next ``limit`` queue pieces in ``sort`` order after ``cursor``.
    Returns the rows and the cursor for the page after (None at the end)."""
    segments = segments_for(sort)
    start_segment, start_key = decode_cursor(cursor, sort) if cursor else (0, None)
    cutoff = datetime.now(timezone.utc) - MIN_PIECE_AGE
    machine_filtered = machine_id is not None

    my_rejection = exists().where(
        and_(
            PieceRejection.machine_id == Q.machine_id,
            PieceRejection.piece_uuid == Q.piece_uuid,
            PieceRejection.labeler_id == user.id,
        )
    )

    def base(agg=None):
        columns = [Q.machine_id, Q.piece_uuid, Q.arrival_at, Q.has_candidates, Q.color_confidence]
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
        if machine_filtered:
            q = q.filter(Q.machine_id == machine_id)
        if with_candidates:
            q = q.filter(Q.has_candidates.is_(True))
        if rare_color_ids is not None:
            q = q.filter(Q.color_id.in_(rare_color_ids)) if rare_color_ids else q.filter(false())
        return scope_to_piece_access(db, q, user, Q.machine_id, Q.piece_uuid)

    out: list[PageRow] = []
    want = limit + 1
    for index, seg in enumerate(segments):
        if index < start_segment:
            continue
        if with_candidates and seg.candidates is False:
            continue  # empty by definition; walking it would read the whole index
        key = start_key if index == start_segment else None
        remaining = want - len(out)
        if remaining <= 0:
            break

        seg_filters = list(seg.filters)
        if seg.candidates is not None:
            seg_filters.append(Q.has_candidates.is_(seg.candidates))

        if seg.kind == "walk":
            q = base().filter(*seg_filters)
            if seg.label is not None:
                table = _LABEL_TABLES[seg.label]
                q = q.filter(
                    ~exists().where(and_(table.machine_id == Q.machine_id, table.piece_uuid == Q.piece_uuid))
                )
            if key is not None:
                q = q.filter(_after(machine_filtered, key, seg.oldest))
            rows = q.order_by(*_newest_first(machine_filtered, seg.oldest)).limit(remaining).all()
            out.extend(PageRow(r.machine_id, r.piece_uuid, bool(r.has_candidates), _key_tail(r), index) for r in rows)

        elif seg.kind == "labeled":
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
            q = base(agg).filter(*seg_filters)
            if seg.mine is not None:
                q = q.filter(agg.c.mine == (1 if seg.mine else 0))
            if key is not None:
                n = int(key[0])
                beyond = agg.c.n < n if seg.most else agg.c.n > n
                q = q.filter(or_(beyond, and_(agg.c.n == n, _after(False, key))))
            count_order = agg.c.n.desc() if seg.most else agg.c.n.asc()
            rows = q.order_by(count_order, *_newest_first(False)).limit(remaining).all()
            out.extend(
                PageRow(r.machine_id, r.piece_uuid, bool(r.has_candidates), [int(r.n), *_key_tail(r)], index)
                for r in rows
            )

        else:  # rare: least confident colour first, then newest
            q = base().filter(Q.color_confidence.isnot(None))
            if key is not None:
                conf = float(key[0])
                q = q.filter(
                    Q.color_confidence >= conf,
                    or_(Q.color_confidence > conf, _after(False, key)),
                )
            rows = q.order_by(Q.color_confidence.asc(), *_newest_first(False)).limit(remaining).all()
            out.extend(
                PageRow(r.machine_id, r.piece_uuid, bool(r.has_candidates), [float(r.color_confidence), *_key_tail(r)], index)
                for r in rows
            )

    has_more = len(out) > limit
    out = out[:limit]
    next_cursor = encode_cursor(sort, out[-1].segment, out[-1].cursor_key) if has_more and out else None
    return out, next_cursor
