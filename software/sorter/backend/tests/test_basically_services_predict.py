"""A colour prediction goes over one kept-open connection. When the other end
has already closed it, the request is sent once more on a fresh connection;
a timeout is not retried."""

from __future__ import annotations

from http.client import RemoteDisconnected
from types import SimpleNamespace
from unittest.mock import patch

import requests

import basically_services

_GC = SimpleNamespace(logger=SimpleNamespace(warn=lambda *_: None))
_ANSWER = {"color_id": 1, "color_name": "White", "confidence": 0.9}


def _response() -> SimpleNamespace:
    return SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: _ANSWER)


def _predict(side_effect) -> tuple[object, int]:
    with patch.object(basically_services, "_deviceState", return_value={"token": "t"}), patch.object(
        basically_services._session, "post", side_effect=side_effect
    ) as post:
        result = basically_services.predictColor(_GC, [b"\xff\xd8jpeg"], [4])
    return result, post.call_count


def test_a_connection_closed_at_the_other_end_is_sent_again() -> None:
    dropped = requests.exceptions.ConnectionError(
        ("Connection aborted.", RemoteDisconnected("Remote end closed connection without response"))
    )
    result, calls = _predict([dropped, _response()])
    assert result == _ANSWER
    assert calls == 2


def test_a_timeout_is_not_sent_again() -> None:
    result, calls = _predict([requests.exceptions.ConnectTimeout("slow"), _response()])
    assert result is None
    assert calls == 1
