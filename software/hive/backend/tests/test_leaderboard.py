"""Regression tests for reviewer leaderboard aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.machine import Machine
from app.models.sample import Sample
from app.models.sample_review import SampleReview
from app.models.upload_session import UploadSession
from app.models.user import User
from tests.conftest import _login_user, _register_user


def _sample_with_review(
    db: Session,
    *,
    owner: User,
    reviewer: User,
    local_id: str,
    decision: str,
    reviewed_at: datetime,
) -> None:
    machine = Machine(
        owner_id=owner.id,
        token_hash=f"token-{local_id}",
        token_prefix=local_id[:8],
        name=f"Machine {local_id}",
    )
    db.add(machine)
    db.flush()

    upload_session = UploadSession(
        machine_id=machine.id,
        source_session_id=f"session-{local_id}",
        name=f"Session {local_id}",
    )
    db.add(upload_session)
    db.flush()

    sample = Sample(
        machine_id=machine.id,
        upload_session_id=upload_session.id,
        local_sample_id=local_id,
        image_path=f"samples/{local_id}.jpg",
        review_status="accepted" if decision == "accept" else "rejected",
        review_count=1,
        accepted_count=1 if decision == "accept" else 0,
        rejected_count=1 if decision == "reject" else 0,
        uploaded_at=reviewed_at,
    )
    db.add(sample)
    db.flush()

    db.add(
        SampleReview(
            sample_id=sample.id,
            reviewer_id=reviewer.id,
            decision=decision,
            created_at=reviewed_at,
            updated_at=reviewed_at,
        )
    )


def test_leaderboard_period_filter_runs_before_limit(client: TestClient, db: Session) -> None:
    _register_user(client, "viewer@test.com", "Password123!", "Viewer")
    _login_user(client, "viewer@test.com", "Password123!")

    owner = db.query(User).filter(User.email == "viewer@test.com").one()
    reviewer = User(email="reviewer@test.com", display_name="Reviewer", role="reviewer")
    db.add(reviewer)
    db.flush()

    now = datetime.now(timezone.utc)
    _sample_with_review(
        db,
        owner=owner,
        reviewer=reviewer,
        local_id="recent-accept",
        decision="accept",
        reviewed_at=now - timedelta(days=1),
    )
    _sample_with_review(
        db,
        owner=owner,
        reviewer=reviewer,
        local_id="recent-reject",
        decision="reject",
        reviewed_at=now - timedelta(days=2),
    )
    _sample_with_review(
        db,
        owner=owner,
        reviewer=reviewer,
        local_id="too-old",
        decision="accept",
        reviewed_at=now - timedelta(days=40),
    )
    db.commit()

    response = client.get(
        "/api/leaderboard?period=7d&limit=100",
        headers={"Origin": "http://localhost:5174"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:5174"
    body = response.json()
    assert body["period"] == "7d"
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["display_name"] == "Reviewer"
    assert entry["total_reviews"] == 2
    assert entry["accepts"] == 1
    assert entry["rejects"] == 1
