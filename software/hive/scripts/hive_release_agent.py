from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Runs ON the Hive prod host, invoked by hive-release.timer. Pull-based on
# purpose: the box takes no inbound connection from CI, so shipping never
# depends on GitHub being able to reach us. A poll that does not happen costs
# one interval; an inbound hook that does not arrive would cost the deploy.

REPO = os.environ.get("HIVE_REPO_SLUG", "basicallysource/sorter-v2")
TAG_PREFIX = "hive/v"
DEPLOY_DIR = Path(os.environ.get("HIVE_DEPLOY_DIR", "/basically/hive"))
BACKUP_DIR = Path(os.environ.get("HIVE_BACKUP_DIR", "/basically/backups/hive-db"))
BACKUP_KEEP_DAYS = int(os.environ.get("HIVE_BACKUP_KEEP_DAYS", "30"))
BACKUP_KEEP_MIN = int(os.environ.get("HIVE_BACKUP_KEEP_MIN", "7"))
BACKUP_S3_PREFIX = os.environ.get("HIVE_BACKUP_S3_PREFIX", "")
RELEASES_KEEP = int(os.environ.get("HIVE_RELEASES_KEEP", "5"))
HEALTH_URL = os.environ.get("HIVE_HEALTH_URL", "https://hive.basically.website/api/health")
PG_CONTAINER = os.environ.get("HIVE_PG_CONTAINER", "hive-postgres")
COMPOSE_PROJECT = os.environ.get("HIVE_COMPOSE_PROJECT", "hive")
GITHUB_TOKEN = os.environ.get("HIVE_GITHUB_TOKEN", "")
SERVICES = ("backend", "frontend")


@dataclass
class AgentConfig:
    deploy_dir: Path
    state_dir: Path
    releases_dir: Path
    env_file: Path
    lock_file: Path
    backup_dir: Path


def buildConfig() -> AgentConfig:
    return AgentConfig(
        deploy_dir=DEPLOY_DIR,
        state_dir=DEPLOY_DIR / "state",
        releases_dir=DEPLOY_DIR / "releases",
        env_file=DEPLOY_DIR / ".env.prod",
        lock_file=DEPLOY_DIR / "state" / "agent.lock",
        backup_dir=BACKUP_DIR,
    )


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{stamp} {message}", flush=True)


def die(message: str, code: int = 1) -> None:
    log(f"FATAL {message}")
    sys.exit(code)


def run(args: list[str], env: Optional[dict[str, str]] = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    result = subprocess.run(args, env=merged_env, capture_output=True, text=True)
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            log(f"  | {line}")
    if result.returncode != 0:
        for line in result.stderr.strip().splitlines():
            log(f"  ! {line}")
        if check:
            raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}")
    return result


def parseVersion(tag: str) -> tuple[int, ...]:
    raw = tag[len(TAG_PREFIX):] if tag.startswith(TAG_PREFIX) else tag.lstrip("v")
    parts: list[int] = []
    for chunk in raw.split(".")[:3]:
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


# ------------------------------------------------------------------ github

def githubRequest(url: str, etag: Optional[str] = None) -> tuple[Optional[Any], Optional[str]]:
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "hive-release-agent")
    if GITHUB_TOKEN:
        request.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    if etag:
        request.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode())
            return body, response.headers.get("ETag")
    except urllib.error.HTTPError as exc:
        # 304s do not count against the unauthenticated 60/hr rate limit, which
        # is the only reason a 60s poll on an anonymous token is sustainable.
        if exc.code == 304:
            return None, etag
        raise


def fetchReleases(cfg: AgentConfig) -> list[dict[str, Any]]:
    etag_path = cfg.state_dir / "releases.etag"
    cache_path = cfg.state_dir / "releases.json"
    etag = etag_path.read_text().strip() if etag_path.exists() else None
    url = f"https://api.github.com/repos/{REPO}/releases?per_page=100"
    body, new_etag = githubRequest(url, etag)
    if body is None:
        if cache_path.exists():
            return json.loads(cache_path.read_text())
        return fetchReleasesUncached(url)
    cache_path.write_text(json.dumps(body))
    if new_etag:
        etag_path.write_text(new_etag)
    return body


def fetchReleasesUncached(url: str) -> list[dict[str, Any]]:
    body, _ = githubRequest(url, None)
    return body or []


