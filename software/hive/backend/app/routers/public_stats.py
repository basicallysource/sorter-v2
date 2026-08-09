"""Service-to-service fleet reporting, in two tiers.

**`GET /stats` is the anonymous tier** (scope `stats:read`): fleet-wide
aggregates — totals, a daily time-series, distributions — with no machine and
no person in the payload. This is what a consumer that is itself public may
hold: the website's headline numbers, a widget, anything cached at an edge.

**`GET /contributors` is the people tier** (scope `contributors:read`): who
has been labelling and reviewing, over four windows, with a linked Discord
identity where that person linked one. A third scope rather than reusing
`fleet:read`, because machine owners and contributors are different
populations and a key that should see one has no business seeing the other.

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
    API_KEY_SCOPE_CONTRIBUTORS_READ,
    API_KEY_SCOPE_FLEET_READ,
    API_KEY_SCOPE_STATS_READ,
    _resolve_api_key,
    get_db,
)
from app.models.machine import Machine
from app.models.machine_daily_stats import MachineDailyStats
from app.models.machine_piece import MachinePiece
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services import analytics, leaderboard, machine_stats

router = APIRouter(prefix="/api/public", tags=["public-stats"])

# The sorter fleet's local zone. The daily table buckets by UTC date, which makes
# "today" roll over mid-afternoon local time; the widget's UTC/local mismatch then
# showed 0 all evening. We additionally expose the day-in-progress and its piece
# count in this zone so the client can label a real local calendar day. Keep in
# sync with the widget's `SorterStats.sorterTimeZone`.
PUBLIC_STATS_LOCAL_TZ = "America/Los_Angeles"

# Lifetime pieces above which a machine is a REAL machine rather than a row in
# the machines table.
#
# Registering is free and a registration proves nothing: a bench that was
# powered on once, a duplicate somebody made while setting up, a unit that
# never got past its first bag. Counting those in "the fleet" inflates the
# denominator with machines that have never sorted anything, which makes every
# ratio built on it — how many are live, how many owners have claimed theirs —
# read worse than the truth and mean less than it should.
#
# 250 pieces is roughly one real run. It is deliberately low: the bar is "this
# thing has actually sorted", not "this thing is impressive". Consumers get
# BOTH counts and choose which to say — see the two counters on /fleet.
ACTIVE_MACHINE_MIN_PIECES = 250


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


def require_contributors_key(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_stats_key: str | None = Header(default=None),
) -> None:
    """The people tier: names and Discord ids, so a scoped key or nothing."""
    _require_scope(
        db,
        _presented_key(authorization, x_stats_key),
        API_KEY_SCOPE_CONTRIBUTORS_READ,
        allow_legacy=False,
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
    an hour-stale answer to that is a wrong one. The 30-day count is the one a
    leaderboard should rank on: a day is too short to mean much and a lifetime
    total is the same order forever.

    Every non-archived machine is listed, each flagged `is_active` against
    ACTIVE_MACHINE_MIN_PIECES, and both counts are returned. Filtering here
    would be the wrong call — a consumer that wants to know how many
    registrations exist can still ask — but `active_machine_count` is the
    number meant for people, and the balloon board says only that one.
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
    this_month = _pieces_by_machine_since(db, ids, hours=24 * 30)
    machines = []
    for machine, identity in rows:
        mid = str(machine.id)
        stats_row = lifetime.get(mid, {})
        pieces_seen = int(stats_row.get("pieces_seen") or 0)
        machines.append(
            {
                "id": mid,
                "name": machine.name,
                # NOTE: this is the FLEET-ACTIVE predicate — has this machine
                # sorted enough to be a real one (see ACTIVE_MACHINE_MIN_PIECES)
                # — and NOT the machines table's enabled flag, which used to be
                # served under this name and which no consumer of this endpoint
                # ever read. One endpoint, one meaning of "active".
                "is_active": pieces_seen > ACTIVE_MACHINE_MIN_PIECES,
                "last_seen_at": machine.last_seen_at.isoformat() if machine.last_seen_at else None,
                "created_at": machine.created_at.isoformat(),
                "pieces_seen": pieces_seen,
                "distributed": int(stats_row.get("distributed") or 0),
                "overall_ppm": float(stats_row.get("overall_ppm") or 0.0),
                "last_24h_pieces": recent.get(mid, 0),
                "last_hour_pieces": this_hour.get(mid, 0),
                "last_30d_pieces": this_month.get(mid, 0),
                "owner_discord": None
                if identity is None
                else {
                    "id": identity.provider_user_id,
                    "login": identity.provider_login,
                    "avatar_url": identity.avatar_url,
                },
            }
        )
    active = [m for m in machines if m["is_active"]]
    # Two counts, and a consumer says whichever it means. REGISTERED is the row
    # count and is the wrong number to put in front of people — it counts
    # benches that have never sorted a piece. ACTIVE is the fleet as anybody
    # would describe it out loud. The linked counts are given per population so
    # a ratio is never built out of two different denominators.
    return {
        "machines": machines,
        "active_threshold_pieces": ACTIVE_MACHINE_MIN_PIECES,
        "registered_machine_count": len(machines),
        "active_machine_count": len(active),
        "registered_discord_linked_count": sum(
            1 for m in machines if m["owner_discord"] is not None
        ),
        "active_discord_linked_count": sum(1 for m in active if m["owner_discord"] is not None),
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


# The windows served in one response. A consumer drawing a leaderboard wants
# all of them at once — asking four times for four rankings of the same people
# is four round trips and four chances for them to disagree.
CONTRIBUTOR_PERIODS = ("24h", "7d", "30d", "all")

# How deep each ranking goes. Well past anything a Discord message will show,
# and short enough that four rankings stay one cheap response.
CONTRIBUTOR_LIMIT = 50


@router.get("/contributors", dependencies=[Depends(require_contributors_key)])
def get_public_contributors(db: Session = Depends(get_db)):
    """Who has been labelling, over every window, with Discord where linked.

    WHAT IS DELIBERATELY NOT HERE. No email, obviously. No hive user id: a
    consumer of this needs to rank people and name the ones who opted in, and
    a stable internal identifier for everybody else is a correlation handle it
    has no use for. **And no avatar_url**, which is the non-obvious one — hive
    stores whatever avatar the person's OAuth provider gave, and a Discord
    avatar URL has that person's Discord snowflake embedded in the path.
    Serving it would hand out the Discord id of people who never linked their
    account, which is the exact thing the linkage is supposed to be their
    choice about.

    So an unlinked contributor is a display name and some counts, and nothing
    that reaches back to a person.
    """
    out: dict[str, list[dict]] = {}
    linked: dict[str, dict] = {}
    for period in CONTRIBUTOR_PERIODS:
        rows = leaderboard.get_leaderboard(db, period=period, limit=CONTRIBUTOR_LIMIT)
        ids = [r.user_id for r in rows]
        discord = _discord_by_user(db, ids)
        entries = []
        for r in rows:
            d = discord.get(str(r.user_id))
            if d is not None:
                linked[d["id"]] = d
            entries.append(
                {
                    "display_name": r.display_name,
                    "role": r.role,
                    "total_contributions": r.total_contributions,
                    "total_reviews": r.total_reviews,
                    "piece_color_labels": r.piece_color_labels,
                    "piece_crop_links": r.piece_crop_links,
                    "last_activity_at": r.last_review_at.isoformat() if r.last_review_at else None,
                    "discord": d,
                }
            )
        out[period] = entries
    return {
        "periods": out,
        "limit": CONTRIBUTOR_LIMIT,
        "discord_linked_count": len(linked),
    }


def _discord_by_user(db: Session, user_ids: list) -> dict[str, dict]:
    """The Discord identity for each of these users, where they linked one.

    Same join and the same opt-in rule as the fleet roster: absent means the
    person did not link, not merely that we are not showing it.
    """
    if not user_ids:
        return {}
    rows = (
        db.query(User.id, UserIdentity.provider_user_id, UserIdentity.provider_login)
        .join(
            UserIdentity,
            and_(UserIdentity.user_id == User.id, UserIdentity.provider == "discord"),
        )
        .filter(User.id.in_(user_ids))
        .all()
    )
    return {
        str(uid): {"id": provider_id, "login": login}
        for uid, provider_id, login in rows
    }
