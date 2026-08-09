"""Service-to-service aggregate stats.

Exposes the same aggregate analytics an admin sees on the all-machines page
(totals + daily time-series + distributions across every non-archived machine).
Meant for other basically services (e.g. the public website) to pull headline
numbers without a user session — regular Hive users cannot reach these
aggregate stats through the normal analytics API.

Auth, preferred: an `hv_*` API key carrying the `stats:read` scope, owned by an
admin and not machine-constrained (a machine-limited key must not read
fleet-wide aggregates). Legacy: the `settings.PUBLIC_STATS_API_KEY` shared
secret, presented as `Authorization: Bearer <key>` or `X-Stats-Key: <key>` —
kept only until every consumer holds a scoped key; delete the env var (and the
legacy branch below) after cutover.
"""

import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import API_KEY_PREFIX, API_KEY_SCOPE_STATS_READ, _resolve_api_key, get_db
from app.models.machine import Machine
from app.models.machine_daily_stats import MachineDailyStats
from app.models.machine_piece import MachinePiece
from app.models.user_identity import UserIdentity
from app.services import analytics

router = APIRouter(prefix="/api/public", tags=["public-stats"])

# The sorter fleet's local zone. The daily table buckets by UTC date, which makes
# "today" roll over mid-afternoon local time; the widget's UTC/local mismatch then
# showed 0 all evening. We additionally expose the day-in-progress and its piece
# count in this zone so the client can label a real local calendar day. Keep in
# sync with the widget's `SorterStats.sorterTimeZone`.
PUBLIC_STATS_LOCAL_TZ = "America/Los_Angeles"


def require_stats_key(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_stats_key: str | None = Header(default=None),
) -> None:
    presented = x_stats_key
    if not presented and authorization and authorization.startswith("Bearer "):
        presented = authorization[7:]
    presented = (presented or "").strip()

    # Preferred: a user API key with the stats:read scope.
    if presented.startswith(API_KEY_PREFIX):
        user, scopes, machine_ids = _resolve_api_key(db, presented)
        if API_KEY_SCOPE_STATS_READ not in scopes:
            raise HTTPException(status_code=403, detail="API key is missing required scopes: stats:read")
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if machine_ids is not None:
            raise HTTPException(
                status_code=403, detail="Machine-scoped API keys cannot read fleet-wide stats"
            )
        return

    # Legacy shared secret — delete once every consumer holds a scoped key.
    configured = (settings.PUBLIC_STATS_API_KEY or "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Public stats API is not configured")
    if not presented or not hmac.compare_digest(presented, configured):
        raise HTTPException(status_code=401, detail="Invalid stats API key")


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


@router.get("/fleet", dependencies=[Depends(require_stats_key)])
def get_public_fleet(db: Session = Depends(get_db)):
    """The fleet roster: every non-archived machine, with the owner's Discord
    identity attached only when that owner has linked one. Linking Discord is
    the opt-in — an unlinked owner appears as an anonymous machine."""
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
    machines = [
        {
            "id": str(machine.id),
            "name": machine.name,
            "is_active": machine.is_active,
            "last_seen_at": machine.last_seen_at.isoformat() if machine.last_seen_at else None,
            "created_at": machine.created_at.isoformat(),
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
