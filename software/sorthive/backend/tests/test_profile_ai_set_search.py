from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.errors import APIError
from app.services import set_inventory
from app.services.openrouter import OpenRouterResponse
from app.services import profile_ai
from app.services.profile_ai import _finalize_ai_response, apply_profile_ai_proposal


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict:
        return self._payload


def test_search_sets_extracts_year_and_matches_theme_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    set_inventory._theme_records_cache = None
    set_inventory._theme_match_cache.clear()
    set_inventory._theme_children_cache.clear()

    def fake_get(url: str, params: dict | None = None, timeout: int = 15) -> _FakeResponse:
        assert params is not None
        if url.endswith("/themes/"):
            return _FakeResponse(
                {
                    "results": [
                        {"id": 101, "name": "Creator 3-in-1", "parent_id": None},
                        {"id": 102, "name": "Creator Expert", "parent_id": None},
                    ],
                    "next": None,
                }
            )

        if url.endswith("/sets/") and params.get("theme_id") == 101:
            assert params.get("min_year") == 2024
            assert params.get("max_year") == 2024
            return _FakeResponse(
                {
                    "results": [
                        {
                            "set_num": "31156-1",
                            "name": "Exotic Parrot",
                            "year": 2024,
                            "num_parts": 253,
                            "set_img_url": "https://img.example/parrot.png",
                            "theme_id": 101,
                        }
                    ],
                    "next": None,
                }
            )

        if url.endswith("/sets/") and params.get("theme_id") == 102:
            assert params.get("min_year") == 2024
            assert params.get("max_year") == 2024
            return _FakeResponse({"results": [], "next": None})

        raise AssertionError(f"Unexpected request: {url} {params}")

    monkeypatch.setattr(set_inventory.requests, "get", fake_get)

    results = set_inventory.search_sets("rb-key", "Creator 2024")

    assert [lego_set["set_num"] for lego_set in results] == ["31156-1"]
    assert results[0]["name"] == "Exotic Parrot"
    assert results[0]["year"] == 2024


def test_finalize_ai_response_replaces_hallucinated_summary_when_set_searches_are_empty() -> None:
    response = OpenRouterResponse(
        content=json.dumps(
            {
                "summary": "Creator 3-in-1: 31136, 31137, 31138",
                "proposals": [],
            }
        ),
        model="test-model",
        usage=None,
    )

    content, proposal = _finalize_ai_response(
        response=response,
        set_search_observations=[
            {
                "input": {"query": "Creator", "min_year": 2024, "max_year": 2024},
                "sets": [],
            }
        ],
        part_search_observations=[],
    )

    assert proposal is None
    assert "I couldn't find matching LEGO sets in the catalog for:" in content
    assert '- "Creator" from 2024' in content
    assert "31136" not in content


def test_finalize_ai_response_rewrites_create_set_metadata_from_search_results() -> None:
    response = OpenRouterResponse(
        content=json.dumps(
            {
                "summary": "Added Exotic Parrot",
                "proposals": [
                    {
                        "action": "create_set",
                        "set_num": "31156-1",
                        "name": "Wrong Name",
                        "set_meta": {
                            "name": "Wrong Name",
                            "year": 1990,
                            "num_parts": 1,
                            "img_url": None,
                        },
                    }
                ],
            }
        ),
        model="test-model",
        usage=None,
    )

    content, proposal = _finalize_ai_response(
        response=response,
        set_search_observations=[
            {
                "input": {"query": "Creator 3-in-1", "min_year": 2024, "max_year": 2024},
                "sets": [
                    {
                        "set_num": "31156-1",
                        "name": "Exotic Parrot",
                        "year": 2024,
                        "num_parts": 253,
                        "img_url": "https://img.example/parrot.png",
                    }
                ],
            }
        ],
        part_search_observations=[],
    )

    assert content == "Added Exotic Parrot"
    assert proposal is not None
    assert proposal["proposals"][0]["name"] == "Exotic Parrot"
    assert proposal["proposals"][0]["set_meta"] == {
        "name": "Exotic Parrot",
        "year": 2024,
        "num_parts": 253,
        "img_url": "https://img.example/parrot.png",
    }


