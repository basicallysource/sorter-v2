"""What is in a machine's bins and lots, counted from its piece records: the
inventory API's arithmetic (routers/inventory.py, agent-docs/inventory.md).

A piece went into a bin when the machine recorded it there (machine_pieces
bin_x, bin_y, bin_z and recorded_at); it belongs to the sorting run whose
stretch holds its seen_at; an emptying of the bin took the pieces put in it
after the bin's emptying before; a piece the machine sent back to be sorted
again (machine_sent_back_pieces) left its bin and no lot counts it.

Every read is one range of an index that leads with the machine and the bin
or the time (ix_machine_pieces_bin_recorded_at, ix_machine_pieces_machine_seen_at),
and reads at most WINDOW pieces: an answer that would take more is refused
with a hint to ask for fewer bins or a shorter stretch, never cut short.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import and_, case, false, func, literal, or_, select, true
from sqlalchemy.orm import Session

from app.errors import APIError
from app.models.machine_bin import MachineBinEmptying, MachineBinLayout
from app.models.machine_piece import MachinePiece
from app.models.machine_sent_back_piece import MachineSentBackPiece
from app.models.machine_sorting_run import MachineLot, MachineSortingRun

# The most pieces one answer reads.
WINDOW = 50_000
# The colour a machine operator gives a piece whose colour does not matter.
ANY_COLOR = "any_color"

_BIN_KEY = re.compile(r"^L(\d+)-S(\d+)-B(\d+)$")

Place = tuple[int, int, int]


def bin_key(place: Place) -> str:
    """A bin's name, numbered from 1 as the sorter shows it: "L1-S2-B4"."""
    layer, section, bin_ = place
    return f"L{layer + 1}-S{section + 1}-B{bin_ + 1}"


def parse_bin_key(text: str) -> Place:
    match = _BIN_KEY.match(text.strip().upper())
    if not match or min(int(n) for n in match.groups()) < 1:
        raise APIError(400, f"Not a bin: {text!r} (like L1-S2-B4, numbered from 1)", "BAD_BIN")
    layer, section, bin_ = (int(n) - 1 for n in match.groups())
    return layer, section, bin_


def bin_ref(place: Place) -> dict[str, Any]:
    layer, section, bin_ = place
    return {"key": bin_key(place), "layer": layer + 1, "section": section + 1, "bin": bin_ + 1}


def aware(moment: datetime | None) -> datetime | None:
    """A stored time with its zone (SQLite hands them back naive, in UTC)."""
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def iso(moment: datetime | None) -> str | None:
    moment = aware(moment)
    return moment.isoformat() if moment else None


# The part an inventory counts a piece as: the machine's, when it classified
# the piece and its operator did not say the part is wrong; else none (the
# piece counts as unidentified).
_PART = case(
    (
        and_(
            MachinePiece.classification_status == "classified",
            MachinePiece.part_id.is_not(None),
            or_(MachinePiece.part_correct.is_(None), MachinePiece.part_correct.is_(true())),
        ),
        MachinePiece.part_id,
    ),
    else_=None,
)
# Its colour: the operator's correction when they gave one, else the machine's.
_COLOR = case(
    (
        and_(MachinePiece.color_corrected_id.is_not(None), MachinePiece.color_corrected_id != ANY_COLOR),
        MachinePiece.color_corrected_id,
    ),
    (MachinePiece.color_corrected_id == ANY_COLOR, None),
    else_=MachinePiece.color_id,
)
# Whether the operator changed the colour (the machine's colour name then no
# longer names it).
_RECOLORED = and_(MachinePiece.color_corrected_id.is_not(None), MachinePiece.color_corrected_id != MachinePiece.color_id)
_SENT_BACK = MachineSentBackPiece.piece_uuid.is_not(None)


@dataclass
class Tally:
    """Pieces grouped into items (a part in a colour), with those that have no
    part, and those sent back (counted apart, in no item)."""

    pieces: int = 0
    unidentified: int = 0
    sent_back: int = 0
    first: datetime | None = None
    last: datetime | None = None
    items: dict[tuple[str, str | None], dict[str, Any]] = field(default_factory=dict)

    def add(self, row: Any, palette: dict[int, dict[str, Any]]) -> None:
        n = int(row.n)
        if row.sent_back:
            self.sent_back += n
            return
        self.pieces += n
        for moment in (aware(row.first), aware(row.last)):
            if moment is not None:
                self.first = moment if self.first is None or moment < self.first else self.first
                self.last = moment if self.last is None or moment > self.last else self.last
        if row.part is None:
            self.unidentified += n
            return
        key = (str(row.part), None if row.color is None else str(row.color))
        item = self.items.get(key)
        if item is None:
            item = self.items[key] = _item(key, row, palette)
        item["count"] += n

    def answer(self) -> dict[str, Any]:
        items = sorted(self.items.values(), key=lambda i: (-i["count"], i["part_id"], i["color_id"] or ""))
        return {
            "pieces": self.pieces,
            "unidentified": self.unidentified,
            "sent_back": self.sent_back,
            "first_put_in": iso(self.first),
            "last_put_in": iso(self.last),
            "items": items,
        }


