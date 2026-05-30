from __future__ import annotations

from server import security
from server.security import (
    compute_allowed_ui_origins,
    is_loopback_client_address,
    is_ui_origin_allowed,
    normalize_origin,
    origin_allowed,
    websocket_connection_allowed,
)


def _set_device(monkeypatch, *, hostname="orangepi5", ips=(), tailscale=None) -> None:
    # Pin what "this device" looks like and bypass the refresh cache so each test
    # sees exactly the addresses it sets.
    monkeypatch.setattr(security.socket, "gethostname", lambda: hostname)
    monkeypatch.setattr(security, "_local_ip_addresses", lambda: [ip.lower() for ip in ips])
    monkeypatch.setattr(security, "_tailscale_hostname", lambda: tailscale)
    monkeypatch.setattr(security, "_hosts_snapshot", (0.0, frozenset()))


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


def test_compute_allowed_ui_origins_lists_this_devices_addresses(monkeypatch) -> None:
    _set_device(monkeypatch, hostname="orangepi5", ips=["192.168.89.96", "100.107.232.19"])
    origins = compute_allowed_ui_origins()
    assert "http://orangepi5:5173" in origins
    assert "http://192.168.89.96:5173" in origins
    assert "http://100.107.232.19:5173" in origins


def test_websocket_connection_allows_approved_origin_from_remote_client(monkeypatch) -> None:
    _set_device(monkeypatch)
    assert websocket_connection_allowed("http://sorter.local:5173/", "192.168.1.42") is True


def test_websocket_connection_without_origin_requires_loopback_client() -> None:
    assert websocket_connection_allowed(None, "127.0.0.1") is True
    assert websocket_connection_allowed(None, "192.168.1.42") is False


def test_ui_origin_allows_this_devices_own_addresses(monkeypatch) -> None:
    _set_device(
        monkeypatch,
        hostname="orangepi5",
        ips=["192.168.89.96"],
        tailscale="sorter-red-brick-0ffbef",
    )
    assert is_ui_origin_allowed("http://localhost:5173") is True
    assert is_ui_origin_allowed("http://127.0.0.1:5173") is True
    assert is_ui_origin_allowed("http://192.168.89.96:5173") is True  # current LAN IP
    assert is_ui_origin_allowed("http://orangepi5:5173") is True  # OS hostname
    assert is_ui_origin_allowed("http://orangepi5.local:5173") is True
    assert is_ui_origin_allowed("http://sorter-red-brick-0ffbef:5173") is True  # Tailscale name
    assert is_ui_origin_allowed("http://sorter.local:5173") is True  # any mDNS .local


def test_ui_origin_rejects_other_hosts_and_wrong_port(monkeypatch) -> None:
    _set_device(monkeypatch, hostname="orangepi5", ips=["192.168.89.96"])
    assert is_ui_origin_allowed("http://8.8.8.8:5173") is False
    assert is_ui_origin_allowed("https://evil.example:5173") is False
    assert is_ui_origin_allowed("http://10.1.2.3:5173") is False  # not one of our IPs
    assert is_ui_origin_allowed("http://192.168.1.5:5173") is False  # different LAN IP
    assert is_ui_origin_allowed("http://192.168.89.96:9999") is False  # wrong port
    assert is_ui_origin_allowed(None) is False


def test_ui_origin_honors_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("SORTER_API_ALLOWED_ORIGINS", "https://sorter.example.com")
    assert is_ui_origin_allowed("https://sorter.example.com") is True