def test_finalize_ai_response_rejects_create_set_not_seen_in_search_results() -> None:
    response = OpenRouterResponse(
        content=json.dumps(
            {
                "summary": "Added a set",
                "proposals": [{"action": "create_set", "set_num": "99999-1"}],
            }
        ),
        model="test-model",
        usage=None,
    )

    with pytest.raises(APIError, match="not returned by search_sets"):
        _finalize_ai_response(
            response=response,
            set_search_observations=[
                {
                    "input": {"query": "Creator", "min_year": 2024, "max_year": 2024},
                    "sets": [],
                }
            ],
            part_search_observations=[],
        )


def test_finalize_ai_response_rewrites_create_custom_set_from_search_results() -> None:
    response = OpenRouterResponse(
        content=json.dumps(
            {
                "summary": "Added a custom order",
                "proposals": [
                    {
                        "action": "create_custom_set",
                        "name": "Customer Order",
                        "custom_parts": [
                            {"part_num": "2780", "quantity": 20},
                            {"part_num": "32054", "color_id": 5, "quantity": 10},
                        ],
                    }
                ],
            }
        ),
        model="test-model",
        usage=None,
    )

    content, proposal = _finalize_ai_response(
        response=response,
        set_search_observations=[],
        part_search_observations=[
            {
                "input": {"query": "technic pin"},
                "parts": [
                    {
                        "part_num": "2780",
                        "name": "Pin with Friction Ridges Lengthwise",
                        "img_url": "https://img.example/2780.png",
                    },
                    {
                        "part_num": "32054",
                        "name": "Axle 2 Notched",
                        "img_url": "https://img.example/32054.png",
                    },
                ],
            }
        ],
    )

    assert content == "Added a custom order"
    assert proposal is not None
    item = proposal["proposals"][0]
    assert item["set_meta"] == {
        "name": "Customer Order",
        "year": None,
        "num_parts": 30,
        "img_url": None,
    }
    assert item["custom_parts"][0] == {
        "part_num": "2780",
        "part_name": "Pin with Friction Ridges Lengthwise",
        "img_url": "https://img.example/2780.png",
        "color_id": -1,
        "color_name": "Any color",
        "quantity": 20,
    }
    assert item["custom_parts"][1]["part_name"] == "Axle 2 Notched"
    assert item["custom_parts"][1]["color_id"] == 5


def test_finalize_ai_response_rejects_create_custom_set_part_not_seen_in_search_results() -> None:
    response = OpenRouterResponse(
        content=json.dumps(
            {
                "summary": "Added a custom order",
                "proposals": [
                    {
                        "action": "create_custom_set",
                        "name": "Customer Order",
                        "custom_parts": [{"part_num": "99999", "quantity": 2}],
                    }
                ],
            }
        ),
        model="test-model",
        usage=None,
    )

    with pytest.raises(APIError, match="not returned by search_parts"):
        _finalize_ai_response(
            response=response,
            set_search_observations=[],
            part_search_observations=[
                {
                    "input": {"query": "pin"},
                    "parts": [{"part_num": "2780", "name": "Pin"}],
                }
            ],
        )


def test_apply_profile_ai_proposal_creates_custom_set_rule() -> None:
    rules = apply_profile_ai_proposal(
        rules=[],
        selected_rule_id=None,
        proposal={
            "summary": "Added custom set",
            "proposals": [
                {
                    "action": "create_custom_set",
                    "name": "Customer Order",
                    "custom_parts": [
                        {
                            "part_num": "2780",
                            "part_name": "Pin",
                            "color_id": -1,
                            "color_name": "Any color",
                            "quantity": 20,
                        }
                    ],
                    "set_meta": {"name": "Customer Order", "year": None, "num_parts": 20, "img_url": None},
                }
            ],
        },
    )

    assert len(rules) == 1
    rule = rules[0]
    assert rule["rule_type"] == "set"
    assert rule["set_source"] == "custom"
    assert rule["set_num"].startswith("custom:")
    assert rule["custom_parts"][0]["part_num"] == "2780"


def test_generate_profile_ai_proposal_short_circuits_custom_set_without_parts_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(profile_ai, "run_openrouter_chat", lambda **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    user = SimpleNamespace(preferred_ai_model=None, openrouter_api_key_encrypted=None)
    catalog = SimpleNamespace(
        parts_data=SimpleNamespace(
            parts={},
            categories={},
            colors={},
            bricklink_categories={},
        )
    )

    result = profile_ai.generate_profile_ai_proposal(
        user=user,
        catalog=catalog,
        document={"rules": []},
        message="Let's create a few custom kits. They're not real LEGO sets.",
    )

    assert result.proposal is None
    assert "parts catalog" in result.content
    assert "Custom Set manually" in result.content
