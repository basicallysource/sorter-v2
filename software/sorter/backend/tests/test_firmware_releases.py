"""The Control Board page's firmware release list, against a fake GitHub.

Firmware shares its repo's releases with Hive and SorterOS, which release far
more often, so the firmware can sit many pages down the list."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from server import shared_state
from server.routers import firmware


def _release(tag: str, assets: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "tag_name": tag,
        "name": tag,
        "published_at": "2026-08-09T04:31:51Z",
        "prerelease": False,
        "body": "",
        "assets": [{"name": a, "size": 1024, "browser_download_url": f"https://example.test/{a}"} for a in assets],
    }


class _GitHub:
    """Hands out `releases`, newest first, a page at a time, like the API."""

    def __init__(self, releases: list[dict[str, Any]]):
        self.releases = releases
        self.pages: list[int] = []

    def get(self, url, params=None, headers=None, timeout=None):
        page, per_page = params["page"], params["per_page"]
        self.pages.append(page)
        batch = self.releases[(page - 1) * per_page : page * per_page]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: batch)


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch):
    def install(releases: list[dict[str, Any]]) -> _GitHub:
        fake = _GitHub(releases)
        monkeypatch.setattr(firmware.requests, "get", fake.get)
        return fake

    monkeypatch.setattr(shared_state, "gc_ref", SimpleNamespace(logger=logging.getLogger("test")))
    monkeypatch.setattr(firmware, "_releases_cache", {"ts": 0.0, "data": None})
    return install


def test_finds_firmware_behind_a_page_of_other_releases(github):
    fake = github(
        [_release(f"hive/v0.1.{n}") for n in range(150, 0, -1)]
        + [_release("firmware/v0.8.0", ("feeder-skr-v0.8.0.uf2", "distribution-skr-v0.8.0.uf2"))]
    )
    payload = firmware.get_firmware_releases(refresh=True)
    assert [r["tag"] for r in payload["releases"]] == ["firmware/v0.8.0"]
    assert [a["role"] for a in payload["releases"][0]["assets"]] == ["feeder", "distribution"]
    assert fake.pages == [1, 2]


def test_one_short_page_is_the_whole_list(github):
    fake = github([_release("sorteros/v4.1.0"), _release("firmware/v0.8.0", ("feeder-skr-v0.8.0.uf2",))])
    assert [r["tag"] for r in firmware.get_firmware_releases(refresh=True)["releases"]] == ["firmware/v0.8.0"]
    assert fake.pages == [1]
