from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.errors import APIError
from app.config import settings
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


def test_finalize_ai_response_accepts_exact_catalog_part_for_custom_set() -> None:
    response = OpenRouterResponse(
        content=json.dumps(
            {
                "summary": "Added a custom order",
                "proposals": [
                    {
                        "action": "create_custom_set",
                        "name": "Customer Order",
                        "custom_parts": [{"part_num": "3001", "quantity": 2}],
                    }
                ],
            }
        ),
        model="test-model",
        usage=None,
    )

    catalog = SimpleNamespace(
        parts_data=SimpleNamespace(
            parts={
                "3001": {
                    "name": "Brick 2 x 4",
                    "part_img_url": "https://img.example/3001.png",
                }
            }
        )
    )

    content, proposal = _finalize_ai_response(
        response=response,
        set_search_observations=[],
        part_search_observations=[
            {
                "input": {"query": "brick 2x4"},
                "parts": [{"part_num": "3002", "name": "Brick 2 x 3"}],
            }
        ],
        catalog=catalog,
    )

    assert content == "Added a custom order"
    assert proposal is not None
    item = proposal["proposals"][0]
    assert item["custom_parts"][0] == {
        "part_num": "3001",
        "part_name": "Brick 2 x 4",
        "img_url": "https://img.example/3001.png",
        "color_id": -1,
        "color_name": "Any color",
        "quantity": 2,
    }


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


def test_apply_profile_ai_proposal_skips_duplicate_create_set() -> None:
    existing_rules = [
        {
            "id": "rule-1",
            "rule_type": "set",
            "set_source": "rebrickable",
            "name": "NASA Mars Rover Perseverance",
            "set_num": "30682-1",
            "include_spares": False,
            "set_meta": {"name": "NASA Mars Rover Perseverance", "year": 2024, "num_parts": 83, "img_url": None},
            "match_mode": "all",
            "conditions": [],
            "children": [],
            "disabled": False,
        }
    ]

    rules = apply_profile_ai_proposal(
        rules=existing_rules,
        selected_rule_id=None,
        proposal={
            "summary": "Added the set again",
            "proposals": [
                {
                    "action": "create_set",
                    "set_num": "30682-1",
                    "name": "NASA Mars Rover Perseverance",
                    "set_meta": {"name": "NASA Mars Rover Perseverance", "year": 2024, "num_parts": 83, "img_url": None},
                }
            ],
        },
    )

    assert len(rules) == 1
    assert rules[0]["set_num"] == "30682-1"


def test_apply_profile_ai_proposal_skips_duplicate_filter_rule() -> None:
    existing_rules = [
        {
            "id": "rule-1",
            "name": "Technic Pins",
            "match_mode": "all",
            "conditions": [
                {"id": "cond-1", "field": "name", "op": "contains", "value": "technic pin"},
            ],
            "children": [],
            "disabled": False,
        }
    ]

    rules = apply_profile_ai_proposal(
        rules=existing_rules,
        selected_rule_id=None,
        proposal={
            "summary": "Added it again",
            "proposals": [
                {
                    "action": "create",
                    "name": "Technic Pins",
                    "match_mode": "all",
                    "conditions": [
                        {"field": "name", "op": "contains", "value": "technic pin"},
                    ],
                }
            ],
        },
    )

    assert len(rules) == 1
    assert rules[0]["name"] == "Technic Pins"


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