def _item(key: tuple[str, str | None], row: Any, palette: dict[int, dict[str, Any]]) -> dict[str, Any]:
    part_id, color_id = key
    color_name = None
    if color_id is not None:
        # The machine's name for its own colour; BrickLink's for one the
        # operator corrected it to.
        color_name = None if row.recolored else row.color_name
        if color_name is None:
            try:
                color_name = (palette.get(int(color_id)) or {}).get("name")
            except ValueError:
                color_name = None
    return {
        # How any inventory app can name it: BrickLink's part and colour ids,
        # as the machine reports them.
        "key": f"bricklink:{part_id}/{color_id}" if color_id is not None else f"bricklink:{part_id}",
        "part_id": part_id,
        "part_name": row.part_name,
        "color_id": color_id,
        "color_name": color_name,
        "count": 0,
    }


def palette() -> dict[int, dict[str, Any]]:
    """BrickLink's colours by id, to name a colour an operator corrected to."""
    try:
        from app.services import color_model_runs

        return color_model_runs._palette()
    except Exception:
        return {}


def _grouped(db: Session, machine_id: Any, where: Any, *, by_place: bool):
    """The pieces of the machine that `where` picks, at most WINDOW of them,
    grouped by bin (when by_place), part, colour and whether they were sent
    back. Refuses an answer that would read more than WINDOW pieces."""
    pieces = (
        select(
            MachinePiece.bin_x,
            MachinePiece.bin_y,
            MachinePiece.bin_z,
            _PART.label("part"),
            _COLOR.label("color"),
            _RECOLORED.label("recolored"),
            MachinePiece.part_name,
            MachinePiece.color_name,
            MachinePiece.recorded_at,
            _SENT_BACK.label("sent_back"),
        )
        .select_from(MachinePiece)
        .outerjoin(
            MachineSentBackPiece,
            and_(
                MachineSentBackPiece.machine_id == MachinePiece.machine_id,
                MachineSentBackPiece.piece_uuid == MachinePiece.piece_uuid,
            ),
        )
        .where(MachinePiece.machine_id == machine_id, where)
        .limit(WINDOW + 1)
        .subquery()
    )
    keys = [pieces.c.bin_x, pieces.c.bin_y, pieces.c.bin_z] if by_place else []
    rows = db.execute(
        select(
            *keys,
            pieces.c.part,
            pieces.c.color,
            pieces.c.recolored,
            pieces.c.sent_back,
            func.max(pieces.c.part_name).label("part_name"),
            func.max(pieces.c.color_name).label("color_name"),
            func.min(pieces.c.recorded_at).label("first"),
            func.max(pieces.c.recorded_at).label("last"),
            func.count().label("n"),
        ).group_by(*keys, pieces.c.part, pieces.c.color, pieces.c.recolored, pieces.c.sent_back)
    ).all()
    if sum(int(r.n) for r in rows) > WINDOW:
        raise APIError(
            422,
            f"More than {WINDOW} pieces: ask for fewer bins or a shorter stretch (put_in_after, put_in_before)",
            "TOO_MANY_PIECES",
        )
    return rows


def tally_by_bin(db: Session, machine_id: Any, where: Any) -> dict[Place, Tally]:
    tallies: dict[Place, Tally] = defaultdict(Tally)
    colors = palette()
    for row in _grouped(db, machine_id, and_(MachinePiece.bin_x.is_not(None), where), by_place=True):
        tallies[(int(row.bin_x), int(row.bin_y), int(row.bin_z))].add(row, colors)
    return tallies


def tally(db: Session, machine_id: Any, where: Any) -> Tally:
    total = Tally()
    colors = palette()
    for row in _grouped(db, machine_id, where, by_place=False):
        total.add(row, colors)
    return total


