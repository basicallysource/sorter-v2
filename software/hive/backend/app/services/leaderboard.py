"""Reviewer leaderboard + achievement computation.

Everything in here is *derived* from existing ``sample_reviews`` and
``samples`` rows — no extra storage. The numbers move when the
underlying data does, so a reviewer who slows down naturally falls off
the streak achievements without any background job touching state.

Achievements are intentionally light: 10 hand-picked milestones plus
streak / speed / quality / variety axes. The set is small enough that
recomputing the entire achievement bundle on each profile-page hit is
sub-100ms even at 100k+ reviews.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, literal, select, text
from sqlalchemy.orm import Session

from app.models.piece_color_label import PieceColorLabel
from app.models.piece_crop_link import PieceCropLink
from app.models.sample import Sample
from app.models.sample_review import SampleReview
from app.models.user import User


# ----------------------------------------------------------------------- periods

PERIOD_TO_HOURS: dict[str, int | None] = {
    "24h": 24,
    "7d": 24 * 7,
    "30d": 24 * 30,
    "all": None,
}


def _cutoff(period: str) -> datetime | None:
    hours = PERIOD_TO_HOURS.get(period)
    if hours is None:
        return None
    return datetime.now(timezone.utc) - timedelta(hours=hours)


# ----------------------------------------------------------------------- list


@dataclass(slots=True)
class LeaderboardRow:
    user_id: UUID
    display_name: str | None
    avatar_url: str | None
    role: str
    total_reviews: int
    accepts: int
    rejects: int
    piece_color_labels: int
    piece_crop_links: int
    total_contributions: int  # reviews + color labels + same-piece links
    last_review_at: datetime | None  # last activity across all sources


def _max_dt(*values: datetime | None) -> datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def get_leaderboard(db: Session, *, period: str, limit: int = 100) -> list[LeaderboardRow]:
    """Ranked contributor list across all labeling work: sample reviews plus
    piece color labels and same-piece crop links.

    Includes anyone with at least one contribution in the period; ordered by
    total contributions desc, then display_name asc for ties.
    """

    cutoff = _cutoff(period)

    review_q = db.query(
        SampleReview.reviewer_id.label("uid"),
        func.count(SampleReview.id).label("total"),
        func.sum(case((SampleReview.decision == "accept", 1), else_=0)).label("accepts"),
        func.sum(case((SampleReview.decision == "reject", 1), else_=0)).label("rejects"),
        func.max(SampleReview.created_at).label("last_at"),
    )
    color_q = db.query(
        PieceColorLabel.labeler_id.label("uid"),
        func.count(PieceColorLabel.id).label("cnt"),
        func.max(PieceColorLabel.created_at).label("last_at"),
    )
    crop_q = db.query(
        PieceCropLink.labeler_id.label("uid"),
        func.count(PieceCropLink.id).label("cnt"),
        func.max(PieceCropLink.created_at).label("last_at"),
    )
    if cutoff is not None:
        review_q = review_q.filter(SampleReview.created_at >= cutoff)
        color_q = color_q.filter(PieceColorLabel.created_at >= cutoff)
        crop_q = crop_q.filter(PieceCropLink.created_at >= cutoff)
    review_rows = review_q.group_by(SampleReview.reviewer_id).all()
    color_rows = color_q.group_by(PieceColorLabel.labeler_id).all()
    crop_rows = crop_q.group_by(PieceCropLink.labeler_id).all()

    agg: dict[UUID, dict[str, Any]] = {}

    def _slot(uid: UUID) -> dict[str, Any]:
        return agg.setdefault(
            uid,
            {"total": 0, "accepts": 0, "rejects": 0, "color": 0, "crop": 0, "last_at": None},
        )

    for r in review_rows:
        s = _slot(r.uid)
        s["total"] = int(r.total or 0)
        s["accepts"] = int(r.accepts or 0)
        s["rejects"] = int(r.rejects or 0)
        s["last_at"] = _max_dt(s["last_at"], r.last_at)
    for r in color_rows:
        s = _slot(r.uid)
        s["color"] = int(r.cnt or 0)
        s["last_at"] = _max_dt(s["last_at"], r.last_at)
    for r in crop_rows:
        s = _slot(r.uid)
        s["crop"] = int(r.cnt or 0)
        s["last_at"] = _max_dt(s["last_at"], r.last_at)

    if not agg:
        return []

    users = {
        u.id: u
        for u in db.query(User.id, User.display_name, User.avatar_url, User.role).filter(User.id.in_(agg.keys())).all()
    }

    rows = [
        LeaderboardRow(
            user_id=uid,
            display_name=users[uid].display_name if uid in users else None,
            avatar_url=users[uid].avatar_url if uid in users else None,
            role=users[uid].role if uid in users else "member",
            total_reviews=s["total"],
            accepts=s["accepts"],
            rejects=s["rejects"],
            piece_color_labels=s["color"],
            piece_crop_links=s["crop"],
            total_contributions=s["total"] + s["color"] + s["crop"],
            last_review_at=s["last_at"],
        )
        for uid, s in agg.items()
        if uid in users
    ]
    rows.sort(key=lambda r: (-r.total_contributions, (r.display_name or "").lower()))
    return rows[:limit]


# ----------------------------------------------------------------------- profile


@dataclass(slots=True)
class ReviewerProfile:
    user_id: UUID
    display_name: str | None
    avatar_url: str | None
    role: str
    total_reviews: int
    accepts: int
    rejects: int
    piece_color_labels: int
    piece_crop_links: int
    total_contributions: int  # reviews + color labels + same-piece links
    agreement_rate: float | None  # 0..1 (None if no conclusive samples reviewed)
    machines_covered: int
    current_streak_days: int
    longest_streak_days: int
    speed_record_24h: int
    first_review_at: datetime | None
    last_review_at: datetime | None
    daily_counts: list[int]  # last 14 days, oldest first
    achievements: list[dict[str, Any]]


def _agreement_rate(db: Session, user_id: UUID) -> float | None:
    """How often did this reviewer's vote match the final consensus on
    samples that reached a conclusive status?

    Only counts accepted / rejected samples (skips conflict — by definition
    no clean majority) and samples where this user voted.
    """

    rows = (
        db.query(SampleReview.decision, Sample.review_status)
        .join(Sample, Sample.id == SampleReview.sample_id)
        .filter(SampleReview.reviewer_id == user_id)
        .filter(Sample.review_status.in_(("accepted", "rejected")))
        .all()
    )
    if not rows:
        return None
    agreed = sum(1 for decision, status in rows if decision == status.split("_")[0])  # accept/reject
    return agreed / len(rows)


def _streak_days(db: Session, user_id: UUID) -> tuple[int, int]:
    """(current_streak_days, longest_streak_days) — consecutive UTC days
    where the user submitted at least one review.

    Pure-Python after one DISTINCT-day query; cheap even for power users
    since at most one row per day they reviewed.
    """

    rows = (
        db.query(func.date(SampleReview.created_at).label("d"))
        .filter(SampleReview.reviewer_id == user_id)
        .distinct()
        .order_by("d")
        .all()
    )
    if not rows:
        return (0, 0)
    days = sorted({r.d for r in rows})

    # Longest streak across all history.
    longest = current_run = 1
    for prev, cur in zip(days, days[1:]):
        if (cur - prev).days == 1:
            current_run += 1
            longest = max(longest, current_run)
        else:
            current_run = 1

    # Current streak only counts if the most recent day is today or yesterday
    # (a missed day breaks the streak even if you'd otherwise have a long one).
    today = datetime.now(timezone.utc).date()
    if (today - days[-1]).days > 1:
        current = 0
    else:
        current = 1
        for i in range(len(days) - 1, 0, -1):
            if (days[i] - days[i - 1]).days == 1:
                current += 1
            else:
                break
    return (current, longest)


def _speed_record_24h(db: Session, user_id: UUID) -> int:
    """Most reviews this user has ever submitted in any 24-hour window."""

    # Quick and approximate: max-per-calendar-day. Real sliding-window would
    # need a window function; this approximation is plenty for an achievement.
    row = (
        db.query(func.count("*").label("c"))
        .filter(SampleReview.reviewer_id == user_id)
        .group_by(func.date(SampleReview.created_at))
        .order_by(func.count("*").desc())
        .limit(1)
        .first()
    )
    return int(row.c) if row else 0


def _machines_covered(db: Session, user_id: UUID) -> int:
    """How many distinct machines this reviewer has touched samples from."""

    row = (
        db.query(func.count(func.distinct(Sample.machine_id)))
        .join(SampleReview, SampleReview.sample_id == Sample.id)
        .filter(SampleReview.reviewer_id == user_id)
        .scalar()
    )
    return int(row or 0)


def _daily_counts(db: Session, user_id: UUID, *, days: int = 14) -> list[int]:
    """Per-day review counts for the last ``days`` days, oldest first.

    Returns a fixed-length list so the frontend sparkline always has the
    same number of buckets, even on days the user didn't review.
    """

    cutoff = datetime.now(timezone.utc) - timedelta(days=days - 1)
    cutoff_date = cutoff.date()
    rows = (
        db.query(func.date(SampleReview.created_at).label("d"), func.count("*").label("c"))
        .filter(SampleReview.reviewer_id == user_id, SampleReview.created_at >= cutoff)
        .group_by("d")
        .all()
    )
    by_day = {r.d: int(r.c) for r in rows}
    today = datetime.now(timezone.utc).date()
    out: list[int] = []
    for i in range(days):
        day = cutoff_date + timedelta(days=i)
        out.append(by_day.get(day, 0))
        if day > today:
            break
    return out


# ----------------------------------------------------------------------- achievements


@dataclass(frozen=True, slots=True)
class AchievementDef:
    slug: str
    name: str
    description: str
    icon: str  # emoji — frontend can swap for SVG later if needed
    tier: str  # 'bronze' | 'silver' | 'gold' | 'special'


ACHIEVEMENTS: tuple[AchievementDef, ...] = (
    AchievementDef("first_steps", "First Steps", "Submit your first review.", "🌱", "bronze"),
    AchievementDef("century", "Century", "Submit 100 reviews.", "💯", "bronze"),
    AchievementDef("marathon", "Marathon", "Submit 1,000 reviews.", "🏃", "silver"),
    AchievementDef("legend", "Legend", "Submit 10,000 reviews.", "🏆", "gold"),
    AchievementDef("speed_reviewer", "Speed Reviewer", "Submit 50+ reviews in a single day.", "⚡", "silver"),
    AchievementDef("daily_devotee", "Daily Devotee", "Review on 7 consecutive days.", "🌅", "silver"),
    AchievementDef("burning_streak", "Burning Streak", "Review on 30 consecutive days.", "🔥", "gold"),
    AchievementDef("perfect_pitch", "Perfect Pitch", "Reach ≥90% consensus agreement (min 50 reviews).", "🎯", "gold"),
    AchievementDef("diverse_reviewer", "Diverse Reviewer", "Review samples from 5+ different machines.", "🦋", "silver"),
    AchievementDef("tiebreaker", "Tiebreaker", "Be the deciding vote on 10+ samples that reached a final verdict.", "🤝", "gold"),
)


def _earned_achievements(*, totals: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate every achievement against the precomputed profile stats.

    Returns the static definition merged with an ``earned`` boolean and,
    when earned, a short progress string for UI ("3 / 7 days").
    """

    out: list[dict[str, Any]] = []
    for a in ACHIEVEMENTS:
        earned, progress = _evaluate(a.slug, totals)
        out.append({
            "slug": a.slug,
            "name": a.name,
            "description": a.description,
            "icon": a.icon,
            "tier": a.tier,
            "earned": earned,
            "progress": progress,
        })
    return out


