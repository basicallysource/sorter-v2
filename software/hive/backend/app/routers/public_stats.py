"""Service-to-service fleet reporting, in two tiers.

**`GET /stats` is the anonymous tier** (scope `stats:read`): fleet-wide
aggregates — totals, a daily time-series, distributions — with no machine and
no person in the payload. This is what a consumer that is itself public may
hold: the website's headline numbers, a widget, anything cached at an edge.

**`GET /fleet` is the identified tier** (scope `fleet:read`): the roster. Which
machines exist, how much each has sorted, and the owner's Discord where that
owner linked one. Only for consumers whose credential is kept as well as the
data is — the balloon box, Spencer's phone — never a public website.

The split is enforced by SCOPE and not by convention, which is the whole point:
a key minted for the website carries `stats:read` alone and is refused the
roster, so leaking it costs aggregates rather than a list of owners. Both tiers
additionally require the key's owner to be an admin and the key to be
unconstrained; a machine-scoped key is strictly less powerful than its owner
and must not read fleet-wide anything.

Legacy: the `settings.PUBLIC_STATS_API_KEY` shared secret, presented as
`Authorization: Bearer <key>` or `X-Stats-Key: <key>`. It opens the ANONYMOUS
tier only — it predates the split, it is shared rather than per-consumer, and
it must never be a way around the scope that protects the roster. Kept until
every consumer holds a scoped key; delete the env var and the legacy branch
below after cutover.
"""

import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import (
    API_KEY_PREFIX,
    API_KEY_SCOPE_FLEET_READ,
    API_KEY_SCOPE_STATS_READ,
    _resolve_api_key,
    get_db,
)
from app.models.machine import Machine
from app.models.machine_daily_stats import MachineDailyStats
from app.models.machine_piece import MachinePiece
from app.models.user_identity import UserIdentity
from app.services import analytics, machine_stats

router = APIRouter(prefix="/api/public", tags=["public-stats"])

# The sorter fleet's local zone. The daily table buckets by UTC date, which makes
# "today" roll over mid-afternoon local time; the widget's UTC/local mismatch then
# showed 0 all evening. We additionally expose the day-in-progress and its piece
# count in this zone so the client can label a real local calendar day. Keep in
# sync with the widget's `SorterStats.sorterTimeZone`.
PUBLIC_STATS_LOCAL_TZ = "America/Los_Angeles"


def _presented_key(authorization: str | None, x_stats_key: str | None) -> str:
    presented = x_stats_key
    if not presented and authorization and authorization.startswith("Bearer "):
        presented = authorization[7:]
    return (presented or "").strip()


def _require_scope(db: Session, presented: str, scope: str, *, allow_legacy: bool) -> None:
    """Admit an admin-owned, unconstrained `hv_*` key carrying `scope`.

    `allow_legacy` says whether the shared secret is also accepted, and it is
    false for every tier above the aggregates. A shared secret cannot be
    revoked for one consumer or scoped to one tier, so letting it stand in for
    a scope would undo the split it predates.
    """
    if presented.startswith(API_KEY_PREFIX):
        user, scopes, machine_ids = _resolve_api_key(db, presented)
        if scope not in scopes:
            raise HTTPException(
                status_code=403, detail=f"API key is missing required scopes: {scope}"
            )
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if machine_ids is not None:
            raise HTTPException(
                status_code=403, detail="Machine-scoped API keys cannot read fleet-wide stats"
            )
        return

    if not allow_legacy:
        raise HTTPException(
            status_code=401, detail=f"This endpoint requires an API key with the {scope} scope"
        )
    # Legacy shared secret — delete once every consumer holds a scoped key.
    configured = (settings.PUBLIC_STATS_API_KEY or "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Public stats API is not configured")
    if not presented or not hmac.compare_digest(presented, configured):
        raise HTTPException(status_code=401, detail="Invalid stats API key")


def require_stats_key(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_stats_key: str | None = Header(default=None),
) -> None:
    """The anonymous tier: aggregates only, so the legacy secret still opens it."""
    _require_scope(
        db, _presented_key(authorization, x_stats_key), API_KEY_SCOPE_STATS_READ, allow_legacy=True
    )


def require_fleet_key(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_stats_key: str | None = Header(default=None),
) -> None:
    """The identified tier: machines and owners, so a scoped key or nothing."""
    _require_scope(
        db, _presented_key(authorization, x_stats_key), API_KEY_SCOPE_FLEET_READ, allow_legacy=False
    )


@router.get("/stats", dependencies=[Depends(require_stats_key)])
def get_public_stats(db: Session = Depends(get_db)):
    """Aggregate analytics across every non-archived machine — the same block the
    admin all-machines dashboard renders, minus any per-owner PII."""
    ids = [mid for (mid,) in db.query(Machine.id).filter(Machine.archived_at.is_(None)).all()]
    # Cold-start: populate the daily table on the first request if the worker
    # hasn't run yet, so stats aren't blank on a fresh deploy.
    if db.query(MachineDailyStats.machine_id).first() is None:
        try:
            analytics.refresh_daily_stats(db)
        except Exception:
            db.rollback()
    data = analytics.get_analytics(db, ids)
    return {
        "scope": {"kind": "all", "label": "All machines", "machine_count": len(ids)},
        "last_24h_pieces": _rolling_24h_pieces(db, ids),
        **_local_day_in_progress(db, ids),
        **data,
    }