def in_bin(place: Place, after: datetime | None = None, until: datetime | None = None) -> Any:
    """The pieces put in a bin after one moment and up to another (one range of
    ix_machine_pieces_bin_recorded_at)."""
    layer, section, bin_ = place
    clauses = [MachinePiece.bin_x == layer, MachinePiece.bin_y == section, MachinePiece.bin_z == bin_]
    if after is not None:
        clauses.append(MachinePiece.recorded_at > after)
    if until is not None:
        clauses.append(MachinePiece.recorded_at <= until)
    return and_(*clauses)


def any_of(clauses: list[Any]) -> Any:
    return or_(*clauses) if clauses else false()


# ---------------------------------------------------------------------------
# Runs and lots
# ---------------------------------------------------------------------------


@dataclass
class Run:
    row: MachineSortingRun
    ends_at: datetime | None

    @property
    def started_at(self) -> datetime:
        return aware(self.row.started_at)

    def holds(self) -> Any:
        """The pieces seen in this run's stretch."""
        clauses = [MachinePiece.seen_at >= self.started_at]
        if self.ends_at is not None:
            clauses.append(MachinePiece.seen_at < self.ends_at)
        return and_(*clauses)

    def answer(self) -> dict[str, Any]:
        return {
            "id": self.row.run_id,
            "name": self.row.name,
            "note": self.row.note,
            "lot_id": self.row.lot_id,
            "adds_to_lot": bool(self.row.adds_to_lot),
            "started_at": iso(self.started_at),
            "ends_at": iso(self.ends_at),
        }


def runs(db: Session, machine_id: Any) -> list[Run]:
    """The machine's sorting runs in order, each until the next one starts."""
    rows = (
        db.query(MachineSortingRun)
        .filter(MachineSortingRun.machine_id == machine_id)
        .order_by(MachineSortingRun.started_at)
        .all()
    )
    return [Run(row, aware(rows[i + 1].started_at) if i + 1 < len(rows) else None) for i, row in enumerate(rows)]


def run(db: Session, machine_id: Any, run_id: str) -> Run:
    for candidate in runs(db, machine_id):
        if candidate.row.run_id == run_id:
            return candidate
    raise APIError(404, "Sorting run not found", "RUN_NOT_FOUND")


def lot(db: Session, machine_id: Any, lot_id: str) -> MachineLot:
    row = db.query(MachineLot).filter(MachineLot.machine_id == machine_id, MachineLot.lot_id == lot_id).first()
    if row is None:
        raise APIError(404, "Lot not found", "LOT_NOT_FOUND")
    return row


def lot_answer(row: MachineLot) -> dict[str, Any]:
    return {"id": row.lot_id, "name": row.name, "description": row.description, "created_at": iso(row.created_at)}


def lot_counts(db: Session, machine_id: Any, adding: list[Run]) -> Tally:
    """A lot as the machine counts it: the pieces seen in the runs that add to
    it, the ones it reaped as stuck left out, less those sent back."""
    return tally(
        db, machine_id, and_(MachinePiece.dead.is_(false()), any_of([r.holds() for r in adding]))
    )


# ---------------------------------------------------------------------------
# Emptyings and layouts
# ---------------------------------------------------------------------------


def last_emptyings(
    db: Session, machine_id: Any, places: Iterable[Place], before: datetime | None = None
) -> dict[Place, MachineBinEmptying]:
    """Each bin's last emptying (by a moment): one probe of
    ix_machine_bin_emptyings_bin per bin, however many emptyings it had."""
    last: dict[Place, MachineBinEmptying] = {}
    for place in places:
        query = db.query(MachineBinEmptying).filter(
            MachineBinEmptying.machine_id == machine_id,
            MachineBinEmptying.layer == place[0],
            MachineBinEmptying.section == place[1],
            MachineBinEmptying.bin == place[2],
        )
        if before is not None:
            query = query.filter(MachineBinEmptying.emptied_at <= before)
        row = query.order_by(MachineBinEmptying.emptied_at.desc(), MachineBinEmptying.local_id.desc()).first()
        if row is not None:
            last[place] = row
    return last


def emptying_before(db: Session, emptying: MachineBinEmptying) -> MachineBinEmptying | None:
    """The bin's emptying before this one."""
    return (
        db.query(MachineBinEmptying)
        .filter(
            MachineBinEmptying.machine_id == emptying.machine_id,
            MachineBinEmptying.layer == emptying.layer,
            MachineBinEmptying.section == emptying.section,
            MachineBinEmptying.bin == emptying.bin,
            or_(
                MachineBinEmptying.emptied_at < emptying.emptied_at,
                and_(
                    MachineBinEmptying.emptied_at == emptying.emptied_at,
                    MachineBinEmptying.local_id < emptying.local_id,
                ),
            ),
        )
        .order_by(MachineBinEmptying.emptied_at.desc(), MachineBinEmptying.local_id.desc())
        .first()
    )


