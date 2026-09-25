"""Software version listing and one-click git-based updates."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

# Machines on this release branch only move between stable releases: tagging
# sorter/stable/vX is how a fix is rolled out, and the Versions page offers each
# machine the newest one. Never a branch (an "update" to main is exactly what an
# operator must not be offered) and never canary.
STABLE_TAG_PREFIX = "sorter/stable/v"
RELEASE_CHANNELS = (("stable", STABLE_TAG_PREFIX),)
MAX_TAGS_LISTED = 20
GIT_TIMEOUT_S = 30.0
GIT_FETCH_TIMEOUT_S = 90.0
REF_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
DEPENDENCY_FILES = (
    "software/sorter/backend/pyproject.toml",
    "software/sorter/backend/requirements.txt",
    "software/sorter/frontend/package.json",
)

_repo_root_cache: Optional[Path] = None
_update_lock = threading.Lock()
_update_target: Optional[str] = None


class UpdateRequest(BaseModel):
    kind: str
    name: str
    restart: bool = True


def _repoRoot() -> Path:
    global _repo_root_cache
    if _repo_root_cache is None:
        backend_dir = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["git", "-C", str(backend_dir), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Could not locate git repo root: {result.stderr.strip()}")
        _repo_root_cache = Path(result.stdout.strip())
    return _repo_root_cache


def _git(*args: str, timeout: float = GIT_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(_repoRoot()), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _gitLine(*args: str) -> Optional[str]:
    result = _git(*args)
    if result.returncode != 0:
        return None
    line = result.stdout.strip()
    return line if line else None


def _commitInfo(ref: str) -> Optional[Dict[str, Any]]:
    line = _gitLine("log", "-1", "--format=%h%x09%H%x09%ct%x09%s", ref)
    if line is None:
        return None
    parts = line.split("\t", 3)
    if len(parts) != 4:
        return None
    return {
        "sha": parts[0],
        "full_sha": parts[1],
        "commit_unix": int(parts[2]),
        "subject": parts[3],
    }


def _currentInfo() -> Dict[str, Any]:
    branch = _gitLine("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    detached = branch == "HEAD"
    head = _commitInfo("HEAD") or {}
    describe = _gitLine("describe", "--tags", "--always") or head.get("sha", "unknown")
    dirty_result = _git("status", "--porcelain", "--untracked-files=no")
    dirty = bool(dirty_result.stdout.strip())
    return {
        "ref": describe if detached else branch,
        "branch": None if detached else branch,
        "detached": detached,
        "describe": describe,
        "dirty": dirty,
        **head,
    }


def _tagsForPrefix(prefix: str) -> List[Dict[str, Any]]:
    # Version-descending so the channel's newest *release number* is first,
    # independent of commit/tag dates (v1.10.0 > v1.9.0, not lexical).
    result = _git(
        "tag",
        "-l",
        f"{prefix}*",
        "--sort=-v:refname",
        "--format=%(refname:strip=2)",
    )
    if result.returncode != 0:
        return []
    tags: List[Dict[str, Any]] = []
    for name in result.stdout.strip().splitlines()[:MAX_TAGS_LISTED]:
        info = _commitInfo(f"refs/tags/{name}")
        if info is None:
            continue
        tags.append({"name": name, **info})
    return tags


def _channelEntries(current: Dict[str, Any]) -> List[Dict[str, Any]]:
    head_full = current.get("full_sha")
    entries: List[Dict[str, Any]] = []
    for channel, prefix in RELEASE_CHANNELS:
        tags = _tagsForPrefix(prefix)
        if not tags:
            continue
        latest = tags[0]
        on_channel = any(tag["full_sha"] == head_full for tag in tags)
        entries.append(
            {
                "kind": "tag",
                "channel": channel,
                "name": latest["name"],
                "sha": latest["sha"],
                "commit_unix": latest["commit_unix"],
                "subject": latest["subject"],
                "is_current": on_channel,
                "up_to_date": on_channel and latest["full_sha"] == head_full,
            }
        )
    return entries


def _changedDependencyFiles(old_sha: str, new_sha: str) -> List[str]:
    if old_sha == new_sha:
        return []
    result = _git("diff", "--name-only", old_sha, new_sha, "--", *DEPENDENCY_FILES)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.strip().splitlines() if line]


def _deferredRestart() -> None:
    def _exit() -> None:
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_exit, daemon=True).start()


@router.get("/api/system/versions")
def get_versions(refresh: bool = False) -> Dict[str, Any]:
    fetch_error: Optional[str] = None
    if refresh:
        result = _git(
            "fetch", "--tags", "--prune", "--prune-tags", "--force", "origin",
            timeout=GIT_FETCH_TIMEOUT_S,
        )
        if result.returncode != 0:
            fetch_error = result.stderr.strip() or "git fetch failed"

    current = _currentInfo()
    return {
        "ok": True,
        "current": current,
        "available": _channelEntries(current),
        "fetch_error": fetch_error,
        "update_in_progress": _update_target,
    }


@router.post("/api/system/update")
def update_version(req: UpdateRequest) -> Dict[str, Any]:
    global _update_target
    if req.kind != "tag" or not req.name.startswith(STABLE_TAG_PREFIX):
        return {"ok": False, "message": f"Only stable releases ({STABLE_TAG_PREFIX}*) can be installed on this machine."}
    if not REF_NAME_PATTERN.match(req.name) or ".." in req.name:
        return {"ok": False, "message": f"Invalid ref name: {req.name}"}

    if not _update_lock.acquire(blocking=False):
        return {"ok": False, "message": f"Update already in progress: {_update_target}"}
    try:
        _update_target = f"{req.kind}:{req.name}"

        fetch = _git(
            "fetch", "--tags", "--prune", "--prune-tags", "--force", "origin",
            timeout=GIT_FETCH_TIMEOUT_S,
        )
        if fetch.returncode != 0:
            return {"ok": False, "message": f"git fetch failed: {fetch.stderr.strip()}"}

        target_ref = f"refs/tags/{req.name}"
        target = _commitInfo(target_ref)
        if target is None:
            return {"ok": False, "message": f"Ref not found on origin: {target_ref}"}

        old = _commitInfo("HEAD") or {}
        old_sha = old.get("full_sha", "")

        # Never `git clean` here — gitignored machine config (machine.toml,
        # .env, mine/, sqlite) must survive every update. Local tracked edits
        # are stashed, not discarded, so nothing is ever silently lost.
        dirty = bool(_git("status", "--porcelain", "--untracked-files=no").stdout.strip())
        stashed = False
        if dirty:
            stash = _git("stash", "push", "-m", f"pre-update {time.strftime('%Y-%m-%d %H:%M:%S')}")
            if stash.returncode != 0:
                return {"ok": False, "message": f"git stash failed: {stash.stderr.strip()}"}
            stashed = True

        checkout = _git("checkout", "-f", "--detach", target_ref)
        if checkout.returncode != 0:
            return {"ok": False, "message": f"git checkout failed: {checkout.stderr.strip()}"}

        deps_changed = _changedDependencyFiles(old_sha, target["full_sha"])

        if req.restart:
            _deferredRestart()

        return {
            "ok": True,
            "old_sha": old.get("sha"),
            "new_sha": target["sha"],
            "changed": old_sha != target["full_sha"],
            "stashed_local_changes": stashed,
            "deps_changed": deps_changed,
            "restarting": req.restart,
        }
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "message": f"git command timed out: {exc}"}
    finally:
        _update_target = None
        _update_lock.release()
