"""The inventory API, version 1: what the caller's own machines hold, for any
inventory app (a shelf of bags, a parts list, a shop): each lot with its parts
and colours, the sorting runs, every bin with what it was assigned, what each
bin holds now or got in a run, and every emptying of a bin with the pieces it
took. Read-only, with a key that has inventory:read, and only for the
caller's machines (and of those, the ones a machine-scoped key names).

The contract, its numbering and its limits: agent-docs/inventory.md. The
arithmetic: services/inventory.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, false, true
from sqlalchemy.orm import Session

from app.deps import API_KEY_SCOPE_INVENTORY_READ, get_db, require_api_key_scopes
from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_bin import MachineBinEmptying
from app.models.machine_piece import MachinePiece
from app.models.machine_sorting_run import MachineLot
from app.models.machine_sync_state import MachineSyncState
from app.models.user import User
from app.services import inventory

router = APIRouter(prefix="/api/inventory/v1", tags=["inventory"])

READ = Depends(require_api_key_scopes(API_KEY_SCOPE_INVENTORY_READ))

# The data a machine syncs that an inventory is counted from; a machine's
# version moves whenever any of them does.
_VERSION_TYPES = {
    "pieces": "piece_records",
    "sent_back": "sent_back_pieces",
    "emptyings": "bin_emptyings",
    "layouts": "bin_layouts",
    "runs": "sorting_runs",
}
EMPTYINGS_PAGE = 20
EMPTYINGS_PAGE_MAX = 100


def _own_machines(db: Session, user: User):
    query = db.query(Machine).filter(Machine.owner_id == user.id)
    allowed = getattr(user, "_api_key_machine_ids", None)
    if allowed is not None:
        query = query.filter(Machine.id.in_([UUID(machine_id) for machine_id in allowed]))
    return query


def _own_machine(db: Session, user: User, machine_id: UUID) -> Machine:
    machine = _own_machines(db, user).filter(Machine.id == machine_id).first()
    if machine is None:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")
    return machine


def _machine(machine: Machine) -> dict[str, Any]:
    return {"id": str(machine.id), "name": machine.name}


def _moment(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _synced(db: Session, machine_ids: list[UUID]) -> dict[UUID, dict[str, int]]:
    synced: dict[UUID, dict[str, int]] = {machine_id: {name: 0 for name in _VERSION_TYPES} for machine_id in machine_ids}
    names = {data_type: name for name, data_type in _VERSION_TYPES.items()}
    for row in db.query(MachineSyncState).filter(
        MachineSyncState.machine_id.in_(machine_ids), MachineSyncState.data_type.in_(list(names))
    ):
        synced[row.machine_id][names[row.data_type]] = int(row.max_local_id or 0)
    return synced


@router.get("/machines")
def list_machines(db: Session = Depends(get_db), current_user: User = READ):
    """The caller's machines. `version` changes whenever a machine syncs
    anything its inventory is counted from: an app that keeps a copy asks
    again for what it keeps when it does. `synced` is each such stream's
    position, as the machine last sent it."""
    machines = _own_machines(db, current_user).order_by(Machine.name.asc()).all()
    synced = _synced(db, [m.id for m in machines])
    return {
        "machines": [
            {
                **_machine(machine),
                "last_seen_at": inventory.iso(machine.last_seen_at),
                "synced": synced[machine.id],
                "version": ".".join(str(synced[machine.id][name]) for name in _VERSION_TYPES),
            }
            for machine in machines
        ]
    }


@router.get("/machines/{machine_id}/lots")
def list_lots(machine_id: UUID, db: Session = Depends(get_db), current_user: User = READ):
    """The machine's lots, oldest first, each with its runs: the ones that add
    to it and the passes over it (runs that name it without adding to it)."""
    machine = _own_machine(db, current_user, machine_id)
    by_lot: dict[str, list[dict[str, Any]]] = {}
    for run in inventory.runs(db, machine.id):
        if run.row.lot_id:
            by_lot.setdefault(run.row.lot_id, []).append(run.answer())
    lots = db.query(MachineLot).filter(MachineLot.machine_id == machine.id).order_by(MachineLot.created_at).all()
    return {
        "machine": _machine(machine),
        "lots": [{**inventory.lot_answer(row), "runs": by_lot.get(row.lot_id, [])} for row in lots],
    }


@router.get("/machines/{machine_id}/lots/{lot_id}")
def get_lot(machine_id: UUID, lot_id: str, db: Session = Depends(get_db), current_user: User = READ):
    """A lot's inventory, as the machine counts it: the pieces seen in the runs
    that add to it (those reaped as stuck left out), less those sent back to
    be sorted again (`sent_back`). `items` are its parts in each colour, one
    count each; `unidentified` the pieces with no part."""
    machine = _own_machine(db, current_user, machine_id)
    row = inventory.lot(db, machine.id, lot_id)
    lot_runs = [r for r in inventory.runs(db, machine.id) if r.row.lot_id == lot_id]
    adding = [r for r in lot_runs if r.row.adds_to_lot]
    counted = inventory.lot_counts(db, machine.id, adding)
    return {
        "machine": _machine(machine),
        "lot": inventory.lot_answer(row),
        "runs": [r.answer() for r in lot_runs],
        **counted.answer(),
    }


@router.get("/machines/{machine_id}/runs")
def list_runs(machine_id: UUID, db: Session = Depends(get_db), current_user: User = READ):
    """The machine's sorting runs, oldest first. A run lasts from started_at
    until the next one starts (ends_at; null for the newest), and a piece
    belongs to the run whose stretch holds its seen_at."""
    machine = _own_machine(db, current_user, machine_id)
    return {"machine": _machine(machine), "runs": [r.answer() for r in inventory.runs(db, machine.id)]}


@router.get("/machines/{machine_id}/runs/{run_id}")
def get_run(machine_id: UUID, run_id: str, db: Session = Depends(get_db), current_user: User = READ):
    """A run's pieces as its lot counts them (stuck ones left out, those sent
    back apart), in items."""
    machine = _own_machine(db, current_user, machine_id)
    run = inventory.run(db, machine.id, run_id)
    counted = inventory.tally(db, machine.id, and_(MachinePiece.dead.is_(false()), run.holds()))
    return {"machine": _machine(machine), "run": run.answer(), **counted.answer()}


@router.get("/machines/{machine_id}/bins")
def list_bins(
    machine_id: UUID,
    run_id: str | None = Query(default=None, alias="run"),
    at: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    """Every bin of the machine as the layout it runs has them (or the one it
    ran `at` a moment): its size, whether it takes pieces, the categories it is
    assigned and what the profile calls them, and its last emptying. With
    `run`, each bin's `assignments` during that run instead: every set of
    categories it held then, each from when until when."""
    machine = _own_machine(db, current_user, machine_id)
    at = _moment(at)
    if run_id is not None:
        run = inventory.run(db, machine.id, run_id)
        at = at or run.ends_at
    current = inventory.layout_at(db, machine.id, at)
    if current is None:
        return {"machine": _machine(machine), "layout": None, "bins": []}
    layout = current.layout
    last = inventory.last_emptyings(db, machine.id, inventory.places(layout), at)
    bins = []
    for place in inventory.places(layout):
        entry: dict[str, Any] = {
            "bin": inventory.bin_ref(place),
            **inventory.bin_shape(layout, place),
            "categories": inventory.assigned(layout, place),
        }
        emptied = last.get(place)
        entry["last_emptying"] = (
            {"id": str(emptied.local_id), "emptied_at": inventory.iso(emptied.emptied_at), "machine_count": int(emptied.piece_count or 0)}
            if emptied is not None
            else None
        )
        bins.append(entry)
    answer: dict[str, Any] = {
        "machine": _machine(machine),
        "layout": {
            "changed_at": inventory.iso(current.changed_at),
            "profile": layout.get("profile"),
            "layers": [
                {
                    "layer": li + 1,
                    "enabled": bool(layer.get("enabled", True)) if isinstance(layer, dict) else True,
                    "sections": len(layer.get("sections") or []) if isinstance(layer, dict) else 0,
                    "max_dimension_mm": layer.get("max_dimension_mm") if isinstance(layer, dict) else None,
                }
                for li, layer in enumerate(layout.get("layers") or [])
            ],
        },
        "bins": bins,
    }
    if run_id is not None:
        answer["run"] = run.answer()
        spans = _assignments(inventory.layouts_during(db, machine.id, run.started_at, run.ends_at), run)
        for entry in bins:
            entry["assignments"] = spans.get(inventory.parse_bin_key(entry["bin"]["key"]), [])
    return answer


def _assignments(ran: list, run: inventory.Run) -> dict[inventory.Place, list[dict[str, Any]]]:
    """Each bin's assignments during a run, from the layouts it ran then (the
    one running at its start, and every one after, before its end), each
    bin's categories merged while they stay the same."""
    start, end = run.started_at, run.ends_at
    spans: dict[inventory.Place, list[dict[str, Any]]] = {}
    for i, row in enumerate(ran):
        until = inventory.aware(ran[i + 1].changed_at) if i + 1 < len(ran) else end
        since = max(inventory.aware(row.changed_at), start)
        for place in inventory.places(row.layout):
            held = inventory.assigned(row.layout, place)
            bin_spans = spans.setdefault(place, [])
            if bin_spans and [c["id"] for c in bin_spans[-1]["categories"]] == [c["id"] for c in held]:
                bin_spans[-1]["until"] = inventory.iso(until)
                continue
            bin_spans.append({"categories": held, "since": inventory.iso(since), "until": inventory.iso(until)})
    return spans