def layout_at(db: Session, machine_id: Any, moment: datetime | None = None) -> MachineBinLayout | None:
    """The layout the machine ran at a moment (its newest, for none); for a
    moment before the first it told of, that first one."""
    query = db.query(MachineBinLayout).filter(MachineBinLayout.machine_id == machine_id)
    if moment is not None:
        running = (
            query.filter(MachineBinLayout.changed_at <= moment)
            .order_by(MachineBinLayout.changed_at.desc(), MachineBinLayout.local_id.desc())
            .first()
        )
        if running is not None:
            return running
        return query.order_by(MachineBinLayout.changed_at, MachineBinLayout.local_id).first()
    return query.order_by(MachineBinLayout.changed_at.desc(), MachineBinLayout.local_id.desc()).first()


def layouts_during(db: Session, machine_id: Any, start: datetime, end: datetime | None) -> list[MachineBinLayout]:
    """The layouts a machine ran during a stretch, in order: the one running
    at its start, then each one it changed to before its end."""
    first = layout_at(db, machine_id, start)
    if first is None:
        return []
    query = db.query(MachineBinLayout).filter(
        MachineBinLayout.machine_id == machine_id, MachineBinLayout.changed_at > start
    )
    if end is not None:
        query = query.filter(MachineBinLayout.changed_at < end)
    later = query.order_by(MachineBinLayout.changed_at, MachineBinLayout.local_id).all()
    return [first, *[row for row in later if row.local_id != first.local_id]]


def places(layout: dict[str, Any]) -> list[Place]:
    """Every bin a layout has, in the machine's order."""
    out: list[Place] = []
    for li, layer in enumerate(layout.get("layers") or []):
        if not isinstance(layer, dict):
            continue
        for si, section in enumerate(layer.get("sections") or []):
            for bi in range(len(section) if isinstance(section, list) else 0):
                out.append((li, si, bi))
    return out


def _at(value: Any, place: Place) -> Any:
    try:
        return value[place[0]][place[1]][place[2]]
    except (TypeError, IndexError, KeyError):
        return None


def assigned(layout: dict[str, Any], place: Place) -> list[dict[str, Any]]:
    """The categories a layout assigns a bin, with what the profile called them."""
    ids = _at(layout.get("bin_categories"), place)
    names = layout.get("category_names") if isinstance(layout.get("category_names"), dict) else {}
    return [{"id": str(c), "name": names.get(str(c))} for c in ids] if isinstance(ids, list) else []


def categories(ids: Iterable[str] | None, layout: dict[str, Any] | None) -> list[dict[str, Any]]:
    names = (layout or {}).get("category_names") if isinstance((layout or {}).get("category_names"), dict) else {}
    return [{"id": str(c), "name": names.get(str(c))} for c in ids or []]


def bin_shape(layout: dict[str, Any], place: Place) -> dict[str, Any]:
    """A bin as a layout has it: its size, how many share its section, and
    whether it takes pieces."""
    layers = layout.get("layers") or []
    layer = layers[place[0]] if place[0] < len(layers) and isinstance(layers[place[0]], dict) else {}
    sections = layer.get("sections") or []
    section = sections[place[1]] if place[1] < len(sections) and isinstance(sections[place[1]], list) else []
    section_enabled = layer.get("section_enabled")
    enabled = bool(layer.get("enabled", True)) and (
        not isinstance(section_enabled, list)
        or place[1] >= len(section_enabled)
        or bool(section_enabled[place[1]])
    )
    return {
        "size": section[place[2]] if place[2] < len(section) else None,
        "bins_in_section": len(section),
        "enabled": enabled,
        "not_in_inventory": bool(_at(layout.get("not_in_inventory_bins"), place)),
        "max_dimension_mm": layer.get("max_dimension_mm"),
    }


def emptying_answer(row: MachineBinEmptying, layout: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "id": str(row.local_id),
        "bin": bin_ref((row.layer, row.section, row.bin)),
        "emptied_at": iso(row.emptied_at),
        # What the clear covered: this bin, its layer, or every bin.
        "scope": row.scope,
        # How many pieces the machine counted in the bin.
        "machine_count": int(row.piece_count or 0),
        "categories": categories(row.category_ids, layout),
        "profile": {"id": row.profile_id, "name": row.profile_name},
    }
