from __future__ import annotations

from server.routers import network


def test_parse_wifi_scan_sorts_dedupes_and_unescapes_colons() -> None:
    stdout = "\n".join([
        r"*:Heimnetz:87:WPA2",
        r":Nachbar\:5G:62:WPA2 WPA3",
        r":Heimnetz:45:WPA2",  # duplicate, weaker — dropped
        r"::30:",              # hidden/empty SSID — dropped
        r":Offen:12:",
        "garbage-line",
    ])

    networks = network.parse_wifi_scan(stdout)

    assert [n["ssid"] for n in networks] == ["Heimnetz", "Nachbar:5G", "Offen"]
    assert networks[0] == {"ssid": "Heimnetz", "signal": 87, "security": "WPA2", "in_use": True}
    assert networks[1]["in_use"] is False
    assert networks[2]["security"] == ""


def test_parse_devices() -> None:
    stdout = "\n".join([
        "wlan0:wifi:disconnected:",
        "enx00e04c680001:ethernet:connected:Wired connection 1",
        "lo:loopback:unmanaged:",
    ])

    devices = network.parse_devices(stdout)

    assert devices[0] == {"device": "wlan0", "type": "wifi", "state": "disconnected", "connection": None}
    assert devices[1]["connection"] == "Wired connection 1"
    assert devices[2]["type"] == "loopback"


def test_nmconnection_body_with_password() -> None:
    body = network.nmconnection_body("Heimnetz", "geheim123", hidden=False)

    assert "id=Heimnetz" in body
    assert "ssid=Heimnetz" in body
    assert "autoconnect=true" in body
    assert "key-mgmt=wpa-psk" in body
    assert "psk=geheim123" in body
    assert "hidden=true" not in body
    assert "[ipv4]\nmethod=auto" in body


def test_nmconnection_body_open_and_hidden() -> None:
    body = network.nmconnection_body("Offen", "", hidden=True)

    assert "hidden=true" in body
    assert "wifi-security" not in body
    assert "psk=" not in body


def test_connect_rejects_bad_input(monkeypatch) -> None:
    monkeypatch.setattr(network, "_nmcli_available", lambda: True)

    bad_ssid = network.connect_wifi(network.WifiConnectPayload(ssid="a/b", password=""))
    assert bad_ssid["ok"] is False and "SSID" in bad_ssid["error"]

    short_pw = network.connect_wifi(network.WifiConnectPayload(ssid="Heimnetz", password="kurz"))
    assert short_pw["ok"] is False and "8-63" in short_pw["error"]


def test_endpoints_degrade_without_nmcli(monkeypatch) -> None:
    monkeypatch.setattr(network.shutil, "which", lambda _: None)

    assert network.get_wifi_status() == {"available": False}
    assert network.scan_wifi()["available"] is False
    assert network.connect_wifi(network.WifiConnectPayload(ssid="x", password=""))["ok"] is False
    assert network.forget_wifi(network.WifiForgetPayload(ssid="x"))["ok"] is False
    assert network.set_wifi_radio(network.WifiRadioPayload(enabled=True))["ok"] is False
