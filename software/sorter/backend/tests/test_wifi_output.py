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