@router.get("/machines/{machine_id}/contents")
def get_contents(
    machine_id: UUID,
    at: datetime | None = Query(default=None),
    run_id: str | None = Query(default=None, alias="run"),
    emptying_id: int | None = Query(default=None, alias="emptying"),
    put_in_after: datetime | None = Query(default=None),
    put_in_before: datetime | None = Query(default=None),
    bins: str | None = Query(default=None, max_length=4000),
    categories: str | None = Query(default=None, max_length=4000),
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    """The pieces put in the machine's bins, per bin, in items (a part in a
    colour, BrickLink's ids), with the pieces that have no part
    (`unidentified`) and those sent back to be sorted again (`sent_back`,
    counted apart: they left the bin).

    Which pieces: by default those each bin holds now, or `at` a moment: put in
    after its last emptying by then and up to that moment (`since` says from
    when). `put_in_after` is when a bin was emptied without the machine
    knowing (a person emptied it by hand): the later of the two counts. An
    answer `at` a past moment stays the same whatever the machine records
    after it. With `run`, the pieces seen in that sorting run instead; with
    `emptying`, those that emptying took out of its bin; `put_in_after` and
    `put_in_before` narrow either by when the pieces went in. `bins` limits
    any of it to some bins (L1-S2-B4, ...), `categories` to some of the
    machine's categories."""
    machine = _own_machine(db, current_user, machine_id)
    if run_id is not None and emptying_id is not None:
        raise APIError(400, "Ask for a run or an emptying, not both", "RUN_OR_EMPTYING")
    after, before, at = _moment(put_in_after), _moment(put_in_before), _moment(at)
    wanted = _keys(bins)
    kinds = _kinds(categories)
    answer: dict[str, Any] = {"machine": _machine(machine)}

    if run_id is not None:
        run = inventory.run(db, machine.id, run_id)
        among = inventory.any_of([inventory.in_bin(place) for place in wanted]) if wanted is not None else true()
        tallies = inventory.tally_by_bin(db, machine.id, and_(run.holds(), among, kinds, _window(after, before)))
        return {**answer, "run": run.answer(), **_bins_answer(tallies, wanted, {})}

    if emptying_id is not None:
        emptying = (
            db.query(MachineBinEmptying)
            .filter(MachineBinEmptying.machine_id == machine.id, MachineBinEmptying.local_id == emptying_id)
            .first()
        )
        if emptying is None:
            raise APIError(404, "Emptying not found", "EMPTYING_NOT_FOUND")
        place = (emptying.layer, emptying.section, emptying.bin)
        previous = inventory.emptying_before(db, emptying)
        layout = inventory.layout_at(db, machine.id, inventory.aware(emptying.emptied_at))
        answer["emptying"] = inventory.emptying_answer(emptying, layout.layout if layout else None)
        targets = [place] if wanted is None or place in wanted else []
        since = {place: _later(previous.emptied_at if previous else None, after)}
        until = _earlier(inventory.aware(emptying.emptied_at), before)
        shown: dict[inventory.Place, datetime | None] = {}
    else:
        if before is not None:
            raise APIError(400, "put_in_before narrows a run or an emptying; for a moment, ask `at`", "AT_NOT_BEFORE")
        layout = inventory.layout_at(db, machine.id, at)
        if layout is None and wanted is None:
            raise APIError(
                409,
                "The machine has not told Hive its bins yet: name them (bins=L1-S1-B1,...)",
                "NO_LAYOUT",
            )
        targets = wanted if wanted is not None else inventory.places(layout.layout)
        last = inventory.last_emptyings(db, machine.id, targets, at)
        since = {place: _later(last[place].emptied_at if place in last else None, after) for place in targets}
        until = at
        shown = since
        answer["at"] = inventory.iso(at) if at is not None else None

    where = inventory.any_of([inventory.in_bin(place, since[place], until) for place in targets])
    tallies = inventory.tally_by_bin(db, machine.id, and_(where, kinds)) if targets else {}
    return {**answer, **_bins_answer(tallies, targets, shown)}


def _keys(bins: str | None) -> list[inventory.Place] | None:
    if not bins:
        return None
    return list(dict.fromkeys(inventory.parse_bin_key(key) for key in bins.split(",") if key.strip()))


def _kinds(categories: str | None):
    """Only pieces of some of the machine's categories."""
    wanted = [c.strip() for c in (categories or "").split(",") if c.strip()]
    return MachinePiece.category_id.in_(wanted) if wanted else true()


def _later(a: datetime | None, b: datetime | None) -> datetime | None:
    a, b = inventory.aware(a), inventory.aware(b)
    if a is None or b is None:
        return a or b
    return max(a, b)


def _earlier(a: datetime | None, b: datetime | None) -> datetime | None:
    a, b = inventory.aware(a), inventory.aware(b)
    if a is None or b is None:
        return a or b
    return min(a, b)


def _window(after: datetime | None, before: datetime | None):
    clauses = []
    if after is not None:
        clauses.append(MachinePiece.recorded_at > after)
    if before is not None:
        clauses.append(MachinePiece.recorded_at <= before)
    return and_(*clauses) if clauses else true()


def _bins_answer(
    tallies: dict[inventory.Place, inventory.Tally],
    order: list[inventory.Place] | None,
    since: dict[inventory.Place, datetime | None],
) -> dict[str, Any]:
    places = order if order is not None else sorted(tallies)
    bins = []
    for place in places:
        counted = tallies.get(place) or inventory.Tally()
        entry = {"bin": inventory.bin_ref(place), **counted.answer()}
        if place in since:
            entry["since"] = inventory.iso(since[place])
        bins.append(entry)
    return {
        "pieces": sum(b["pieces"] for b in bins),
        "bins": bins,
    }


@router.get("/machines/{machine_id}/emptyings")
def list_emptyings(
    machine_id: UUID,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=EMPTYINGS_PAGE, ge=1, le=EMPTYINGS_PAGE_MAX),
    bin_key: str | None = Query(default=None, alias="bin"),
    items: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    """Every emptying of the machine's bins in the order the machine recorded
    them, a page at a time: pass `next` back as `after` until it is null (an
    app that keeps a copy keeps the last one and asks again from there). Each
    says which bin, when, what the clear covered, how many pieces the machine
    counted, the categories the bin was assigned, and (unless items=false) the
    pieces it took, counted as the contents of a bin are."""
    machine = _own_machine(db, current_user, machine_id)
    query = db.query(MachineBinEmptying).filter(
        MachineBinEmptying.machine_id == machine.id, MachineBinEmptying.local_id > after
    )
    if bin_key is not None:
        layer, section, bin_ = inventory.parse_bin_key(bin_key)
        query = query.filter(
            MachineBinEmptying.layer == layer, MachineBinEmptying.section == section, MachineBinEmptying.bin == bin_
        )
    rows = query.order_by(MachineBinEmptying.local_id).limit(limit + 1).all()
    more = len(rows) > limit
    rows = rows[:limit]
    emptyings = []
    for row in rows:
        layout = inventory.layout_at(db, machine.id, inventory.aware(row.emptied_at))
        entry = inventory.emptying_answer(row, layout.layout if layout else None)
        if items:
            previous = inventory.emptying_before(db, row)
            place = (row.layer, row.section, row.bin)
            counted = inventory.tally_by_bin(
                db,
                machine.id,
                inventory.in_bin(place, previous.emptied_at if previous else None, inventory.aware(row.emptied_at)),
            ).get(place) or inventory.Tally()
            entry.update(counted.answer())
            entry["put_in_after"] = inventory.iso(previous.emptied_at) if previous else None
        emptyings.append(entry)
    return {
        "machine": _machine(machine),
        "emptyings": emptyings,
        "next": rows[-1].local_id if more else None,
    }
