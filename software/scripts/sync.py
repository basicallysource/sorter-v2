from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

LOCAL_PARTS_WITH_CATEGORIES_FILE_PATH = os.getenv(
    "PARTS_WITH_CATEGORIES_FILE_PATH",
    "/Users/spencer/Documents/GitHub/sorter-v2/software/sorter/backend/parts_with_categories.json",
)

REMOTE_USER = "spencer"
REMOTE_HOST = "192.168.1.214"
REMOTE_PARTS_WITH_CATEGORIES_PATH = (
    f"/home/{REMOTE_USER}/sorter-v2/software/sorter/backend/parts_with_categories.json"
)

RSYNC_FLAGS = ["-avz"]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def ensureRemoteDir(remote: str, remote_dir: str) -> None:
    result = run(["ssh", remote, "mkdir", "-p", remote_dir])
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create remote dir {remote_dir}: {result.stderr.strip()}"
        )


def remoteFileExists(remote: str, remote_path: str) -> bool:
    result = run(["ssh", remote, "test", "-f", remote_path])
    return result.returncode == 0


def rsyncAvailable() -> bool:
    result = run(["rsync", "--version"])
    return result.returncode == 0


def syncFile(local_path: str, remote: str, remote_path: str) -> None:
    if not Path(local_path).exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")

    if remoteFileExists(remote, remote_path):
        print(f"Skip: {remote_path} already exists on {remote}")
        return

    if rsyncAvailable():
        cmd = ["rsync", *RSYNC_FLAGS, local_path, f"{remote}:{remote_path}"]
    else:
        cmd = ["scp", local_path, f"{remote}:{remote_path}"]

    result = run(cmd)
    if result.returncode != 0:
        raise RuntimeError(
            "Copy failed: "
            + " ".join(shlex.quote(part) for part in cmd)
            + f"\n{result.stderr.strip()}"
        )

    print(f"Copied {local_path} -> {remote}:{remote_path}")


def main() -> int:
    remote = f"{REMOTE_USER}@{REMOTE_HOST}"
    ensureRemoteDir(
        remote,
        str(Path(REMOTE_PARTS_WITH_CATEGORIES_PATH).parent),
    )

    syncFile(
        LOCAL_PARTS_WITH_CATEGORIES_FILE_PATH,
        remote,
        REMOTE_PARTS_WITH_CATEGORIES_PATH,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
