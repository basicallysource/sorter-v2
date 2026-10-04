"""Software updates: a machine is offered the newest release of each channel,
stable and canary, and never one older than what it already runs, against a
real git repo and its origin."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from server.routers import versions


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, message: str) -> None:
    (repo / "file.txt").write_text(message)
    _git(repo, "add", "file.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A machine's checkout sitting on stable v0.1.0, with stable v0.1.1 and,
    a commit later on main, canary v0.2.0 on origin."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    _commit(work, "first")
    _git(work, "tag", "sorter/stable/v0.1.0")
    _commit(work, "second")
    _git(work, "tag", "sorter/stable/v0.1.1")
    _commit(work, "third")
    _git(work, "tag", "sorter/canary/v0.2.0")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "main", "--tags")

    checkout = tmp_path / "machine"
    _git(tmp_path, "clone", "-q", str(origin), str(checkout))
    _git(checkout, "checkout", "-q", "--detach", "refs/tags/sorter/stable/v0.1.0")

    restarts: list[bool] = []
    monkeypatch.setattr(versions, "_repo_root_cache", checkout)
    monkeypatch.setattr(versions, "_deferredRestart", lambda: restarts.append(True))
    return checkout


def _switch(name: str) -> dict:
    return versions.update_version(versions.UpdateRequest(kind="tag", name=name, restart=False))


def _head(machine: Path) -> str:
    return _git(machine, "rev-parse", "HEAD")


def _tagged(machine: Path, name: str) -> str:
    return _git(machine, "rev-parse", f"{name}^{{}}")


def test_offers_the_newest_release_of_each_channel(machine: Path):
    payload = versions.get_versions(refresh=True)
    assert payload["fetch_error"] is None
    assert payload["current"]["release_version"] == "0.1.0"
    assert [
        (e["channel"], e["name"], e["version"], e["is_current"], e["up_to_date"], e["behind"])
        for e in payload["available"]
    ] == [
        ("stable", "sorter/stable/v0.1.1", "0.1.1", True, False, False),
        ("canary", "sorter/canary/v0.2.0", "0.2.0", False, False, False),
    ]


def test_a_stable_machine_switches_to_canary(machine: Path):
    result = _switch("sorter/canary/v0.2.0")
    assert result["ok"] and result["changed"]
    assert _head(machine) == _tagged(machine, "sorter/canary/v0.2.0")
    stable, canary = versions.get_versions()["available"]
    assert (canary["is_current"], canary["up_to_date"]) == (True, True)
    # Stable is behind what the machine now runs.
    assert (stable["is_current"], stable["behind"]) == (False, True)


def test_canary_never_goes_back_to_an_older_stable(machine: Path):
    assert _switch("sorter/canary/v0.2.0")["ok"]
    result = _switch("sorter/stable/v0.1.1")
    assert result["ok"] is False
    assert "older than the software on this machine" in result["message"]
    assert _head(machine) == _tagged(machine, "sorter/canary/v0.2.0")


def test_canary_comes_back_to_stable_once_stable_catches_up(machine: Path):
    assert _switch("sorter/canary/v0.2.0")["ok"]
    work = machine.parent / "work"
    _commit(work, "stable catches up")
    _git(work, "tag", "sorter/stable/v0.2.1")
    _git(work, "push", "-q", "origin", "main", "refs/tags/sorter/stable/v0.2.1")

    stable = versions.get_versions(refresh=True)["available"][0]
    assert (stable["name"], stable["behind"]) == ("sorter/stable/v0.2.1", False)
    assert _switch("sorter/stable/v0.2.1")["ok"]
    assert _head(machine) == _tagged(machine, "sorter/stable/v0.2.1")


def test_a_stable_fix_off_main_reaches_a_stable_machine(machine: Path):
    """A stable fix released from a branch beside main (main has moved on to
    canary) is offered and installed like any stable release."""
    work = machine.parent / "work"
    _git(work, "switch", "-q", "-c", "release/stable-v0.1", "sorter/stable/v0.1.1")
    _commit(work, "fix on stable")
    _git(work, "tag", "sorter/stable/v0.1.2")
    _git(work, "push", "-q", "origin", "release/stable-v0.1", "refs/tags/sorter/stable/v0.1.2")

    stable, canary = versions.get_versions(refresh=True)["available"]
    assert (stable["name"], stable["is_current"], stable["up_to_date"]) == ("sorter/stable/v0.1.2", True, False)
    assert _switch("sorter/stable/v0.1.2")["ok"]
    assert _head(machine) == _tagged(machine, "sorter/stable/v0.1.2")
    # Canary is still newer, so the fixed stable machine can still switch to it.
    assert versions.get_versions()["available"][1]["behind"] is False


def test_updates_to_the_newer_stable_release(machine: Path):
    result = versions.update_version(versions.UpdateRequest(kind="tag", name="sorter/stable/v0.1.1"))
    assert result["ok"] and result["changed"]
    assert _git(machine, "rev-parse", "HEAD") == _git(machine, "rev-parse", "sorter/stable/v0.1.1^{}")
    assert versions.get_versions()["available"][0]["up_to_date"] is True


def test_pinned_machine_receives_a_new_stable_tag_from_main(machine: Path):
    _git(machine, "switch", "-c", "pin/old-release")
    work = machine.parent / "work"
    _commit(work, "new main release")
    _git(work, "tag", "sorter/stable/v0.1.2")
    _git(work, "push", "-q", "origin", "main", "refs/tags/sorter/stable/v0.1.2")
    config = machine / "software" / "machine.toml"
    config.parent.mkdir()
    config.write_text('[machine]\nname = "existing machine"\n')
    (machine / ".git" / "info" / "exclude").write_text("software/machine.toml\n")

    available = versions.get_versions(refresh=True)["available"]
    assert available[0]["name"] == "sorter/stable/v0.1.2"
    result = versions.update_version(
        versions.UpdateRequest(kind="tag", name=available[0]["name"], restart=False)
    )

    assert result["ok"] and result["changed"]
    assert result["restarting"] is False
    assert _git(machine, "rev-parse", "HEAD") == _git(work, "rev-parse", "main")
    assert config.read_text() == '[machine]\nname = "existing machine"\n'
    stable, canary = versions.get_versions()["available"]
    assert stable["up_to_date"] is True
    # v0.1.2 is numbered below canary v0.2.0 but contains it: still its own
    # channel's current release, while the older canary commit is behind it.
    assert (stable["behind"], canary["behind"]) == (False, True)


@pytest.mark.parametrize(
    ("kind", "name"),
    [("branch", "main"), ("tag", "v0.1.1"), ("tag", "sorter/canary/latest"), ("branch", "sorter/canary/v0.2.0")],
)
def test_refuses_anything_but_a_release(machine: Path, kind: str, name: str):
    result = versions.update_version(versions.UpdateRequest(kind=kind, name=name))
    assert result["ok"] is False
    assert _head(machine) == _tagged(machine, "sorter/stable/v0.1.0")
