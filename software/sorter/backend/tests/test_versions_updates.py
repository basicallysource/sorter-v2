"""Software updates on this release branch: a machine is offered the newest
stable release and nothing else, against a real git repo and its origin."""

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
    """A machine's checkout sitting on stable v0.1.0, with v0.1.1 and a canary
    tag on origin."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    _commit(work, "first")
    _git(work, "tag", "sorter/stable/v0.1.0")
    _commit(work, "second")
    _git(work, "tag", "sorter/stable/v0.1.1")
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


def test_offers_the_newest_stable_release_only(machine: Path):
    payload = versions.get_versions(refresh=True)
    assert payload["fetch_error"] is None
    assert [(e["kind"], e["name"], e["is_current"], e["up_to_date"]) for e in payload["available"]] == [
        ("tag", "sorter/stable/v0.1.1", True, False)
    ]


def test_updates_to_the_newer_stable_release(machine: Path):
    result = versions.update_version(versions.UpdateRequest(kind="tag", name="sorter/stable/v0.1.1"))
    assert result["ok"] and result["changed"]
    assert _git(machine, "rev-parse", "HEAD") == _git(machine, "rev-parse", "sorter/stable/v0.1.1^{}")
    assert versions.get_versions()["available"][0]["up_to_date"] is True


@pytest.mark.parametrize(
    ("kind", "name"),
    [("branch", "main"), ("tag", "sorter/canary/v0.2.0"), ("tag", "v0.1.1")],
)
def test_refuses_anything_but_a_stable_release(machine: Path, kind: str, name: str):
    result = versions.update_version(versions.UpdateRequest(kind=kind, name=name))
    assert result["ok"] is False
    assert _git(machine, "rev-parse", "HEAD") == _git(machine, "rev-parse", "sorter/stable/v0.1.0^{}")
