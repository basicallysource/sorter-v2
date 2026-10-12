"""The parts sync pages Rebrickable's parts list from the number of parts it
already has. Rebrickable answers 404 for a page past the last one, which is the
end of the list: the sync finishes and records when, so the hourly check stops
planning it. A 404 on the first page, or any other error, is still a failure."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import profile_catalog
from app.services.profile_engine import db as profile_db
from app.services.profile_engine import parts_cache

PAGE_SIZE = 2


class _Response:
    def __init__(self, status: int, url: str, body: dict | None = None) -> None:
        self.status_code = status
        self.ok = status < 400
        self.reason = {200: "OK", 403: "Forbidden", 404: "Not Found"}.get(status, "")
        self.url = url
        self.headers: dict[str, str] = {}
        self._body = body

    def json(self) -> dict | None:
        return self._body


class FakeRebrickable:
    """GET /parts/ over ``parts``, PAGE_SIZE to a page, 404 past the last page;
    ``fail`` = (page, status) answers that page with that status instead."""

    def __init__(self, parts: list[str], fail: tuple[int, int] | None = None) -> None:
        self.parts = [{"part_num": p, "name": f"Part {p}"} for p in parts]
        self.fail = fail
        self.pages_asked: list[int] = []

    def get(self, url, params=None, headers=None, timeout=None):
        page = int(params["page"])
        self.pages_asked.append(page)
        last = max(1, -(-len(self.parts) // PAGE_SIZE))
        if self.fail and self.fail[0] == page:
            return _Response(self.fail[1], url)
        if page > last:
            return _Response(404, url)
        results = self.parts[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        return _Response(200, url, {"count": len(self.parts), "next": None if page == last else "more", "results": results})


@pytest.fixture()
def catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SORTING_PROFILE_PARTS_DB_PATH", str(tmp_path / "parts.db"))
    monkeypatch.setattr(settings, "REBRICKABLE_API_KEY", "test-key")
    monkeypatch.setattr(settings, "PROFILE_CATALOG_AUTO_SYNC_ENABLED", True)
    monkeypatch.setattr(parts_cache, "REBRICKABLE_PAGE_SIZE", PAGE_SIZE)
    monkeypatch.setattr(parts_cache, "THROTTLE_SECONDS", 0)
    return profile_catalog.ProfileCatalogService(runs_syncs=True)


def _with_parts(service, parts: list[str]):
    profile_db.upsertParts(service._conn, [{"part_num": p, "name": f"Part {p}"} for p in parts])
    profile_db.reloadPartsData(service._conn, service.parts_data)
    return service


def _sync(service, monkeypatch, rebrickable: FakeRebrickable) -> bool:
    monkeypatch.setattr(parts_cache.requests, "get", rebrickable.get)
    assert service.start_sync("parts")
    return service.wait_for_sync(poll_s=0.01)


def test_a_404_past_the_last_page_is_the_end_of_the_list(catalog, monkeypatch):
    # Five parts here, four at Rebrickable (one merged there since): the page
    # after this catalog's count is past Rebrickable's last.
    service = _with_parts(catalog, ["p1", "p2", "p3", "p4", "p5"])
    rebrickable = FakeRebrickable(["p1", "p2", "p3", "p4"])
    assert _sync(service, monkeypatch, rebrickable) is True
    assert rebrickable.pages_asked == [3]
    assert profile_db.getCatalogSyncState(service._conn, "parts")["status"] == "completed"
    assert service.get_last_synced_at("parts") is not None
    assert "parts" not in service.get_auto_sync_plan()


def test_a_catalog_behind_still_fetches_every_page_it_lacks(catalog, monkeypatch):
    service = _with_parts(catalog, ["p1", "p2"])
    rebrickable = FakeRebrickable(["p1", "p2", "p3", "p4", "p5"])
    assert _sync(service, monkeypatch, rebrickable) is True
    assert rebrickable.pages_asked == [2, 3]
    assert len(service.parts_data.parts) == 5
    assert service.get_last_synced_at("parts") is not None


@pytest.mark.parametrize(
    ("have", "fail"),
    [
        ([], (1, 404)),  # the first page missing is a real failure
        (["p1", "p2", "p3", "p4", "p5"], (3, 403)),  # and so is any other error
    ],
)
def test_other_errors_still_fail_the_sync(catalog, monkeypatch, have, fail):
    service = _with_parts(catalog, have)
    rebrickable = FakeRebrickable(["p1", "p2", "p3", "p4"], fail=fail)
    assert _sync(service, monkeypatch, rebrickable) is False
    assert profile_db.getCatalogSyncState(service._conn, "parts")["status"] == "error"
    assert service.get_last_synced_at("parts") is None
    assert "parts" in service.get_auto_sync_plan()