def _evaluate(slug: str, t: dict[str, Any]) -> tuple[bool, str]:
    total = t["total_reviews"]
    agreement = t["agreement_rate"]
    machines = t["machines_covered"]
    streak = t["longest_streak_days"]
    speed = t["speed_record_24h"]
    tiebreaks = t["tiebreaker_count"]

    if slug == "first_steps":
        return (total >= 1, f"{min(total, 1)} / 1")
    if slug == "century":
        return (total >= 100, f"{min(total, 100)} / 100")
    if slug == "marathon":
        return (total >= 1000, f"{min(total, 1000)} / 1000")
    if slug == "legend":
        return (total >= 10_000, f"{min(total, 10_000)} / 10,000")
    if slug == "speed_reviewer":
        return (speed >= 50, f"best day: {speed} reviews")
    if slug == "daily_devotee":
        return (streak >= 7, f"{min(streak, 7)} / 7 day streak")
    if slug == "burning_streak":
        return (streak >= 30, f"{min(streak, 30)} / 30 day streak")
    if slug == "perfect_pitch":
        if agreement is None or total < 50:
            return (False, f"{total} / 50 reviews to qualify")
        pct = round(agreement * 100, 1)
        return (agreement >= 0.9, f"{pct}% agreement")
    if slug == "diverse_reviewer":
        return (machines >= 5, f"{min(machines, 5)} / 5 machines")
    if slug == "tiebreaker":
        return (tiebreaks >= 10, f"{min(tiebreaks, 10)} / 10 tiebreaks")
    return (False, "")


