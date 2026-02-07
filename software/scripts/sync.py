from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

LOCAL_FEEDER_MODEL_PATH = os.getenv(
    "FEEDER_MODEL_PATH",
    "/Users/spencer/code/yolo-trainer/runs/segment/checkpoints/c_channel_feeder_02_1769745064_640_small_100epochs_20batch/weights/last.pt",
)
LOCAL_CLASSIFICATION_MODEL_PATH = os.getenv(
    "CLASSIFICATION_CHAMBER_MODEL_PATH",
    "/Users/spencer/code/yolo-trainer/runs/segment/checkpoints/run_1769112999_640_small_100epochs_20batch_data/weights/best.pt",
)
LOCAL_PARTS_WITH_CATEGORIES_FILE_PATH = os.getenv(
    "PARTS_WITH_CATEGORIES_FILE_PATH",
    "/Users/spencer/Documents/GitHub/sorter-v2/software/client/parts_with_categories.json",
)

REMOTE_USER = "spencer"
REMOTE_HOST = "192.168.1.214"
REMOTE_BASE_DIR = f"/home/{REMOTE_USER}/sorter-v2/software/models"
REMOTE_FEEDER_NAME = "feeder_model.pt"
REMOTE_CLASSIFICATION_NAME = "classification_chamber_model.pt"
REMOTE_PARTS_WITH_CATEGORIES_PATH = (
    f"/home/{REMOTE_USER}/sorter-v2/software/client/parts_with_categories.json"
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
    ensureRemoteDir(remote, REMOTE_BASE_DIR)
    ensureRemoteDir(
        remote,
        str(Path(REMOTE_PARTS_WITH_CATEGORIES_PATH).parent),
    )

    syncFile(
        LOCAL_FEEDER_MODEL_PATH,
        remote,
        f"{REMOTE_BASE_DIR}/{REMOTE_FEEDER_NAME}",
    )
    syncFile(
        LOCAL_CLASSIFICATION_MODEL_PATH,
        remote,
        f"{REMOTE_BASE_DIR}/{REMOTE_CLASSIFICATION_NAME}",
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