def test_tool_get_set_inventory_pages_inventory_and_excludes_spares_by_default() -> None:
    catalog = SimpleNamespace(
        get_set_inventory=lambda set_num: {
            "set": {
                "set_num": set_num,
                "name": "Lion Knights' Castle",
                "year": 2022,
                "num_parts": 4514,
                "img_url": "https://img.example/10305.png",
            },
            "inventory": [
                {
                    "part_num": "3001",
                    "part_name": "Brick 2 x 4",
                    "color_id": 1,
                    "color_name": "Blue",
                    "quantity": 4,
                    "is_spare": False,
                    "part_img_url": "https://img.example/3001.png",
                },
                {
                    "part_num": "3002",
                    "part_name": "Brick 2 x 3",
                    "color_id": 5,
                    "color_name": "Red",
                    "quantity": 2,
                    "is_spare": True,
                    "part_img_url": "https://img.example/3002.png",
                },
                {
                    "part_num": "3003",
                    "part_name": "Brick 2 x 2",
                    "color_id": 3,
                    "color_name": "Green",
                    "quantity": 6,
                    "is_spare": False,
                    "part_img_url": "https://img.example/3003.png",
                },
            ],
        }
    )

    result = profile_ai._tool_get_set_inventory(
        catalog,
        {"set_num": "10305-1", "limit": 1, "offset": 1},
    )
    model_payload = json.loads(result.content)
    trace_payload = result.trace_output

    assert model_payload["set"] == {
        "set_num": "10305-1",
        "name": "Lion Knights' Castle",
        "year": 2022,
        "num_parts": 4514,
        "img_url": "https://img.example/10305.png",
    }
    assert model_payload["total"] == 2
    assert model_payload["showing"] == 1
    assert model_payload["inventory"] == [
        {
            "part_num": "3003",
            "part_name": "Brick 2 x 2",
            "color_id": 3,
            "color_name": "Green",
            "quantity": 6,
            "is_spare": False,
        }
    ]
    assert trace_payload is not None
    assert trace_payload["set"]["set_num"] == "10305-1"
    assert trace_payload["total"] == 2
    assert trace_payload["showing"] == 1
    assert trace_payload["include_spares"] is False
    assert trace_payload["inventory"] == [
        {
            "part_num": "3003",
            "part_name": "Brick 2 x 2",
            "color_id": 3,
            "color_name": "Green",
            "quantity": 6,
            "is_spare": False,
        }
    ]


def test_summarize_tool_result_formats_set_inventory() -> None:
    summary = profile_ai._summarize_tool_result(
        "get_set_inventory",
        {"set_num": "10305-1"},
        json.dumps(
            {
                "set": {"set_num": "10305-1", "name": "Lion Knights' Castle"},
                "total": 2,
                "inventory": [
                    {
                        "part_num": "3001",
                        "part_name": "Brick 2 x 4",
                        "color_name": "Blue",
                        "quantity": 4,
                        "is_spare": False,
                    },
                    {
                        "part_num": "3002",
                        "part_name": "Brick 2 x 3",
                        "color_name": "Red",
                        "quantity": 1,
                        "is_spare": True,
                    },
                ],
            }
        ),
    )

    assert 'Found 2 inventory entries in "Lion Knights\' Castle" (10305-1):' in summary
    assert "- Brick 2 x 4 (3001) · Blue · qty 4" in summary
    assert "- Brick 2 x 3 (3002) · Red · qty 1 · spare" in summary


def test_generate_profile_ai_proposal_exposes_set_inventory_tool_without_parts_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_tool_names: list[str] = []

    def fake_chat(**kwargs):
        observed_tool_names.extend(tool["function"]["name"] for tool in kwargs.get("tools", []))
        return OpenRouterResponse(
            content=json.dumps({"summary": "Looked it up", "proposals": []}),
            model="test-model",
            usage=None,
        )

    monkeypatch.setattr(profile_ai, "run_openrouter_chat", fake_chat)
    monkeypatch.setattr(profile_ai, "get_user_openrouter_key", lambda user: "or-key")

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
        message="What parts are in Lion Knights' Castle?",
    )

    assert result.content == "Looked it up"
    assert observed_tool_names == ["search_sets", "get_set_inventory"]


def test_generate_profile_ai_proposal_reports_performance_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(profile_ai, "run_openrouter_chat", lambda **kwargs: OpenRouterResponse(
        content=json.dumps({"summary": "Done", "proposals": []}),
        model="test-model",
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {
                "cached_tokens": 8,
                "cache_write_tokens": 2,
            },
        },
    ))
    monkeypatch.setattr(profile_ai, "get_user_openrouter_key", lambda user: "or-key")

    user = SimpleNamespace(preferred_ai_model=None, openrouter_api_key_encrypted=None)
    catalog = SimpleNamespace(
        parts_data=SimpleNamespace(
            parts={"3001": {"name": "Brick 2 x 4"}},
            categories={},
            colors={},
            bricklink_categories={},
        )
    )

    result = profile_ai.generate_profile_ai_proposal(
        user=user,
        catalog=catalog,
        document={"rules": []},
        message="Add a simple rule",
        ai_request_id="req-test-1",
    )

    assert result.content == "Done"
    assert result.performance is not None
    assert result.performance["request_id"] == "req-test-1"
    assert result.performance["round_count"] == 1
    assert result.performance["tool_call_count"] == 0
    assert result.performance["cached_tokens"] == 8
    assert result.performance["cache_write_tokens"] == 2
    assert isinstance(result.performance["llm_ms"], float)
    assert isinstance(result.performance["total_ms"], float)