@router.get("/fleet", dependencies=[Depends(require_fleet_key)])
def get_public_fleet(db: Session = Depends(get_db)):
    """The fleet roster: every non-archived machine, what it has sorted, and the
    owner's Discord identity attached only when that owner has linked one.

    Linking Discord is the opt-in — an unlinked owner appears as an anonymous
    machine, and no other owner field is ever served here (no email, no user id,
    no display name), so an unlinked owner is not merely unnamed but absent.

    The per-machine lifetime counters come from machine_stats_cache, which a
    worker refreshes hourly; reading them costs one indexed table scan rather
    than a recompute over machine_pieces. The trailing-hour and trailing-24h
    counts are computed live off the (machine_id, seen_at) index, because they
    are what a consumer uses to say whether a machine is working RIGHT NOW and
    an hour-stale answer to that is a wrong one.
    """
    rows = (
        db.query(Machine, UserIdentity)
        .outerjoin(
            UserIdentity,
            and_(
                UserIdentity.user_id == Machine.owner_id,
                UserIdentity.provider == "discord",
            ),
        )
        .filter(Machine.archived_at.is_(None))
        .order_by(Machine.created_at)
        .all()
    )
    ids = [machine.id for machine, _ in rows]
    lifetime = machine_stats.get_fleet_stats(db)
    recent = _pieces_by_machine_since(db, ids, hours=24)
    this_hour = _pieces_by_machine_since(db, ids, hours=1)
    machines = [
        {
            "id": str(machine.id),
            "name": machine.name,
            "is_active": machine.is_active,
            "last_seen_at": machine.last_seen_at.isoformat() if machine.last_seen_at else None,
            "created_at": machine.created_at.isoformat(),
            "pieces_seen": int(lifetime.get(str(machine.id), {}).get("pieces_seen") or 0),
            "distributed": int(lifetime.get(str(machine.id), {}).get("distributed") or 0),
            "overall_ppm": float(lifetime.get(str(machine.id), {}).get("overall_ppm") or 0.0),
            "last_24h_pieces": recent.get(str(machine.id), 0),
            "last_hour_pieces": this_hour.get(str(machine.id), 0),
            "owner_discord": None
            if identity is None
            else {
                "id": identity.provider_user_id,
                "login": identity.provider_login,
                "avatar_url": identity.avatar_url,
            },
        }
        for machine, identity in rows
    ]
    return {
        "machines": machines,
        "machine_count": len(machines),
        "discord_linked_count": sum(1 for m in machines if m["owner_discord"] is not None),
    }


def _pieces_by_machine_since(db: Session, ids: list, *, hours: int) -> dict[str, int]:
    """Piece count per machine over a trailing window.

    The 24h call uses the same window as the fleet-wide number in /stats, so a
    leaderboard and the headline agree. The 1h call is what tells a consumer a
    machine is actually sorting rather than merely powered on.
    """
    if not ids:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(MachinePiece.machine_id, func.count())
        .filter(MachinePiece.machine_id.in_(ids))
        .filter(MachinePiece.seen_at >= cutoff)
        .group_by(MachinePiece.machine_id)
        .all()
    )
    return {str(mid): int(n) for mid, n in rows}


def _rolling_24h_pieces(db: Session, ids: list) -> int:
    """Pieces seen in the trailing 24 hours — a rolling window, not a calendar day.

    Preferred over either day-in-progress number for a live readout: it never
    resets to 0 at a midnight the reader doesn't share, so no zone has to agree
    with any other. Uses the (machine_id, seen_at) index; rows with a NULL
    seen_at drop out of the comparison, same as everywhere else.
    """
    if not ids:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    return int(
        db.query(func.count())
        .select_from(MachinePiece)
        .filter(MachinePiece.machine_id.in_(ids))
        .filter(MachinePiece.seen_at >= cutoff)
        .scalar()
        or 0
    )


def _local_day_in_progress(db: Session, ids: list) -> dict:
    """Day-in-progress and its piece count bucketed in PUBLIC_STATS_LOCAL_TZ.

    Postgres only (prod); the local-zone date math relies on ``timezone()``.
    Elsewhere (SQLite tests) return nothing and the client keeps its UTC fallback.
    """
    if db.bind.dialect.name != "postgresql":
        return {}
    today_local = db.query(func.date(func.timezone(PUBLIC_STATS_LOCAL_TZ, func.now()))).scalar()
    piece_local_date = func.date(func.timezone(PUBLIC_STATS_LOCAL_TZ, MachinePiece.seen_at))
    pieces = (
        db.query(func.count())
        .select_from(MachinePiece)
        .filter(MachinePiece.machine_id.in_(ids))
        .filter(piece_local_date == today_local)
        .scalar()
    ) or 0
    return {"last_day_local": today_local.isoformat(), "last_day_local_pieces": int(pieces)}
