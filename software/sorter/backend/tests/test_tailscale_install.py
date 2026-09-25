"""SorterOS keeps Tailscale installed so a key can be added at any time, and
uses a setup-page key that first boot could not."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from server.routers import tailscale


@pytest.fixture
def machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """A SorterOS machine without Tailscale, first boot finished, nothing slept."""
    state: dict[str, Any] = {"installed": False, "sleeps": [], "busy": [], "installs": 0, "joins": []}
    monkeypatch.setattr(tailscale.shutil, "which", lambda name: "/usr/bin/tailscale" if state["installed"] else None)
    monkeypatch.setattr(tailscale.time, "sleep", lambda s: state["sleeps"].append(s))
    monkeypatch.setattr(tailscale, "_busy", lambda: state["busy"].pop(0) if state["busy"] else False)
    monkeypatch.setattr(tailscale, "SETUP_KEY_FILE", tmp_path / "tailscale.env")
    monkeypatch.setattr(tailscale, "_get_status", lambda: {"installed": state["installed"], "connected": False})
    monkeypatch.setattr(tailscale, "_install_error", None)
    return state


def test_waits_for_first_boot_then_retries_a_failed_install(machine, monkeypatch):
    machine["busy"] = [True, True]

    def install() -> None:
        machine["installs"] += 1
        if machine["installs"] == 1:
            raise RuntimeError("curl exited 56: Connection reset by peer")
        machine["installed"] = True

    monkeypatch.setattr(tailscale, "_install", install)
    tailscale._install_until_done()

    assert machine["installs"] == 2
    assert machine["sleeps"] == [tailscale.BUSY_POLL_S] * 2 + [tailscale.INSTALL_RETRY_S]
    assert tailscale._install_error is None


def test_a_failed_download_fails_the_install(tmp_path):
    # `curl | sh` exits 0 here, which is how first boot lost Tailscale.
    fake = tmp_path / "curl"
    fake.write_text("#!/bin/sh\nexit 56\n")
    fake.chmod(0o755)
    result = subprocess.run(["sh", "-c", tailscale.INSTALL_COMMAND], env={"PATH": f"{tmp_path}:/usr/bin:/bin"})
    assert result.returncode == 56


@pytest.mark.parametrize("joined", [True, False])
def test_joins_with_the_setup_page_key(machine, monkeypatch, joined):
    machine["installed"] = True
    tailscale.SETUP_KEY_FILE.write_text("TAILSCALE_AUTH_KEY=tskey-auth-test\nTAILSCALE_TAGS=tag:sorter\n")
    monkeypatch.setattr(tailscale, "_join", lambda key: machine["joins"].append(key) or {"ok": joined})

    tailscale._install_until_done()

    assert machine["joins"] == ["tskey-auth-test"]
    # Kept after a failed join so the next start tries again.
    assert tailscale.SETUP_KEY_FILE.exists() is not joined


def test_nothing_happens_off_sorteros(monkeypatch, tmp_path):
    monkeypatch.setattr(tailscale, "SORTEROS_STAMP", tmp_path / "missing")
    monkeypatch.setattr(tailscale, "_installer", None)
    tailscale.keep_installed()
    assert tailscale._installer is None


@pytest.mark.parametrize(
    "unreachable, expected",
    [
        ("timed out", "can't reach Tailscale's servers (timed out)"),
        (None, "didn't finish joining within 30 seconds: NeedsLogin"),
    ],
)
def test_a_join_that_never_finishes_says_why(machine, monkeypatch, unreachable, expected):
    machine["installed"] = True

    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(tailscale.subprocess, "run", run)
    monkeypatch.setattr(tailscale, "_get_status", lambda: {"installed": True, "connected": False, "error": "NeedsLogin"})
    monkeypatch.setattr(tailscale, "_control_unreachable", lambda: unreachable)

    result = tailscale._join("tskey-auth-test")

    assert result["ok"] is False
    assert expected in result["error"]
