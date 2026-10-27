"""What Settings says about Tailscale, read from `tailscale status --json` as
Tailscale 1.104 writes it."""

from __future__ import annotations

import subprocess

import pytest

from server import tailscale_status
from server.routers import tailscale


def _status(backend_state="Running", health=(), tags=("tag:sorter",), dns="sorter-red-brick-0ffbef.tail1234ab.ts.net."):
    return {
        "BackendState": backend_state,
        "Health": list(health),
        "CurrentTailnet": {"Name": "example.github", "MagicDNSSuffix": "tail1234ab.ts.net"} if dns else None,
        "Self": {
            "DNSName": dns,
            "HostName": "sorter-red-brick-0ffbef" if dns else "orangepi5",
            "Tags": list(tags) or None,
            "UserID": 42,
            "TailscaleIPs": ["100.70.1.2", "fd7a:115c:a1e0::1"] if dns else None,
        },
        "User": {"42": {"LoginName": "builder@example.com"}},
    }


def test_a_machine_that_joined_with_a_tagged_key_says_which_network_and_tag():
    status = tailscale_status.parse(_status())

    assert status["state"] == "connected" and status["connected"] is True
    assert status["hostname"] == "sorter-red-brick-0ffbef"
    assert status["ipv4"] == "100.70.1.2"
    assert status["network"] == "example.github"
    assert status["tailnet"] == "tail1234ab.ts.net"
    assert status["tags"] == ["tag:sorter"]
    assert status["owner"] is None


def test_a_machine_signed_in_as_a_person_says_who():
    status = tailscale_status.parse(_status(tags=()))

    assert status["tags"] == []
    assert status["owner"] == "builder@example.com"


def test_a_machine_that_never_joined_is_not_connected_and_has_no_name():
    status = tailscale_status.parse(_status("NeedsLogin", ["Tailscale is stopped."], dns=""))

    assert status["state"] == "logged_out" and status["connected"] is False
    assert status["hostname"] is None
    assert status["error"] == "Not on a Tailscale network yet."


def test_a_refused_key_shows_as_logged_out_and_keeps_the_name():
    # After a bad key the daemon stays Running; only Health says it logged out.
    error = "You are logged out. The last login error was: invalid key: API key does not exist"
    status = tailscale_status.parse(_status(health=[error]))

    assert status["state"] == "logged_out" and status["connected"] is False
    assert status["error"] == error
    assert status["hostname"] == "sorter-red-brick-0ffbef"


def test_a_network_that_approves_devices_by_hand_says_so():
    status = tailscale_status.parse(_status("NeedsMachineAuth"))

    assert status["state"] == "needs_approval" and status["connected"] is False
    assert "approve" in status["error"]


def test_a_stopped_service_is_named(monkeypatch):
    monkeypatch.setattr(tailscale_status.shutil, "which", lambda name: "/usr/bin/tailscale")
    stderr = "failed to connect to local tailscaled; it doesn't appear to be running (sudo systemctl start tailscaled ?)"
    monkeypatch.setattr(
        tailscale_status.subprocess, "run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, "", stderr)
    )

    assert tailscale_status.read() == {
        "installed": True, "connected": False, "state": "stopped", "error": "The Tailscale service isn't running.",
    }


@pytest.mark.parametrize("installing, state", [(False, "not_installed"), (True, "installing")])
def test_a_machine_without_tailscale(monkeypatch, installing, state):
    monkeypatch.setattr(tailscale_status.shutil, "which", lambda name: None)
    monkeypatch.setattr(tailscale, "_installing", installing)
    monkeypatch.setattr(tailscale, "_canRepair", lambda: True)

    assert tailscale._get_status()["state"] == state
