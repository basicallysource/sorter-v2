from __future__ import annotations

from server.security import (
    compute_allowed_ui_origins,
    is_loopback_client_address,
    normalize_origin,
    origin_allowed,
    websocket_connection_allowed,
)


def test_normalize_origin_rejects_invalid_values() -> None:
    assert normalize_origin(None) is None
    assert normalize_origin("") is None
    assert normalize_origin("example.com") is None
    assert normalize_origin("ftp://example.com") is None


def test_normalize_origin_trims_trailing_slash() -> None:
    assert normalize_origin(" http://localhost:5173/ ") == "http://localhost:5173"


def test_origin_allowed_matches_normalized_origin() -> None:
    allowed = ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert origin_allowed("http://localhost:5173/", allowed) is True
    assert origin_allowed("http://evil.example", allowed) is False


def test_loopback_detection_handles_ipv4_ipv6_and_mapped_ipv4() -> None:
    assert is_loopback_client_address("127.0.0.1") is True
    assert is_loopback_client_address("::1") is True
    assert is_loopback_client_address("::ffff:127.0.0.1") is True
    assert is_loopback_client_address("192.168.1.42") is False


def test_compute_allowed_ui_origins_honors_override(monkeypatch) -> None:
    monkeypatch.setenv(
        "SORTER_API_ALLOWED_ORIGINS",
        "http://localhost:5173, http://sorter.local:5173/",
    )
    assert compute_allowed_ui_origins() == [
        "http://localhost:5173",
        "http://sorter.local:5173",
    ]


def test_websocket_connection_allows_approved_origin_from_remote_client() -> None:
    allowed = ["http://localhost:5173", "http://sorter.local:5173"]
    assert websocket_connection_allowed(
        "http://sorter.local:5173/",
        "192.168.1.42",
        allowed,
    ) is True


def test_websocket_connection_without_origin_requires_loopback_client() -> None:
    allowed = ["http://localhost:5173"]
    assert websocket_connection_allowed(None, "127.0.0.1", allowed) is True
    assert websocket_connection_allowed(None, "192.168.1.42", allowed) is False
