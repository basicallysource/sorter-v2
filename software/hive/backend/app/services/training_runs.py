"""Training runs from sorters, and the colour labels they give pieces.

A sorter in training mode labels every piece it sees during a run with what
the run was for: in a colour run, one of the colours the operator fed
(``machine_pieces.training_*``, synced with the piece's record; the run itself
is ``machine_training_runs``). Such a label counts as a colour label when it
is set, the piece is not excluded and its run is not (``counts``); a run
Hive has not received yet is taken as not excluded.

What follows from that is kept, never computed per request:

  * each run's piece, labelled and excluded counts, recounted over the run's
    pieces (an indexed count of one run) when a batch of piece records touches
    the run and when the run itself syncs (``recount``);
  * the labeling queue's ``has_training_label``, which makes the piece grid
    treat the piece as colour-labelled: set by the queue worker when it
    evaluates a piece (``labelled``), and by the sync endpoints when a piece's
    training state or its run's exclusion changes (``after_piece_records``,
    ``after_runs``).
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.models.labeling_queue import LabelingQueueEntry
from app.models.machine_piece import MachinePiece
from app.models.machine_training_run import MachineTrainingRun
from app.services.profile_catalog import get_profile_catalog_service

_IN_CHUNK = 500


def _chunks(items: Sequence[Any], size: int = _IN_CHUNK) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def counts(run_uuid: str | None, color_id: str | None, piece_excluded: bool, run_excluded: bool) -> bool:
    """Whether a piece's training colour counts as a colour label."""
    return bool(run_uuid) and color_id is not None and not piece_excluded and not run_excluded


def excluded_runs(db: Session, machine_id: Any, run_uuids: Iterable[str]) -> set[str]:
    """Which of these runs of a machine the operator excluded."""
    found: set[str] = set()
    for chunk in _chunks(sorted(set(run_uuids))):
        found.update(
            run_uuid
            for (run_uuid,) in db.query(MachineTrainingRun.run_uuid).filter(
                MachineTrainingRun.machine_id == machine_id,
                MachineTrainingRun.run_uuid.in_(chunk),
                MachineTrainingRun.excluded.is_(True),
            )
        )
    return found


def recount(db: Session, machine_id: Any, run_uuids: Iterable[str]) -> None:
    """Count each run's pieces into its row: all of them, the labelled ones
    (a colour and not excluded) and the excluded ones. A run with no row yet
    is counted when its row arrives."""
    labelled = and_(MachinePiece.training_color_id.isnot(None), MachinePiece.training_excluded.is_(False))
    for chunk in _chunks(sorted(set(run_uuids))):
        found = {
            run_uuid: (int(n), int(lab or 0), int(exc or 0))
            for run_uuid, n, lab, exc in db.query(
                MachinePiece.training_run_uuid,
                func.count(),
                func.sum(case((labelled, 1), else_=0)),
                func.sum(case((MachinePiece.training_excluded.is_(True), 1), else_=0)),
            )
            .filter(MachinePiece.machine_id == machine_id, MachinePiece.training_run_uuid.in_(chunk))
            .group_by(MachinePiece.training_run_uuid)
        }
        for run_uuid in chunk:
            n, lab, exc = found.get(run_uuid, (0, 0, 0))
            db.query(MachineTrainingRun).filter(
                MachineTrainingRun.machine_id == machine_id, MachineTrainingRun.run_uuid == run_uuid
            ).update(
                {
                    MachineTrainingRun.piece_count: n,
                    MachineTrainingRun.labeled_count: lab,
                    MachineTrainingRun.excluded_count: exc,
                },
                synchronize_session=False,
            )


def set_queue_flags(db: Session, machine_id: Any, flags: dict[str, bool]) -> int:
    """Set ``has_training_label`` on these pieces' queue rows, writing only
    the rows it changes. A piece not in the queue yet gets it from the worker."""
    changed = 0
    for value in (True, False):
        piece_uuids = sorted(p for p, flag in flags.items() if flag == value)
        for chunk in _chunks(piece_uuids):
            changed += (
                db.query(LabelingQueueEntry)
                .filter(
                    LabelingQueueEntry.machine_id == machine_id,
                    LabelingQueueEntry.piece_uuid.in_(chunk),
                    LabelingQueueEntry.has_training_label.is_(not value),
                )
                .update({LabelingQueueEntry.has_training_label: value}, synchronize_session=False)
            )
    return changed


def runs_of(db: Session, machine_id: Any, piece_uuids: Sequence[str]) -> dict[str, str]:
    """The run each of these pieces is in now, for the pieces in one."""
    found: dict[str, str] = {}
    for chunk in _chunks(sorted(set(piece_uuids))):
        found.update(
            db.query(MachinePiece.piece_uuid, MachinePiece.training_run_uuid).filter(
                MachinePiece.machine_id == machine_id,
                MachinePiece.piece_uuid.in_(chunk),
                MachinePiece.training_run_uuid.isnot(None),
            )
        )
    return found


