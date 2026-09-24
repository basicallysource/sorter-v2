import subprocess

from server.routers import wifi


def test_nmcli_output_has_no_terminal_control_codes(monkeypatch):
    raw = "\x1b[2K\rDevice 'wlan0' successfully activated with 'abc'.\n"

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=raw, stderr="\x1b[31merror\x1b[0m")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    proc = wifi._run("device", "wifi", "connect", "x")
    assert proc.stdout == "Device 'wlan0' successfully activated with 'abc'.\n"
    assert proc.stderr == "error"


def _fake_nmcli(monkeypatch, calls):
    status = "wlan0:wifi:disconnected:--\nap0:wifi:connected:sorteros-ap\np2p-dev-wlan0:wifi-p2p:disconnected:--\n"

    def fake_run(cmd, **kwargs):
        calls.append(cmd[1:])
        out = status if cmd[1:5] == ["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    monkeypatch.setattr(wifi, "_have_nmcli", lambda: True)


def test_the_setup_networks_interface_is_not_an_adapter(monkeypatch):
    _fake_nmcli(monkeypatch, [])
    assert [d["device"] for d in wifi._wifi_devices()] == ["wlan0"]


def test_connect_uses_the_real_adapter_never_the_setup_networks(monkeypatch):
    calls = []
    _fake_nmcli(monkeypatch, calls)
    assert wifi.wifi_connect(wifi.WifiConnectPayload(ssid="HomeNet", password="right-password"))["ok"]
    assert ["device", "wifi", "connect", "HomeNet", "ifname", "wlan0", "password", "right-password"] in calls
    assert not wifi.wifi_connect(wifi.WifiConnectPayload(ssid="HomeNet", device="ap0"))["ok"]
