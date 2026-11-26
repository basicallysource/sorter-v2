"""A profile saved on the machine can be read before it is activated: its
description, its bins and how it names them."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routers import sorting_profiles


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(sorting_profiles, "_local_profiles_dir", lambda: tmp_path)
    app = FastAPI()
    app.include_router(sorting_profiles.router)
    return TestClient(app)


def test_the_description_bins_and_naming_of_a_saved_profile_are_returned(client, tmp_path):
    artifact = {
        "name": "One bin per color",
        "description": "Sort by color.",
        "default_category_id": "misc",
        "fallback_mode": {"by_color": True},
        "categories": {"misc": {"name": "Misc"}},
        "category_order": ["misc"],
        "rules": [],
        "stats": {"total_parts": 10, "sorted": 10, "samples": ["x"]},
        "requires": ["bin_sort_by"],
        "bin_sort_by": ["color"],
        "program": {"format": 1, "rules": []},
    }
    (tmp_path / "color.json").write_text(json.dumps(artifact))

    body = client.get("/api/sorting-profiles/local/color.json/metadata").json()

    assert body["name"] == "One bin per color"
    assert body["description"] == "Sort by color."
    assert body["fallback_mode"] == {"by_color": True}
    assert body["category_order"] == ["misc"]
    assert body["bin_sort_by"] == ["color"]
    assert body["stats"] == {"total_parts": 10, "sorted": 10}
    assert "program" not in body


def test_a_profile_without_name_or_description_falls_back_to_its_file_name(client, tmp_path):
    (tmp_path / "plain.json").write_text(json.dumps({}))

    body = client.get("/api/sorting-profiles/local/plain.json/metadata").json()

    assert body["name"] == "plain"
    assert body["description"] == ""
    assert body["default_category_id"] == "misc"
    assert body["bin_sort_by"] == []


def test_a_missing_profile_is_404(client):
    assert client.get("/api/sorting-profiles/local/nope.json/metadata").status_code == 404


def test_a_file_that_is_not_a_profile_is_422(client, tmp_path):
    (tmp_path / "broken.json").write_text("[1, 2]")

    assert client.get("/api/sorting-profiles/local/broken.json/metadata").status_code == 422
