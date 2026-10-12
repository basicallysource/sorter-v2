"""The Channel samples queue: one machine or several, keyset pages, the review
queue's fresh work, and the batch actions acting on exactly what is shown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.machine import Machine
from app.models.sample import Sample
from app.models.sample_review import SampleReview
from app.models.upload_session import UploadSession
from app.models.user import User
from tests.conftest import _auth_headers, refresh_stats

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _me(db: Session) -> User:
    return db.query(User).filter(User.email == "member@test.com").one()


@pytest.fixture()
def samples(client: TestClient, db: Session, test_user: dict) -> dict:
    me = _me(db)
    other = User(email="other@test.com", display_name="Other", role="member")
    db.add(other)
    db.commit()
    machines = {}
    for name, owner in (("a", me), ("b", me), ("c", me), ("theirs", other)):
        m = Machine(owner_id=owner.id, token_hash=f"h-{name}", token_prefix=name, name=name)
        db.add(m)
        db.flush()
        session = UploadSession(machine_id=m.id, source_session_id=f"s-{name}", name=name)
        db.add(session)
        db.flush()
        machines[name] = (m.id, session.id)
    order = []
    # 21 samples interleaved across the machines, some sharing an upload time.
    for i in range(21):
        name = ["a", "b", "c", "theirs"][i % 4] if i < 20 else "a"
        mid, sid = machines[name]
        uploaded = NOW - timedelta(minutes=i // 2)
        sample = Sample(
            machine_id=mid,
            upload_session_id=sid,
            local_sample_id=f"{name}-{i}",
            image_path=f"{mid}/samples/{i}.jpg",
            source_role="c_channel_2" if i % 3 else "classification_chamber",
            capture_reason="live",
            review_status="accepted" if i % 7 == 0 else "unreviewed",
            review_count=3 if i % 7 == 0 else 0,
            uploaded_at=uploaded,
        )
        db.add(sample)
        db.flush()
        order.append((name, sample.id, uploaded))
    db.commit()
    return {"machines": machines, "order": order, "me": me}


def _walk(client, limit=2, **params) -> list[dict]:
    items, cursor = [], None
    for _ in range(50):
        query = {"limit": limit, "annotated": "all", **params}
        if cursor:
            query["cursor"] = cursor
        resp = client.get("/api/samples", params=query, headers=_auth_headers(client))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        items.extend(body["items"])
        assert body["has_more"] == (body["next_cursor"] is not None)
        cursor = body["next_cursor"]
        if not cursor:
            return items
    raise AssertionError("paging never ended")


def _expected(samples: dict, names: set[str], needs_review_for=None) -> list[str]:
    rows = [(uploaded, str(sid)) for name, sid, uploaded in samples["order"] if name in names]
    rows.sort(reverse=True)  # newest first, then id, both descending
    return [sid for _, sid in rows]


@pytest.mark.parametrize("names", [["a"], ["a", "c"], ["b", "c"]])
def test_machine_filter_pages_only_those_machines(client, samples, names):
    ids = [str(samples["machines"][n][0]) for n in names]
    got = _walk(client, machine_id=ids)
    assert {s["machine_id"] for s in got} <= set(ids)
    assert [s["id"] for s in got] == _expected(samples, set(names))


def test_no_filter_is_every_machine_the_member_may_see(client, samples):
    got = _walk(client, limit=3)
    theirs = str(samples["machines"]["theirs"][0])
    assert theirs not in {s["machine_id"] for s in got}
    assert [s["id"] for s in got] == _expected(samples, {"a", "b", "c"})


def test_needs_review_is_fresh_work_for_this_viewer(client, db, samples):
    a, _ = samples["machines"]["a"]
    first = _walk(client, limit=50, machine_id=[str(a)], needs_review="true")
    # Samples already at consensus (review_count 3) are not offered.
    assert all(s["review_count"] < 3 for s in first)
    db.add(SampleReview(sample_id=UUID(first[0]["id"]), reviewer_id=samples["me"].id, decision="accept"))
    db.commit()
    again = _walk(client, limit=50, machine_id=[str(a)], needs_review="true")
    assert [s["id"] for s in again] == [s["id"] for s in first[1:]]


def test_batch_archive_counts_only_the_chosen_machines(client, db, samples):
    me = samples["me"]
    me.role = "admin"
    db.commit()
    a, c = samples["machines"]["a"][0], samples["machines"]["c"][0]
    shown = _walk(client, limit=50, machine_id=[str(a), str(c)])
    resp = client.post(
        "/api/samples/batch-archive",
        json={"machine_ids": [str(a), str(c)], "dry_run": True, "exposure": "normal"},
        headers=_auth_headers(client),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["matched"] == len(shown)


def test_overview_and_filter_options_sum_the_worker_counts(client, db, samples):
    refresh_stats()
    a, c = samples["machines"]["a"][0], samples["machines"]["c"][0]
    all_mine = client.get("/api/stats/overview").json()
    assert all_mine["total_samples"] == 16  # a, b and c; not the other member's
    assert all_mine["total_machines"] == 3
    two = client.get("/api/stats/overview", params={"machine_id": [str(a), str(c)]}).json()
    assert two["total_samples"] == 6 + 5
    assert two["accepted_samples"] == sum(
        1 for i, (name, _, _) in enumerate(samples["order"]) if name in {"a", "c"} and i % 7 == 0
    )
    options = client.get("/api/samples/filter-options").json()
    assert sum(options["source_role_counts"].values()) == 16
    assert options["capture_reasons"] == ["live"]


def test_a_bad_cursor_is_a_400(client, samples):
    resp = client.get("/api/samples", params={"cursor": "nope"}, headers=_auth_headers(client))
    assert resp.status_code == 400


def test_list_items_carry_a_thumbnail_url_when_storage_signs_them(client, samples, monkeypatch):
    from app.services import review_queue

    class _Signing:
        def presigned_get_url(self, key):
            return f"https://store.example/{key}"

    monkeypatch.setattr(review_queue, "get_backend", lambda: _Signing())
    item = _walk(client, limit=1)[0]
    assert item["thumb_url"].startswith("https://store.example/")


def test_batch_delete_dry_run_counts_only_the_chosen_machines(client, samples):
    a = samples["machines"]["a"][0]
    shown = _walk(client, limit=50, machine_id=[str(a)])
    resp = client.post(
        "/api/samples/batch-delete",
        json={"machine_ids": [str(a)], "dry_run": True, "exposure": "normal"},
        headers=_auth_headers(client),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["matched"] == len(shown)


def test_a_teacher_job_filter_is_the_samples_filter(client, db, samples):
    from app.routers.teacher import TeacherJobFilter
    from app.services.sample_filters import apply_sample_filters

    a, c = samples["machines"]["a"][0], samples["machines"]["c"][0]
    filt = TeacherJobFilter(machine_ids=[a, c], exposure="normal")
    picked = apply_sample_filters(db.query(Sample), filt, samples["me"].id).all()
    assert {s.machine_id for s in picked} == {a, c}
    assert len(picked) == len(_walk(client, limit=50, machine_id=[str(a), str(c)]))