def test_generate_profile_ai_proposal_enables_prompt_cache_for_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_kwargs: dict[str, object] = {}

    def fake_chat(**kwargs):
        observed_kwargs.update(kwargs)
        return OpenRouterResponse(
            content=json.dumps({"summary": "Done", "proposals": []}),
            model="test-model",
            usage=None,
        )

    monkeypatch.setattr(profile_ai, "run_openrouter_chat", fake_chat)
    monkeypatch.setattr(profile_ai, "get_user_openrouter_key", lambda user: "or-key")

    user = SimpleNamespace(preferred_ai_model=None, openrouter_api_key_encrypted=None)
    catalog = SimpleNamespace(
        parts_data=SimpleNamespace(
            parts={"3001": {"name": "Brick 2 x 4"}},
            categories={},
            colors={},
            bricklink_categories={},
        )
    )

    profile_ai.generate_profile_ai_proposal(
        user=user,
        catalog=catalog,
        document={"rules": []},
        message="Add a simple rule",
    )

    assert observed_kwargs["max_tokens"] == 8192
    assert observed_kwargs["cache_control"] == {"type": "ephemeral"}


def test_generate_profile_ai_proposal_does_not_enable_prompt_cache_for_non_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_kwargs: dict[str, object] = {}

    def fake_chat(**kwargs):
        observed_kwargs.update(kwargs)
        return OpenRouterResponse(
            content=json.dumps({"summary": "Done", "proposals": []}),
            model="test-model",
            usage=None,
        )

    monkeypatch.setattr(profile_ai, "run_openrouter_chat", fake_chat)
    monkeypatch.setattr(profile_ai, "get_user_openrouter_key", lambda user: "or-key")

    user = SimpleNamespace(preferred_ai_model="openai/gpt-5-mini", openrouter_api_key_encrypted=None)
    catalog = SimpleNamespace(
        parts_data=SimpleNamespace(
            parts={"3001": {"name": "Brick 2 x 4"}},
            categories={},
            colors={},
            bricklink_categories={},
        )
    )

    profile_ai.generate_profile_ai_proposal(
        user=user,
        catalog=catalog,
        document={"rules": []},
        message="Add a simple rule",
    )

    assert observed_kwargs["cache_control"] is None


def test_build_system_prompt_uses_compact_rule_snapshot_for_current_rules() -> None:
    catalog = SimpleNamespace(
        parts_data=SimpleNamespace(
            parts={"3001": {"name": "Brick 2 x 4"}},
            categories={},
            colors={1: {"name": "Blue"}},
            bricklink_categories={},
        )
    )
    document = {
        "rules": [
            {
                "id": "set-1",
                "rule_type": "set",
                "set_source": "custom",
                "name": "Custom Bundle",
                "set_num": "custom:set-1",
                "custom_parts": [
                    {"part_num": "3001", "part_name": "Brick 2 x 4", "color_id": 1, "color_name": "Blue", "quantity": 4},
                    {"part_num": "3002", "part_name": "Brick 2 x 3", "color_id": -1, "color_name": "Any color", "quantity": 2},
                ],
                "conditions": [],
                "children": [],
            },
            {
                "id": "rule-1",
                "name": "Technic Pins",
                "match_mode": "all",
                "conditions": [
                    {"id": "cond-1", "field": "name", "op": "contains", "value": "technic pin"},
                ],
                "children": [],
            },
        ]
    }

    prompt = profile_ai._build_system_prompt(catalog, document, None)

    assert '"custom_parts_summary"' in prompt
    assert '"sample_parts"' in prompt
    assert '"line_items": 2' in prompt
    assert '"id": "cond-1"' not in prompt
