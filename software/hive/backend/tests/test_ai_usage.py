from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.ai_usage_event import AiUsageEvent
from app.routers import profiles as profiles_router


def _create_profile(client: TestClient, auth_headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/profiles",
        json={"name": "Usage Profile", "visibility": "private"},
        headers=auth_headers,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


class TestAiUsageLogging:
    def test_chat_message_records_usage_event(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, monkeypatch: object
    ) -> None:
        profile = _create_profile(client, auth_headers)
        profile_id = profile["id"]
        version_id = profile["current_version"]["id"]

        def fake_generate(**_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                content="Sure.",
                model="anthropic/claude-sonnet-4.6",
                usage={
                    "prompt_tokens": 1200,
                    "completion_tokens": 300,
                    "total_tokens": 1500,
                    "cost": 0.0042,
                    "prompt_tokens_details": {"cached_tokens": 800},
                },
                tool_trace=[],
                proposal=None,
                performance={"round_count": 2, "generation_ids": ["gen-1", "gen-2"]},
            )

        monkeypatch.setattr(profiles_router, "generate_profile_ai_proposal", fake_generate)

        response = client.post(
            f"/api/profiles/{profile_id}/ai/messages",
            json={"message": "Add a Technic category.", "version_id": version_id},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text

        event = db.query(AiUsageEvent).one()
        assert event.purpose == "profile_chat"
        assert str(event.profile_id) == profile_id
        assert event.message_id is not None
        assert event.model == "anthropic/claude-sonnet-4.6"
        assert event.cost_usd == 0.0042
        assert event.prompt_tokens == 1200
        assert event.completion_tokens == 300
        assert event.total_tokens == 1500
        assert event.cached_tokens == 800
        assert event.call_count == 2
        assert event.generation_ids == ["gen-1", "gen-2"]

    def test_usage_summary_totals(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: object
    ) -> None:
        profile = _create_profile(client, auth_headers)
        version_id = profile["current_version"]["id"]

        def fake_generate(**_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                content="Sure.",
                model="anthropic/claude-sonnet-4.6",
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.25},
                tool_trace=[],
                proposal=None,
                performance={"round_count": 1},
            )

        monkeypatch.setattr(profiles_router, "generate_profile_ai_proposal", fake_generate)

        for _ in range(2):
            response = client.post(
                f"/api/profiles/{profile['id']}/ai/messages",
                json={"message": "Again.", "version_id": version_id},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text

        summary = client.get("/api/ai/usage", headers=auth_headers)
        assert summary.status_code == 200, summary.text
        body = summary.json()

        for period in ("week", "month", "year", "all_time"):
            assert body[period]["cost_usd"] == 0.5
            assert body[period]["total_tokens"] == 30
            assert body[period]["message_count"] == 2
        assert body["since"] is not None

    def test_usage_summary_is_empty_for_a_user_with_no_calls(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        body = client.get("/api/ai/usage", headers=auth_headers).json()
        assert body["all_time"]["cost_usd"] == 0.0
        assert body["all_time"]["message_count"] == 0
        assert body["since"] is None