def _tiebreaker_count(db: Session, user_id: UUID) -> int:
    """How many conclusive samples did this reviewer's vote push over the line?

    A tiebreaker = the reviewer's vote was on a sample that ended up
    accepted or rejected, AND that vote matched the final consensus, AND
    the reviewer's vote was among the last 1-2 chronologically (i.e. they
    were "the one who sealed it"). Approximation: any vote on an
    accepted/rejected sample where the reviewer's vote matched final
    AND the sample's review_count == REVIEW_CONSENSUS_TARGET (so they
    were one of the closers).
    """

    from app.config import settings

    cap = max(1, int(settings.REVIEW_CONSENSUS_TARGET))
    row = (
        db.query(func.count("*"))
        .select_from(SampleReview)
        .join(Sample, Sample.id == SampleReview.sample_id)
        .filter(SampleReview.reviewer_id == user_id)
        .filter(Sample.review_status.in_(("accepted", "rejected")))
        .filter(Sample.review_count >= cap)
        .filter(
            (
                (SampleReview.decision == "accept")
                & (Sample.review_status == "accepted")
            )
            | (
                (SampleReview.decision == "reject")
                & (Sample.review_status == "rejected")
            )
        )
        .scalar()
    )
    return int(row or 0)


def get_reviewer_profile(db: Session, user_id: UUID) -> ReviewerProfile | None:
    """Full stat bundle for one reviewer's profile + dashboard widget."""

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None

    totals = (
        db.query(
            func.count("*").label("total"),
            func.sum(case((SampleReview.decision == "accept", 1), else_=0)).label("accepts"),
            func.sum(case((SampleReview.decision == "reject", 1), else_=0)).label("rejects"),
            func.min(SampleReview.created_at).label("first_at"),
            func.max(SampleReview.created_at).label("last_at"),
        )
        .filter(SampleReview.reviewer_id == user_id)
        .first()
    )
    total = int(totals.total or 0) if totals else 0
    accepts = int(totals.accepts or 0) if totals else 0
    rejects = int(totals.rejects or 0) if totals else 0

    color_labels = (
        db.query(func.count(PieceColorLabel.id)).filter(PieceColorLabel.labeler_id == user_id).scalar() or 0
    )
    crop_links = db.query(func.count(PieceCropLink.id)).filter(PieceCropLink.labeler_id == user_id).scalar() or 0

    agreement = _agreement_rate(db, user_id)
    machines = _machines_covered(db, user_id)
    current_streak, longest_streak = _streak_days(db, user_id)
    speed = _speed_record_24h(db, user_id)
    tiebreaks = _tiebreaker_count(db, user_id)
    sparkline = _daily_counts(db, user_id)

    raw_totals = {
        "total_reviews": total,
        "agreement_rate": agreement,
        "machines_covered": machines,
        "longest_streak_days": longest_streak,
        "speed_record_24h": speed,
        "tiebreaker_count": tiebreaks,
    }
    achievements = _earned_achievements(totals=raw_totals)

    return ReviewerProfile(
        user_id=user.id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=user.role,
        total_reviews=total,
        accepts=accepts,
        rejects=rejects,
        piece_color_labels=int(color_labels),
        piece_crop_links=int(crop_links),
        total_contributions=total + int(color_labels) + int(crop_links),
        agreement_rate=agreement,
        machines_covered=machines,
        current_streak_days=current_streak,
        longest_streak_days=longest_streak,
        speed_record_24h=speed,
        first_review_at=totals.first_at if totals else None,
        last_review_at=totals.last_at if totals else None,
        daily_counts=sparkline,
        achievements=achievements,
    )


__all__ = [
    "ACHIEVEMENTS",
    "LeaderboardRow",
    "PERIOD_TO_HOURS",
    "ReviewerProfile",
    "get_leaderboard",
    "get_reviewer_profile",
]
