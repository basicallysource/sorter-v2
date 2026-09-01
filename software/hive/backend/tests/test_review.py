"""Tests for the review workflow endpoints."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from tests.conftest import (
    _auth_headers,
    _login_user,
    _register_user,
    make_test_image,
)


def _upload_sample(
    client: TestClient,
    machine_token: str,
    session_id: str = "sess-review",
    sample_id: str = "sample-review",
) -> dict:
    """Upload a sample for review testing."""
    metadata = json.dumps(
        {
            "source_session_id": session_id,
            "local_sample_id": sample_id,
        }
    )
    image = make_test_image()
    resp = client.post(
        "/api/machine/upload",
        headers={"Authorization": f"Bearer {machine_token}"},
        data={"metadata": metadata},
        files={"image": ("test.png", image, "image/png")},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _make_reviewer(
    client: TestClient, db: Session, email: str, password: str = "Password123!"
) -> dict[str, str]:
    """Register a user, promote to reviewer, log in, and return auth info."""
    _register_user(client, email, password, email.split("@")[0])
    user = db.query(User).filter(User.email == email).first()
    user.role = "reviewer"
    db.commit()
    _login_user(client, email, password)
    return {"email": email, "password": password, "headers": _auth_headers(client)}


class TestReviewQueue:
    def test_review_queue_next(
        self,
        client: TestClient,
        test_reviewer: dict,
        machine_token: str,
        upload_dir: str,
        db: Session,
    ) -> None:
        _upload_sample(client, machine_token, "sess-q", "s1")

        # Log in as reviewer
        _login_user(client, test_reviewer["email"], test_reviewer["password"])
        headers = _auth_headers(client)

        resp = client.get("/api/review/queue/next", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert "id" in data


class TestSubmitReview:
    def test_submit_review_accept(
        self,
        client: TestClient,
        test_reviewer: dict,
        machine_token: str,
        upload_dir: str,
        db: Session,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-ra", "s1")
        sample_id = sample["id"]

        _login_user(client, test_reviewer["email"], test_reviewer["password"])
        headers = _auth_headers(client)

        resp = client.post(
            f"/api/review/samples/{sample_id}",
            json={"decision": "accept", "notes": "Looks good"},
            headers=headers,
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data.get("decision") == "accept"

    def test_submit_review_reject(
        self,
        client: TestClient,
        test_reviewer: dict,
        machine_token: str,
        upload_dir: str,
        db: Session,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-rr", "s1")
        sample_id = sample["id"]

        _login_user(client, test_reviewer["email"], test_reviewer["password"])
        headers = _auth_headers(client)

        resp = client.post(
            f"/api/review/samples/{sample_id}",
            json={"decision": "reject", "notes": "Bad quality"},
            headers=headers,
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data.get("decision") == "reject"


class TestReviewAggregation:
    def test_unanimous_accepts_make_accepted(
        self,
        client: TestClient,
        machine_token: str,
        upload_dir: str,
        db: Session,
    ) -> None:
        # Consensus needs MIN_REVIEWS_FOR_CONSENSUS (3) agreeing reviews.
        sample = _upload_sample(client, machine_token, "sess-2a", "s1")
        sample_id = sample["id"]

        headers = None
        for i, email in enumerate(("reva@test.com", "revb@test.com", "revc@test.com")):
            rev = _make_reviewer(client, db, email)
            _login_user(client, rev["email"], rev["password"])
            headers = _auth_headers(client)
            resp = client.post(
                f"/api/review/samples/{sample_id}",
                json={"decision": "accept"},
                headers=headers,
            )
            assert resp.status_code in (200, 201)

        # Check sample status is now accepted (reuse the last reviewer's session).
        detail = client.get(f"/api/samples/{sample_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["review_status"] == "accepted"

    def test_unanimous_rejects_make_rejected(
        self,
        client: TestClient,
        machine_token: str,
        upload_dir: str,
        db: Session,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-2r", "s1")
        sample_id = sample["id"]

        headers = None
        for email in ("rejA@test.com", "rejB@test.com", "rejC@test.com"):
            rev = _make_reviewer(client, db, email)
            _login_user(client, rev["email"], rev["password"])
            headers = _auth_headers(client)
            client.post(
                f"/api/review/samples/{sample_id}",
                json={"decision": "reject"},
                headers=headers,
            )

        detail = client.get(f"/api/samples/{sample_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["review_status"] == "rejected"

    def test_mixed_reviews_make_conflict(
        self,
        client: TestClient,
        machine_token: str,
        upload_dir: str,
        db: Session,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-mix", "s1")
        sample_id = sample["id"]

        # 3 reviews (consensus reached) that don't all agree → conflict.
        headers = None
        for email, decision in (
            ("mixA@test.com", "accept"),
            ("mixB@test.com", "reject"),
            ("mixC@test.com", "accept"),
        ):
            rev = _make_reviewer(client, db, email)
            _login_user(client, rev["email"], rev["password"])
            headers = _auth_headers(client)
            client.post(
                f"/api/review/samples/{sample_id}",
                json={"decision": decision},
                headers=headers,
            )

        detail = client.get(f"/api/samples/{sample_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["review_status"] == "conflict"


class TestReviewEdgeCases:
    def test_reviewer_cannot_review_twice(
        self,
        client: TestClient,
        test_reviewer: dict,
        machine_token: str,
        upload_dir: str,
        db: Session,
    ) -> None:
        """Second review from the same reviewer should update, not create a duplicate."""
        sample = _upload_sample(client, machine_token, "sess-dup", "s1")
        sample_id = sample["id"]

        _login_user(client, test_reviewer["email"], test_reviewer["password"])
        headers = _auth_headers(client)

        # First review: accept
        resp1 = client.post(
            f"/api/review/samples/{sample_id}",
            json={"decision": "accept"},
            headers=headers,
        )
        assert resp1.status_code in (200, 201)

        # Second review from same reviewer: reject (should update)
        resp2 = client.post(
            f"/api/review/samples/{sample_id}",
            json={"decision": "reject"},
            headers=headers,
        )
        assert resp2.status_code == 200
        assert resp2.json()["decision"] == "reject"

        # Verify only one review exists for this reviewer
        history = client.get(
            f"/api/review/samples/{sample_id}/history", headers=headers
        )
        assert history.status_code == 200
        reviews = history.json()["reviews"]
        assert len(reviews) == 1
        assert reviews[0]["decision"] == "reject"

    def test_member_cannot_review(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        """A user with 'member' role should not be able to submit reviews."""
        sample = _upload_sample(client, machine_token, "sess-norole", "s1")
        sample_id = sample["id"]

        # test_user is a member, not a reviewer
        resp = client.post(
            f"/api/review/samples/{sample_id}",
            json={"decision": "accept"},
            headers=auth_headers,
        )
        assert resp.status_code == 403


class TestReviewHistory:
    def test_review_history(
        self,
        client: TestClient,
        machine_token: str,
        upload_dir: str,
        db: Session,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-hist", "s1")
        sample_id = sample["id"]

        # Two reviewers submit reviews
        rev_a = _make_reviewer(client, db, "histA@test.com")
        _login_user(client, rev_a["email"], rev_a["password"])
        client.post(
            f"/api/review/samples/{sample_id}",
            json={"decision": "accept", "notes": "Good"},
            headers=_auth_headers(client),
        )

        rev_b = _make_reviewer(client, db, "histB@test.com")
        _login_user(client, rev_b["email"], rev_b["password"])
        client.post(
            f"/api/review/samples/{sample_id}",
            json={"decision": "reject", "notes": "Bad quality"},
            headers=_auth_headers(client),
        )

        # Check history
        resp = client.get(
            f"/api/review/samples/{sample_id}/history",
            headers=_auth_headers(client),
        )
        assert resp.status_code == 200
        data = resp.json()
        reviews = data["reviews"]
        assert len(reviews) >= 2
        decisions = {r["decision"] for r in reviews}
        assert "accept" in decisions
        assert "reject" in decisions
