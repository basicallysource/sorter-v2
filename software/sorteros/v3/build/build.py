"""
v3 SorterOS image builder.

Runs inside a Linux environment (a colima VM on the Mac, or any Linux box).
Builds a bootable Orange Pi 5 .img with the v3 overlay applied and a
minimal apt delta. No partition surgery, no FAT, no qemu. Single ext4.

Phases (run with --phase <name> for a partial rerun):
  prep              — fetch base img if missing, copy to working file
  mount             — loop-mount the ext4 partition
  overlay           — rsync overlay/ into the rootfs
  chroot            — run chroot_apt.sh inside the rootfs
  firstboot-config  — write /etc/sorteros-config.toml placeholder
  finalize          — unmount, rename, report

Default with no --phase: run all of them in order.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PHASES = ["prep", "mount", "overlay", "chroot", "firstboot-config", "finalize"]


@dataclass
class BuildCtx:
    config: dict
    work_img: Path
    cache_dir: Path
    overlay_dir: Path
    mnt: Path
    out_dir: Path
    branch: str


def log(msg: str) -> None:
    print(f"[build {dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    log(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kw)


def require_root() -> None:
    if os.geteuid() != 0:
        sys.exit("must run as root (loop-mount + chroot)")


def phase_prep(ctx: BuildCtx) -> None:
    ctx.cache_dir.mkdir(parents=True, exist_ok=True)
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    base = ctx.cache_dir / ctx.config["base"]["filename"]
    if not base.exists():
        sys.exit(
            f"base image not at {base}.\n"
            f"Download manually from {ctx.config['base']['url']}\n"
            f"and place it at the path above. (TODO: automate when URL is stable.)"
        )
    log(f"copying base → {ctx.work_img}")
    shutil.copy2(base, ctx.work_img)


def phase_mount(ctx: BuildCtx) -> None:
    # TODO: losetup -fP ctx.work_img, mount p1 at ctx.mnt.
    log(f"TODO phase_mount: mount {ctx.work_img} at {ctx.mnt}")


def phase_overlay(ctx: BuildCtx) -> None:
    # TODO: rsync ctx.overlay_dir/ → ctx.mnt/
    log(f"TODO phase_overlay: rsync {ctx.overlay_dir} → {ctx.mnt}")


def phase_chroot(ctx: BuildCtx) -> None:
    # TODO: bind /dev /proc /sys, copy chroot_apt.sh into ctx.mnt/tmp/, chroot+run.
    log(f"TODO phase_chroot: chroot {ctx.mnt} /tmp/chroot_apt.sh")


def phase_firstboot_config(ctx: BuildCtx) -> None:
    # TODO: write /etc/sorteros-config.toml placeholder with magic markers,
    # padded to placeholder_kb. The browser sorteros-setup site searches
    # for the markers and overwrites the region in place.
    kb = ctx.config["firstboot"]["placeholder_kb"]
    log(f"TODO phase_firstboot_config: write {kb} KB placeholder into {ctx.mnt}")


def phase_finalize(ctx: BuildCtx) -> None:
    # TODO: unmount, losetup -d, rename work.img → out/sorteros-v3-<date>.img.
    log(f"TODO phase_finalize: unmount {ctx.mnt}, output to {ctx.out_dir}")


PHASE_FNS = {
    "prep": phase_prep,
    "mount": phase_mount,
    "overlay": phase_overlay,
    "chroot": phase_chroot,
    "firstboot-config": phase_firstboot_config,
    "finalize": phase_finalize,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=PHASES, help="run only this phase")
    ap.add_argument("--branch", default=None, help="override branch from config.toml")
    ap.add_argument("--config", default=str(SCRIPT_DIR / "config.toml"))
    args = ap.parse_args()

    require_root()

    with open(args.config, "rb") as f:
        config = tomllib.load(f)

    branch = args.branch or config["branch"]["default"]

    ctx = BuildCtx(
        config=config,
        work_img=SCRIPT_DIR / "out" / "work.img",
        cache_dir=SCRIPT_DIR / "cache",
        overlay_dir=SCRIPT_DIR / "overlay",
        mnt=Path("/mnt/sorteros-build"),
        out_dir=SCRIPT_DIR / "out",
        branch=branch,
    )

    phases = [args.phase] if args.phase else PHASES
    for p in phases:
        log(f"=== phase: {p} ===")
        PHASE_FNS[p](ctx)
    log("done.")


if __name__ == "__main__":
    main()