def after_piece_records(db: Session, machine_id: Any, records: Sequence[Any], previous: dict[str, str]) -> None:
    """After a batch of piece records is written: recount the runs it touched
    (the runs its pieces are in, and any run one of them was in before) and
    set the queue flag of the pieces that are or were in a run. ``records``
    carry piece_uuid and the training fields; ``previous`` is ``runs_of`` the
    batch read before it was written."""
    touched = {r.training_run_uuid for r in records if r.training_run_uuid} | set(previous.values())
    if not touched:
        return
    recount(db, machine_id, touched)
    excluded = excluded_runs(db, machine_id, touched)
    set_queue_flags(
        db,
        machine_id,
        {
            r.piece_uuid: counts(
                r.training_run_uuid, r.training_color_id, bool(r.training_excluded), r.training_run_uuid in excluded
            )
            for r in records
            if r.training_run_uuid or r.piece_uuid in previous
        },
    )


def after_runs(db: Session, machine_id: Any, run_uuids: Sequence[str]) -> None:
    """After runs are written: count their pieces (a run's first sync may
    follow its pieces') and set their pieces' queue flags (an excluded run's
    labels stop counting, and count again when it is let back in)."""
    if not run_uuids:
        return
    recount(db, machine_id, run_uuids)
    excluded = excluded_runs(db, machine_id, run_uuids)
    for chunk in _chunks(sorted(set(run_uuids))):
        rows = db.query(
            MachinePiece.piece_uuid,
            MachinePiece.training_run_uuid,
            MachinePiece.training_color_id,
            MachinePiece.training_excluded,
        ).filter(MachinePiece.machine_id == machine_id, MachinePiece.training_run_uuid.in_(chunk))
        set_queue_flags(
            db,
            machine_id,
            {
                puid: counts(run_uuid, color_id, bool(piece_excluded), run_uuid in excluded)
                for puid, run_uuid, color_id, piece_excluded in rows
            },
        )


def labelled(db: Session, machine_id: Any, pieces: Sequence[Any]) -> set[str]:
    """Which of these pieces of one machine (rows with piece_uuid and the
    training columns) have a training colour that counts: one read of the
    machine's excluded runs among theirs."""
    candidates = [p for p in pieces if counts(p.training_run_uuid, p.training_color_id, bool(p.training_excluded), False)]
    if not candidates:
        return set()
    excluded = excluded_runs(db, machine_id, {p.training_run_uuid for p in candidates})
    return {p.piece_uuid for p in candidates if p.training_run_uuid not in excluded}


# --- What the pages show -------------------------------------------------------------


def palette() -> dict[str, dict[str, Any]]:
    """BrickLink colours by id as a string (how sorters send them)."""
    return {str(c["id"]): c for c in get_profile_catalog_service().list_bricklink_colors()}


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


def colors_of(color_ids: Iterable[Any], colors: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for cid in color_ids or []:
        c = colors.get(str(cid)) or {}
        out.append({"id": str(cid), "name": c.get("name"), "rgb": c.get("rgb")})
    return out


def run_out(run: MachineTrainingRun, colors: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A run as the machine page lists it."""
    return {
        "run_uuid": run.run_uuid,
        "mode": run.mode,
        "color_ids": [str(c) for c in run.color_ids or []],
        "colors": colors_of(run.color_ids, colors),
        "started_at": _iso(run.started_at),
        "ended_at": _iso(run.ended_at),
        "excluded": bool(run.excluded),
        "pieces": run.piece_count,
        "labeled": run.labeled_count,
        "excluded_pieces": run.excluded_count,
    }


def _segment_out(segment: dict[str, Any], colors: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "segment_uuid": segment.get("segment_uuid"),
        "color_ids": [str(c) for c in segment.get("color_ids") or []],
        "colors": colors_of(segment.get("color_ids"), colors),
        "started_at": segment.get("started_at"),
        "ended_at": segment.get("ended_at"),
    }


def piece_training(db: Session, piece: MachinePiece) -> dict[str, Any] | None:
    """The training run a piece was seen in, the segment of it (the colours
    being fed then; None when the piece names none or the run has not synced
    it) and the colour it gives the piece, for the piece panel; None for a
    piece seen outside a run."""
    if not piece.training_run_uuid:
        return None
    run = (
        db.query(MachineTrainingRun)
        .filter(MachineTrainingRun.machine_id == piece.machine_id, MachineTrainingRun.run_uuid == piece.training_run_uuid)
        .first()
    )
    colors = palette()
    label = colors.get(str(piece.training_color_id)) if piece.training_color_id is not None else None
    run_excluded = bool(run.excluded) if run is not None else False
    segment = None
    if run is not None and piece.training_segment_uuid:
        segment = next(
            (s for s in run.segments or [] if isinstance(s, dict) and s.get("segment_uuid") == piece.training_segment_uuid),
            None,
        )
    return {
        "run_uuid": piece.training_run_uuid,
        "mode": run.mode if run is not None else None,
        "color_ids": [str(c) for c in run.color_ids or []] if run is not None else [],
        "colors": colors_of(run.color_ids, colors) if run is not None else [],
        "segment": _segment_out(segment, colors) if segment is not None else None,
        "color_id": piece.training_color_id,
        "color_name": label.get("name") if label else None,
        "color_rgb": label.get("rgb") if label else None,
        "label_source": piece.training_label_source,
        "excluded": bool(piece.training_excluded),
        "run_excluded": run_excluded,
        "counts": counts(piece.training_run_uuid, piece.training_color_id, bool(piece.training_excluded), run_excluded),
        "started_at": _iso(run.started_at) if run is not None else None,
        "ended_at": _iso(run.ended_at) if run is not None else None,
    }
