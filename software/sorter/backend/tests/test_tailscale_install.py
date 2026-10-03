"""SorterOS keeps Tailscale installed so a key can be added at any time, and
uses a setup-page key that first boot could not."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from server.routers import tailscale


@pytest.fixture(autouse=True)
def isolatedActions(monkeypatch):
    monkeypatch.setattr(tailscale, "_operation_lock", threading.Lock())
    monkeypatch.setattr(tailscale, "_installing", False)
    monkeypatch.setattr(tailscale, "_install_error", None)


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


def test_a_key_switches_a_machine_already_on_a_tailnet(machine, monkeypatch):
    """Without --force-reauth, `up` on a logged-in machine ignores the key and succeeds."""
    machine["installed"] = True
    runs = []

    def run(cmd, **kwargs):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tailscale.subprocess, "run", run)
    monkeypatch.setattr(
        tailscale, "_get_status", lambda: {"installed": True, "connected": True, "hostname": "sorter-old-name-000000"}
    )
    monkeypatch.setattr(tailscale, "refresh_device_identity", lambda: None)

    assert tailscale._join("tskey-auth-test")["ok"] is True
    assert "--force-reauth" in runs[0]
    assert "--hostname=sorter-old-name-000000" in runs[0]


@pytest.mark.parametrize("connected", [False, True])
def test_status_reports_active_repair_even_when_installed(monkeypatch, connected):
    monkeypatch.setattr(tailscale, "_readStatus", lambda: {"installed": True, "connected": connected})
    monkeypatch.setattr(tailscale, "_canRepair", lambda: True)
    monkeypatch.setattr(tailscale, "_installing", True)
    monkeypatch.setattr(tailscale, "_install_error", "Try again")

    status = tailscale._get_status()

    assert status["connected"] is connected
    assert status["installing"] is True
    assert status["can_repair"] is True
    assert status["install_error"] == "Try again"


@pytest.mark.parametrize("missing", [None, "apt-get", "systemctl"])
def test_older_linux_installations_can_repair_without_sorteros_stamp(monkeypatch, tmp_path, missing):
    monkeypatch.setattr(tailscale, "SORTEROS_STAMP", tmp_path / "missing")
    monkeypatch.setattr(tailscale, "SYSTEMD_RUNTIME", tmp_path)
    monkeypatch.setattr(tailscale, "_TAILSCALE_SOCKET", "")
    monkeypatch.setattr(tailscale.sys, "platform", "linux")
    monkeypatch.setattr(tailscale.os, "geteuid", lambda: 0)
    monkeypatch.setattr(tailscale.shutil, "which", lambda command: None if command == missing else f"/bin/{command}")

    assert tailscale._canRepair() is (missing is None)


def test_custom_socket_cannot_restart_unrelated_system_daemon(monkeypatch, tmp_path):
    monkeypatch.setattr(tailscale, "SYSTEMD_RUNTIME", tmp_path)
    monkeypatch.setattr(tailscale, "_TAILSCALE_SOCKET", "/tmp/test-tailscale.sock")
    monkeypatch.setattr(tailscale.sys, "platform", "linux")
    monkeypatch.setattr(tailscale.os, "geteuid", lambda: 0)
    monkeypatch.setattr(tailscale.shutil, "which", lambda command: f"/bin/{command}")

    assert tailscale._canRepair() is False


def test_retry_wait_does_not_report_active_installation(machine, monkeypatch):
    statuses = []

    def install():
        assert tailscale._installing is True
        if not statuses:
            raise RuntimeError("offline")
        machine["installed"] = True

    def sleep(seconds):
        statuses.append(tailscale._installing)
        assert tailscale._operation_lock.acquire(blocking=False)
        tailscale._operation_lock.release()

    monkeypatch.setattr(tailscale, "_install", install)
    monkeypatch.setattr(tailscale.time, "sleep", sleep)

    tailscale._install_until_done()

    assert statuses == [False]


@pytest.mark.parametrize("succeeds", [False, True])
def test_explicit_repair_runs_when_installed_and_releases_lock(machine, monkeypatch, succeeds):
    machine["installed"] = True
    tailscale.SETUP_KEY_FILE.write_text("TAILSCALE_AUTH_KEY=tskey-auth-test\n")
    targets = []
    calls = []

    class PendingThread:
        def __init__(self, *, target, **kwargs):
            targets.append(target)

        def start(self):
            pass

    def install(*, repair=False):
        calls.append(repair)
        if not succeeds:
            raise RuntimeError("private installer detail")

    monkeypatch.setattr(tailscale, "_canRepair", lambda: True)
    monkeypatch.setattr(tailscale.threading, "Thread", PendingThread)
    monkeypatch.setattr(tailscale, "_install", install)
    monkeypatch.setattr(tailscale, "refresh_device_identity", lambda: None)

    assert tailscale.tailscaleInstall()["ok"] is True
    assert tailscale._installing is True
    assert tailscale.tailscale_logout()["ok"] is False
    assert tailscale.tailscale_up(tailscale.TailscaleUpPayload(auth_key="new-key"))["ok"] is False
    targets[0]()

    assert calls == [True]
    assert tailscale._installing is False
    assert tailscale._operation_lock.locked() is False
    assert bool(tailscale._install_error) is not succeeds
    assert "private installer detail" not in (tailscale._install_error or "")
    assert tailscale.SETUP_KEY_FILE.exists()
    assert machine["joins"] == []


def test_repair_forces_package_reinstall_and_restarts_service(machine, monkeypatch):
    machine["installed"] = True
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(tailscale.subprocess, "run", run)
    tailscale._install(repair=True)

    assert calls[0][0] == "systemd-run"
    assert "--wait" in calls[0]
    assert "apt-get install -y --reinstall tailscale" in calls[0][-1]
    assert "systemctl restart tailscaled.service" in calls[0][-1]
    assert "logout" not in calls[0][-1]


def test_failed_worker_start_releases_action_lock(machine, monkeypatch):
    class FailedThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("cannot start thread")

    monkeypatch.setattr(tailscale, "_canRepair", lambda: True)
    monkeypatch.setattr(tailscale.threading, "Thread", FailedThread)

    assert tailscale.tailscaleInstall()["ok"] is False
    assert tailscale._installing is False
    assert tailscale._operation_lock.locked() is False


def test_clear_key_failure_does_not_logout(machine, monkeypatch):
    def unlink(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(tailscale.subprocess, "run", lambda *args, **kwargs: pytest.fail("Unexpected logout"))

    assert tailscale.tailscale_logout()["ok"] is False
    assert tailscale._operation_lock.locked() is False


@pytest.mark.parametrize("action", ["tailscaleRestart", "tailscaleInstall"])
def test_repair_is_refused_outside_managed_service(monkeypatch, action):
    monkeypatch.setattr(tailscale, "_canRepair", lambda: False)
    monkeypatch.setattr(tailscale.subprocess, "run", lambda *args, **kwargs: pytest.fail("Unexpected service change"))

    assert getattr(tailscale, action)()["ok"] is False
    assert tailscale._operation_lock.locked() is False


@pytest.mark.parametrize("action", ["tailscaleRestart", "tailscaleInstall", "tailscale_logout"])
def test_first_boot_blocks_conflicting_repairs(machine, monkeypatch, action):
    monkeypatch.setattr(tailscale, "_canRepair", lambda: True)
    machine["busy"] = [True]
    tailscale.SETUP_KEY_FILE.write_text("TAILSCALE_AUTH_KEY=tskey-auth-test\n")

    assert getattr(tailscale, action)()["ok"] is False
    assert tailscale._operation_lock.locked() is False
    assert tailscale.SETUP_KEY_FILE.exists()


@pytest.mark.parametrize("return_code", [0, 1])
def test_restart_only_restarts_service_and_preserves_credentials(machine, monkeypatch, return_code):
    machine["installed"] = True
    tailscale.SETUP_KEY_FILE.write_text("TAILSCALE_AUTH_KEY=tskey-auth-test\n")
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, return_code, "", "failure")

    monkeypatch.setattr(tailscale, "_canRepair", lambda: True)
    monkeypatch.setattr(tailscale.subprocess, "run", run)

    result = tailscale.tailscaleRestart()

    assert result["ok"] is (return_code == 0)
    assert calls == [["systemctl", "restart", "tailscaled.service"]]
    assert tailscale.SETUP_KEY_FILE.exists()
    assert tailscale._operation_lock.locked() is False


@pytest.mark.parametrize("installed", [False, True])
def test_clear_sign_in_removes_pending_setup_key_before_logout(machine, monkeypatch, installed):
    machine["installed"] = installed
    tailscale.SETUP_KEY_FILE.write_text("TAILSCALE_AUTH_KEY=tskey-auth-test\n")
    calls = []

    def run(cmd, **kwargs):
        assert not tailscale.SETUP_KEY_FILE.exists()
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tailscale.subprocess, "run", run)
    monkeypatch.setattr(tailscale, "refresh_device_identity", lambda: None)

    assert tailscale.tailscale_logout()["ok"] is True
    assert not tailscale.SETUP_KEY_FILE.exists()
    assert calls == ([tailscale._cli("logout")] if installed else [])
    assert tailscale._operation_lock.locked() is False


def test_settings_key_clears_old_setup_key_and_resets_old_preferences(machine, monkeypatch):
    machine["installed"] = True
    tailscale.SETUP_KEY_FILE.write_text("TAILSCALE_AUTH_KEY=tskey-auth-old\n")
    calls = []

    def run(cmd, **kwargs):
        assert not tailscale.SETUP_KEY_FILE.exists()
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tailscale.subprocess, "run", run)
    monkeypatch.setattr(tailscale, "refresh_device_identity", lambda: None)

    assert tailscale.tailscale_up(tailscale.TailscaleUpPayload(auth_key="tskey-auth-new"))["ok"] is True
    assert "--reset" in calls[0]
    assert "--force-reauth" in calls[0]
    assert "--authkey=tskey-auth-new" in calls[0]
    assert tailscale._operation_lock.locked() is False


def test_auth_key_is_redacted_from_join_errors(machine, monkeypatch, caplog):
    machine["installed"] = True
    key = "tskey-auth-test-secret"
    tailscale.SETUP_KEY_FILE.write_text(f"TAILSCALE_AUTH_KEY={key}\n")

    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", f"up --authkey={key} failed")

    monkeypatch.setattr(tailscale.subprocess, "run", run)

    result = tailscale._join(key)
    tailscale._join_with_setup_key()

    assert result["ok"] is False
    assert key not in result["error"]
    assert key not in caplog.text
