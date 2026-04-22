from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.api import app


def test_websocket_accepts_allowed_origin() -> None:
    with (
        patch("server.api.compute_allowed_ui_origins", return_value=["http://localhost:5173"]),
        patch("server.api.getRecentKnownObjects", return_value=[]),
        TestClient(app) as client,
    ):
        with client.websocket_connect("/ws", headers={"origin": "http://localhost:5173"}) as websocket:
            first_message = websocket.receive_json()

    assert first_message["tag"] == "identity"


def test_websocket_rejects_disallowed_origin() -> None:
    with (
        patch("server.api.compute_allowed_ui_origins", return_value=["http://localhost:5173"]),
        patch("server.api.getRecentKnownObjects", return_value=[]),
        TestClient(app) as client,
    ):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws", headers={"origin": "http://evil.example"}):
                pass

    assert exc_info.value.code == 1008
