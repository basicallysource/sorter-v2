"""Per-role access control over the piece-bbox dataset (and owner-scoping for
samples).

Access rules enforced here:
  - admin    → everything, unrestricted.
  - member   → only their OWN machines' data. A random registrant who owns no
               machines (or someone else's) sees nothing — this is the anti-scrape
               guarantee.
  - reviewer → their own PLUS a bounded visibility window (a rolling slice of
               everyone's data) so review work has fresh material without exposing
               the whole corpus. Rate-limited on top.

A window is a contiguous slice ordered by upload time (see ``models.access_window``
for anchor semantics); sizes are tunable live per (role, entity) via the admin API.

Enforcement shape:
  - list/queue queries → ``apply_piece_access`` / ``apply_sample_access`` narrow
    the query to what the caller may see.
  - single-object reads (detail, crop images) → ``piece_access_visible`` /
    ``channel_crop_access_visible`` / ``sample_access_visible`` gate one row.
    Callers 404 (not 403) on a miss so a scoped user can't probe for the existence
    of rows outside their scope.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.models.access_window import AccessWindow
from app.models.machine import Machine
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_piece import MachinePiece
from app.models.sample import Sample
from app.models.user import User

ENTITY_PIECE = "piece"
ENTITY_CHANNEL_CROP = "channel_crop"
ENTITIES = (ENTITY_PIECE, ENTITY_CHANNEL_CROP)

ANCHOR_OLDEST = "oldest"
ANCHOR_NEWEST = "newest"
ANCHORS = (ANCHOR_OLDEST, ANCHOR_NEWEST)

# Roles that get a window. 'admin' is intentionally absent — admins are
# unrestricted. A role with no default and no DB row denies all (size 0).
WINDOWED_ROLES = ("member", "reviewer")


@dataclass(frozen=True)
class Window:
    anchor: str
    size: int
    offset: int


# Starting points, tunable live per (role, entity) via the admin API. Members get
# a small PINNED (oldest) slice; reviewers a large ROLLING (newest) one. Channel
# crops are ~10-20x more numerous than pieces, so their windows are sized up.
_DEFAULTS: dict[tuple[str, str], Window] = {
    ("member", ENTITY_PIECE): Window(ANCHOR_OLDEST, 200, 0),
    ("member", ENTITY_CHANNEL_CROP): Window(ANCHOR_OLDEST, 2000, 0),
    ("reviewer", ENTITY_PIECE): Window(ANCHOR_NEWEST, 5000, 0),
    ("reviewer", ENTITY_CHANNEL_CROP): Window(ANCHOR_NEWEST, 50000, 0),
}

# Deny-all fallback for a windowed role with no default configured.
_DENY = Window(ANCHOR_OLDEST, 0, 0)


def is_unrestricted(role: str) -> bool:
    return role == "admin"


def resolve_window(db: Session, role: str, entity: str) -> Window | None:
    """The effective window for a (role, entity), or None if unrestricted."""
    if is_unrestricted(role):
        return None
    row = (
        db.query(AccessWindow)
        .filter(AccessWindow.role == role, AccessWindow.entity == entity)
        .first()
    )
    if row is not None:
        return Window(row.anchor, int(row.size), int(row.offset))
    return _DEFAULTS.get((role, entity), _DENY)


def _model_for(entity: str):
    return MachinePiece if entity == ENTITY_PIECE else MachineChannelCrop


def _base_filters(entity: str):
    # Pieces exclude dead/spurious rows from the ordering so a member's small
    # window isn't wasted on junk. Channel crops have no such flag.
    if entity == ENTITY_PIECE:
        return (MachinePiece.dead.is_(False),)
    return ()


def _window_id_select(entity: str, win: Window):
    model = _model_for(entity)
    if win.anchor == ANCHOR_OLDEST:
        order = (model.created_at.asc(), model.id.asc())
    else:
        order = (model.created_at.desc(), model.id.desc())
    stmt = select(model.id)
    for f in _base_filters(entity):
        stmt = stmt.where(f)
    return stmt.order_by(*order).offset(win.offset).limit(win.size)


def _strictly_before(model, created_at, pk):
    return or_(model.created_at < created_at, and_(model.created_at == created_at, model.id < pk))


def _strictly_after(model, created_at, pk):
    return or_(model.created_at > created_at, and_(model.created_at == created_at, model.id > pk))


def _rank_visible(db: Session, entity: str, obj, win: Window) -> bool:
    """True iff ``obj`` falls inside the window, computed from its rank in the
    canonical ordering — an O(count) index scan, no need to materialize the slice."""
    if win.size <= 0:
        return False
    model = _model_for(entity)
    cmp = _strictly_after if win.anchor == ANCHOR_NEWEST else _strictly_before
    q = db.query(func.count()).select_from(model)
    for f in _base_filters(entity):
        q = q.filter(f)
    rank = q.filter(cmp(model, obj.created_at, obj.id)).scalar() or 0
    return win.offset <= rank < win.offset + win.size


def _owned_machine_ids(user: User):
    return select(Machine.id).where(Machine.owner_id == user.id)


def _machine_owned_by(db: Session, machine_id, user: User) -> bool:
    return (
        db.query(Machine.id)
        .filter(Machine.id == machine_id, Machine.owner_id == user.id)
        .first()
        is not None
    )


def _piece_window_key_select(win: Window):
    """Select of (machine_id, piece_uuid) for the pieces in a window — for scoping
    piece-derived rows (labels, crop-links) that key off that pair rather than id."""
    if win.anchor == ANCHOR_OLDEST:
        order = (MachinePiece.created_at.asc(), MachinePiece.id.asc())
    else:
        order = (MachinePiece.created_at.desc(), MachinePiece.id.desc())
    return (
        select(MachinePiece.machine_id, MachinePiece.piece_uuid)
        .where(MachinePiece.dead.is_(False))
        .order_by(*order)
        .offset(win.offset)
        .limit(win.size)
    )


# --- Piece-bbox access: admin=all, member=own machines only, reviewer=own+window --

def apply_piece_access(db: Session, query, user: User):
    """Narrow a MachinePiece query to what ``user`` may see: admins everything;
    members only their own machines' pieces; reviewers their own PLUS the reviewer
    visibility window (rolling slice of everyone's)."""
    if is_unrestricted(user.role):
        return query
    owned = MachinePiece.machine_id.in_(_owned_machine_ids(user))
    if user.role == "reviewer":
        win = resolve_window(db, "reviewer", ENTITY_PIECE)
        if win is not None and win.size > 0:
            return query.filter(or_(owned, MachinePiece.id.in_(_window_id_select(ENTITY_PIECE, win))))
    return query.filter(owned)


def scope_to_piece_access(db: Session, query, user: User, machine_col, piece_uuid_col):
    """Owner-or-window scoping for piece-derived tables (labels, crop-links) that
    key off (machine_id, piece_uuid)."""
    if is_unrestricted(user.role):
        return query
    owned = machine_col.in_(_owned_machine_ids(user))
    if user.role == "reviewer":
        win = resolve_window(db, "reviewer", ENTITY_PIECE)
        if win is not None and win.size > 0:
            return query.filter(
                or_(owned, tuple_(machine_col, piece_uuid_col).in_(_piece_window_key_select(win)))
            )
    return query.filter(owned)


def piece_access_visible(db: Session, user: User, piece: MachinePiece) -> bool:
    if is_unrestricted(user.role):
        return True
    if _machine_owned_by(db, piece.machine_id, user):
        return True
    if user.role == "reviewer" and not piece.dead:
        win = resolve_window(db, "reviewer", ENTITY_PIECE)
        if win is not None:
            return _rank_visible(db, ENTITY_PIECE, piece, win)
    return False


def piece_access_visible_by_key(db: Session, user: User, machine_id, piece_uuid: str) -> bool:
    """Access gate for endpoints keyed by (machine_id, piece_uuid) that don't
    already hold the row. Missing piece reads as not-visible (caller 404s)."""
    if is_unrestricted(user.role):
        return True
    piece = (
        db.query(MachinePiece)
        .filter(MachinePiece.machine_id == machine_id, MachinePiece.piece_uuid == piece_uuid)
        .first()
    )
    if piece is None:
        return False
    return piece_access_visible(db, user, piece)


def channel_crop_access_visible(db: Session, user: User, crop: MachineChannelCrop) -> bool:
    if is_unrestricted(user.role):
        return True
    if _machine_owned_by(db, crop.machine_id, user):
        return True
    if user.role == "reviewer":
        win = resolve_window(db, "reviewer", ENTITY_CHANNEL_CROP)
        if win is not None:
            return _rank_visible(db, ENTITY_CHANNEL_CROP, crop, win)
    return False


# --- Samples corpus access: admin+reviewer=all, member=own machines only. -------
# (No reviewer window on samples yet — that's the deferred "samples pass". The
# anti-scrape rule that matters — random members only see their own — is enforced.)

def apply_sample_access(db: Session, query, user: User):
    if user.role in ("admin", "reviewer"):
        return query
    return query.filter(Sample.machine.has(Machine.owner_id == user.id))


def sample_access_visible(db: Session, user: User, sample: Sample) -> bool:
    if user.role in ("admin", "reviewer"):
        return True
    return sample.machine is not None and str(sample.machine.owner_id) == str(user.id)


def list_effective_windows(db: Session) -> dict:
    """All windowed (role, entity) pairs with their effective values + whether the
    value comes from a DB override or the code default. Powers the admin view."""
    overrides = {
        (r.role, r.entity): r for r in db.query(AccessWindow).all()
    }
    windows = []
    for role in WINDOWED_ROLES:
        for entity in ENTITIES:
            row = overrides.get((role, entity))
            if row is not None:
                windows.append(
                    {
                        "role": role,
                        "entity": entity,
                        "anchor": row.anchor,
                        "size": int(row.size),
                        "offset": int(row.offset),
                        "source": "override",
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                )
            else:
                d = _DEFAULTS.get((role, entity), _DENY)
                windows.append(
                    {
                        "role": role,
                        "entity": entity,
                        "anchor": d.anchor,
                        "size": d.size,
                        "offset": d.offset,
                        "source": "default",
                        "updated_at": None,
                    }
                )
    return {"admin": "unrestricted", "windows": windows}


def set_window(db: Session, role: str, entity: str, anchor: str, size: int, offset: int) -> AccessWindow:
    row = (
        db.query(AccessWindow)
        .filter(AccessWindow.role == role, AccessWindow.entity == entity)
        .first()
    )
    if row is None:
        row = AccessWindow(role=role, entity=entity)
        db.add(row)
    row.anchor = anchor
    row.size = size
    row.offset = offset
    db.commit()
    db.refresh(row)
    return row
