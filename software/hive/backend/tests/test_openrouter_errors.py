import io
import json
from urllib.error import HTTPError

import pytest

from app.errors import APIError
from app.services import openrouter


def _httpError(status: int, message: str | None) -> HTTPError:
    body = json.dumps({"error": {"message": message}}).encode() if message else b"not json"
    return HTTPError("https://openrouter.ai/api/v1/chat/completions", status, "err", {}, io.BytesIO(body))


@pytest.mark.parametrize(
    "upstream_status, expected_status, expected_code",
    [
        (402, 402, "OPENROUTER_NO_CREDITS"),
        (401, 400, "OPENROUTER_KEY_REJECTED"),
        (403, 400, "OPENROUTER_KEY_REJECTED"),
        (429, 429, "OPENROUTER_RATE_LIMITED"),
        (500, 502, "OPENROUTER_HTTP_ERROR"),
        (503, 502, "OPENROUTER_HTTP_ERROR"),
    ],
)
def test_account_problems_are_the_users_not_a_gateway_failure(monkeypatch, upstream_status, expected_status, expected_code):
    def fake_urlopen(request, timeout):
        raise _httpError(upstream_status, "Insufficient credits. This account never purchased credits.")

    monkeypatch.setattr(openrouter, "urlopen", fake_urlopen)
    with pytest.raises(APIError) as excinfo:
        openrouter.run_openrouter_chat(api_key="k", model="m", messages=[{"role": "user", "content": "hi"}])
    assert excinfo.value.status_code == expected_status
    assert excinfo.value.error_code == expected_code
    assert "Insufficient credits" in excinfo.value.error_message


def test_no_credits_message_tells_the_user_what_to_do(monkeypatch):
    monkeypatch.setattr(openrouter, "urlopen", lambda request, timeout: (_ for _ in ()).throw(_httpError(402, None)))
    with pytest.raises(APIError) as excinfo:
        openrouter.run_openrouter_chat(api_key="k", model="m", messages=[])
    assert excinfo.value.error_message.startswith("Your OpenRouter account has no credits.")
    assert "Settings" in excinfo.value.error_message