def selectNewestRelease(releases: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    candidates = [
        r for r in releases
        if str(r.get("tag_name", "")).startswith(TAG_PREFIX)
        and not r.get("draft")
        and not r.get("prerelease")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: parseVersion(r["tag_name"]))


def findReleaseByVersion(releases: list[dict[str, Any]], version: str) -> Optional[dict[str, Any]]:
    wanted = version if version.startswith(TAG_PREFIX) else f"{TAG_PREFIX}{version.lstrip('v')}"
    for release in releases:
        if release.get("tag_name") == wanted:
            return release
    return None


def downloadAsset(release: dict[str, Any], name: str, dest: Path) -> None:
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            request = urllib.request.Request(asset["browser_download_url"])
            request.add_header("User-Agent", "hive-release-agent")
            if GITHUB_TOKEN:
                request.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
            with urllib.request.urlopen(request, timeout=120) as response:
                dest.write_bytes(response.read())
            return
    raise RuntimeError(f"release {release.get('tag_name')} has no asset named {name}")


# ------------------------------------------------------------------ state

def readState(cfg: AgentConfig, name: str) -> Optional[dict[str, Any]]:
    path = cfg.state_dir / name
    if not path.exists():
        return None
    return json.loads(path.read_text())


def writeState(cfg: AgentConfig, name: str, payload: dict[str, Any]) -> None:
    path = cfg.state_dir / name
    path.write_text(json.dumps(payload, indent=2) + "\n")


# ------------------------------------------------------------------ backup

def takeBackup(cfg: AgentConfig, reason: str) -> Path:
    requirePostgres()
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = cfg.backup_dir / f"db-{stamp}-{reason}.dump"
    log(f"backup → {out}")
    with out.open("wb") as handle:
        result = subprocess.run(
            ["docker", "exec", PG_CONTAINER, "sh", "-c", "pg_dump -U $POSTGRES_USER -Fc $POSTGRES_DB"],
            stdout=handle,
            stderr=subprocess.PIPE,
            text=False,
        )
    if result.returncode != 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump failed: {result.stderr.decode(errors='replace').strip()}")
    if out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        raise RuntimeError("pg_dump produced an empty file")
    verifyBackup(out)
    log(f"  ✓ backup ok ({out.stat().st_size / 1e6:.1f} MB)")
    uploadBackup(out)
    pruneBackups(cfg)
    return out


def verifyBackup(path: Path) -> None:
    # An exit-0 pg_dump that wrote a truncated file still exits 0 if the pipe
    # broke at the right moment. `pg_restore --list` parses the archive's table
    # of contents, so it fails on exactly the corruption a size check misses.
    with path.open("rb") as handle:
        result = subprocess.run(
            ["docker", "exec", "-i", PG_CONTAINER, "pg_restore", "--list"],
            stdin=handle,
            capture_output=True,
        )
    if result.returncode != 0:
        raise RuntimeError(f"backup failed verification: {result.stderr.decode(errors='replace').strip()}")


def uploadBackup(path: Path) -> None:
    if not BACKUP_S3_PREFIX or shutil.which("aws") is None:
        return
    result = subprocess.run(
        ["aws", "s3", "cp", str(path), f"{BACKUP_S3_PREFIX}/{path.name}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log(f"  ✓ off-box copy → {BACKUP_S3_PREFIX}/{path.name}")
    else:
        log(f"  ! off-box copy failed (non-fatal): {result.stderr.strip()}")


def pruneBackups(cfg: AgentConfig) -> None:
    dumps = sorted(cfg.backup_dir.glob("db-*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    cutoff = time.time() - BACKUP_KEEP_DAYS * 86400
    # Never let age-based pruning empty the directory: if deploys have been
    # quiet for longer than the retention window, the newest dumps are the only
    # ones there are and deleting them is how you end up with no backups at all.
    for old in dumps[BACKUP_KEEP_MIN:]:
        if old.stat().st_mtime < cutoff:
            log(f"  · pruning {old.name}")
            old.unlink(missing_ok=True)


# ------------------------------------------------------------------ compose

def composeArgs(cfg: AgentConfig, compose_file: Path) -> list[str]:
    return [
        "docker", "compose",
        "--project-name", COMPOSE_PROJECT,
        "--env-file", str(cfg.env_file),
        "-f", str(compose_file),
    ]


def imageEnv(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "HIVE_BACKEND_IMAGE": manifest["images"]["backend"],
        "HIVE_FRONTEND_IMAGE": manifest["images"]["frontend"],
    }


def containerStartedAt(name: str) -> float:
    result = subprocess.run(
        ["docker", "inspect", name, "--format", "{{.State.StartedAt}}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return 0.0
    raw = result.stdout.strip()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def containerHealth(name: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", name, "--format", "{{.State.Health.Status}}"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "missing"


def httpHealthy(url: str) -> bool:
    try:
        request = urllib.request.Request(url)
        request.add_header("User-Agent", "hive-release-agent")
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def requirePostgres() -> None:
    health = containerHealth(PG_CONTAINER)
    if health != "healthy":
        raise RuntimeError(f"{PG_CONTAINER} is '{health}', refusing to deploy against it")


def applyRelease(cfg: AgentConfig, manifest: dict[str, Any], compose_file: Path) -> None:
    requirePostgres()
    env = imageEnv(manifest)
    deploy_epoch = time.time()

    log("pulling images by digest")
    run(composeArgs(cfg, compose_file) + ["pull", *SERVICES], env=env)

    # Migrate with the NEW image before any running container is touched, so a
    # bad migration fails while the old stack is still serving traffic.
    log("alembic upgrade head")
    run(composeArgs(cfg, compose_file) + ["run", "--rm", "-T", "--no-deps", "backend", "alembic", "upgrade", "head"], env=env)

    # --no-deps is load-bearing, not tidiness: postgres is in this compose
    # project, and without it `--force-recreate` would recreate the customer's
    # database container on every routine deploy. The agent never touches
    # postgres; `restart: unless-stopped` is what keeps it up.
    log("recreating services")
    run(composeArgs(cfg, compose_file) + ["up", "-d", "--no-build", "--no-deps", "--force-recreate", *SERVICES], env=env)

    # A digest change makes `up` recreate, but this check is what caught the
    # 2026-06-10 silent no-op where a rebuilt :latest tag left old containers
    # running. A start timestamp cannot lie about whether a container is new.
    for service in SERVICES:
        name = f"hive-{service}"
        if containerStartedAt(name) < deploy_epoch:
            raise RuntimeError(f"{name} is still the pre-deploy container")
        log(f"  ✓ {name} recreated")

    waitHealthy(cfg)


def waitHealthy(cfg: AgentConfig) -> None:
    log("health check")
    deadline = time.time() + 180
    while time.time() < deadline:
        states = {f"hive-{s}": containerHealth(f"hive-{s}") for s in SERVICES}
        if all(v == "healthy" for v in states.values()) and httpHealthy(HEALTH_URL):
            log(f"  ✓ healthy ({HEALTH_URL})")
            return
        time.sleep(5)
    states = {f"hive-{s}": containerHealth(f"hive-{s}") for s in SERVICES}
    raise RuntimeError(f"health check timed out: containers={states} url={HEALTH_URL}")


# ------------------------------------------------------------------ install

def stageRelease(cfg: AgentConfig, release: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    version = release["tag_name"][len(TAG_PREFIX) - 1:]
    target = cfg.releases_dir / version
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / "hive-release.json"
    compose_path = target / "docker-compose.prod.yml"
    downloadAsset(release, "hive-release.json", manifest_path)
    downloadAsset(release, "docker-compose.prod.yml", compose_path)
    manifest = json.loads(manifest_path.read_text())
    for key in ("version", "commit", "images"):
        if key not in manifest:
            raise RuntimeError(f"manifest for {version} is missing '{key}'")
    for service in SERVICES:
        reference = manifest["images"].get(service, "")
        if "@sha256:" not in reference:
            raise RuntimeError(f"manifest image for {service} is not digest-pinned: {reference!r}")
    return manifest, compose_path


def installRelease(cfg: AgentConfig, release: dict[str, Any], force: bool) -> bool:
    manifest, compose_path = stageRelease(cfg, release)
    current = readState(cfg, "current.json")
    if current and current.get("images") == manifest["images"] and not force:
        return False

    log(f"installing {manifest['version']} (commit {manifest['commit'][:9]})")
    takeBackup(cfg, "predeploy")

    try:
        applyRelease(cfg, manifest, compose_path)
    except Exception as exc:
        log(f"install FAILED: {exc}")
        rollback(cfg, current)
        raise

    if current:
        writeState(cfg, "previous.json", current)
    installed = dict(manifest)
    installed["installed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    installed["compose_file"] = str(compose_path)
    writeState(cfg, "current.json", installed)
    pruneReleases(cfg)
    log(f"✓ {manifest['version']} live")
    return True


def rollback(cfg: AgentConfig, target: Optional[dict[str, Any]]) -> None:
    if not target:
        log("no previous release recorded — cannot roll back automatically.")
        log("recover with: hive_release_agent.py install --version <known-good>")
        return
    compose_path = Path(target.get("compose_file", ""))
    if not compose_path.exists():
        log(f"previous compose file {compose_path} is gone — cannot roll back automatically")
        return
    log(f"rolling back to {target.get('version')}")
    # Deliberately no `alembic downgrade`: auto-downgrading a schema against
    # live data is how a bad deploy becomes a bad restore. The pre-deploy dump
    # in the backup dir is the recovery path if the schema is the problem.
    try:
        applyRelease(cfg, target, compose_path)
        log(f"✓ rolled back to {target.get('version')}")
        log("NOTE: migrations from the failed release were NOT reverted. If the")
        log("      schema is the problem, restore the newest *-predeploy.dump.")
    except Exception as exc:
        log(f"ROLLBACK FAILED: {exc}")


def pruneReleases(cfg: AgentConfig) -> None:
    keep: set[str] = set()
    for name in ("current.json", "previous.json"):
        state = readState(cfg, name)
        if state:
            keep.add(str(state.get("version")))
    entries = sorted(
        [p for p in cfg.releases_dir.iterdir() if p.is_dir()],
        key=lambda p: parseVersion(p.name),
        reverse=True,
    )
    for stale in entries[RELEASES_KEEP:]:
        if stale.name not in keep:
            shutil.rmtree(stale, ignore_errors=True)


# ------------------------------------------------------------------ commands

def ensureLayout(cfg: AgentConfig) -> None:
    for path in (cfg.deploy_dir, cfg.state_dir, cfg.releases_dir, cfg.backup_dir):
        path.mkdir(parents=True, exist_ok=True)
    if not cfg.env_file.exists():
        die(f"{cfg.env_file} is missing — see software/hive/scripts/CUTOVER.md")


def withLock(cfg: AgentConfig, action) -> int:
    with cfg.lock_file.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another agent run holds the lock — skipping")
            return 0
        return action()


def cmdPoll(cfg: AgentConfig, args: argparse.Namespace) -> int:
    releases = fetchReleases(cfg)
    release = selectNewestRelease(releases)
    if not release:
        log("no hive/v* release published yet")
        return 0
    current = readState(cfg, "current.json")
    if current and current.get("tag") == release["tag_name"] and not args.force:
        return 0
    installRelease(cfg, release, args.force)
    return 0


def cmdInstall(cfg: AgentConfig, args: argparse.Namespace) -> int:
    releases = fetchReleases(cfg)
    release = findReleaseByVersion(releases, args.version)
    if not release:
        die(f"no release found for version {args.version}")
    installRelease(cfg, release, True)
    return 0


def cmdRollback(cfg: AgentConfig, args: argparse.Namespace) -> int:
    rollback(cfg, readState(cfg, "previous.json"))
    return 0


def cmdBackup(cfg: AgentConfig, args: argparse.Namespace) -> int:
    takeBackup(cfg, args.reason)
    return 0


def cmdStatus(cfg: AgentConfig, args: argparse.Namespace) -> int:
    current = readState(cfg, "current.json")
    previous = readState(cfg, "previous.json")
    print(json.dumps({
        "current": current,
        "previous": {"version": previous.get("version")} if previous else None,
        "containers": {f"hive-{s}": containerHealth(f"hive-{s}") for s in SERVICES},
        "url_healthy": httpHealthy(HEALTH_URL),
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="hive_release_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    poll = sub.add_parser("poll", help="install the newest hive/v* release if it differs from what is running")
    poll.add_argument("--force", action="store_true")
    poll.set_defaults(handler=cmdPoll, locked=True)

    install = sub.add_parser("install", help="install a specific version (break-glass / rollforward)")
    install.add_argument("--version", required=True)
    install.set_defaults(handler=cmdInstall, locked=True)

    roll = sub.add_parser("rollback", help="reinstall the previously installed release")
    roll.set_defaults(handler=cmdRollback, locked=True)

    backup = sub.add_parser("backup", help="take and verify a database dump")
    backup.add_argument("--reason", default="scheduled")
    backup.set_defaults(handler=cmdBackup, locked=True)

    status = sub.add_parser("status", help="print what is installed and healthy")
    status.set_defaults(handler=cmdStatus, locked=False)

    args = parser.parse_args()
    cfg = buildConfig()
    ensureLayout(cfg)

    try:
        if args.locked:
            return withLock(cfg, lambda: args.handler(cfg, args))
        return args.handler(cfg, args)
    except Exception as exc:
        log(f"FATAL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
