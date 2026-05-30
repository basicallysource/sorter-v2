from __future__ import annotations

from server.security import (
    compute_allowed_ui_origins,
    is_loopback_client_address,
    is_ui_origin_allowed,
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
    assert websocket_connection_allowed("http://sorter.local:5173/", "192.168.1.42") is True


def test_websocket_connection_without_origin_requires_loopback_client() -> None:
    assert websocket_connection_allowed(None, "127.0.0.1") is True
    assert websocket_connection_allowed(None, "192.168.1.42") is False


def test_ui_origin_allows_local_and_private_hosts() -> None:
    assert is_ui_origin_allowed("http://localhost:5173") is True
    assert is_ui_origin_allowed("http://127.0.0.1:5173") is True
    assert is_ui_origin_allowed("http://192.168.89.96:5173") is True
    assert is_ui_origin_allowed("http://10.1.2.3:5173") is True
    assert is_ui_origin_allowed("http://172.20.5.6:5173") is True
    assert is_ui_origin_allowed("http://100.112.251.96:5173") is True  # Tailscale CGNAT
    assert is_ui_origin_allowed("http://sorter.local:5173") is True
    assert is_ui_origin_allowed("http://sorter-brown-axle.tail1234.ts.net:5173") is True


def test_ui_origin_rejects_public_hosts_and_wrong_port() -> None:
    assert is_ui_origin_allowed("http://8.8.8.8:5173") is False
    assert is_ui_origin_allowed("https://evil.example:5173") is False
    assert is_ui_origin_allowed("http://172.32.0.1:5173") is False  # just outside 172.16/12
    assert is_ui_origin_allowed("http://192.168.1.5:9999") is False  # wrong port
    assert is_ui_origin_allowed(None) is False


def test_ui_origin_honors_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("SORTER_API_ALLOWED_ORIGINS", "https://sorter.example.com")
    assert is_ui_origin_allowed("https://sorter.example.com") is True
