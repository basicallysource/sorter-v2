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

Default with no --phase: run all of them in order. Each phase is
idempotent on its own — re-running a single phase won't break the
overall state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PHASES = ["prep", "mount", "overlay", "chroot", "firstboot-config", "finalize"]

CFG_START_MARKER = "__SORTEROS_CFG_START__"
CFG_END_MARKER = "__SORTEROS_CFG_END__"


@dataclass
class BuildCtx:
    config: dict
    work_img: Path
    cache_dir: Path
    overlay_dir: Path
    mnt: Path
    out_dir: Path
    state_file: Path
    branch: str


def log(msg: str) -> None:
    print(f"[build {dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    log(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kw)


def require_root() -> None:
    if os.geteuid() != 0:
        sys.exit("must run as root (loop-mount + chroot)")


def state_read(ctx: BuildCtx) -> dict:
    if not ctx.state_file.exists():
        return {}
    return json.loads(ctx.state_file.read_text())


def state_write(ctx: BuildCtx, **kw) -> None:
    s = state_read(ctx)
    s.update(kw)
    ctx.state_file.write_text(json.dumps(s, indent=2))


def is_mounted(path: Path) -> bool:
    try:
        return subprocess.run(["mountpoint", "-q", str(path)]).returncode == 0
    except FileNotFoundError:
        # mountpoint not available — fallback to /proc/mounts grep
        return any(str(path) in ln for ln in Path("/proc/mounts").read_text().splitlines())


# ─── prep ──────────────────────────────────────────────────────────────────

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


# ─── mount ─────────────────────────────────────────────────────────────────

def phase_mount(ctx: BuildCtx) -> None:
    if is_mounted(ctx.mnt):
        log(f"{ctx.mnt} already mounted; skipping")
        return

    if not ctx.work_img.exists():
        sys.exit(f"{ctx.work_img} missing — run --phase prep first")

    ctx.mnt.mkdir(parents=True, exist_ok=True)
    log(f"losetup -fP {ctx.work_img}")
    out = subprocess.check_output(
        ["losetup", "--show", "-fP", str(ctx.work_img)], text=True
    ).strip()
    loop = out
    state_write(ctx, loop=loop)

    # The Orange Pi base image has one ext4 partition at p1. Verify.
    part = f"{loop}p1"
    if not Path(part).exists():
        run(["losetup", "-d", loop])
        sys.exit(f"expected {part} to exist; image layout is unexpected")

    log(f"fsck {part}")
    # e2fsck -fy: force-check, answer yes to repairs. Returns 1 if it
    # repaired things, 2 if it needs reboot, 0 if clean. Treat 0/1 as OK.
    p = subprocess.run(["e2fsck", "-fy", part])
    if p.returncode not in (0, 1):
        sys.exit(f"e2fsck exit {p.returncode} — image is unhealthy")

    run(["mount", part, str(ctx.mnt)])
    state_write(ctx, partition=part)


# ─── overlay ───────────────────────────────────────────────────────────────

def phase_overlay(ctx: BuildCtx) -> None:
    if not is_mounted(ctx.mnt):
        sys.exit("rootfs not mounted — run --phase mount first")

    if not ctx.overlay_dir.exists():
        log(f"overlay dir {ctx.overlay_dir} does not exist; nothing to copy")
        return

    # -a preserves perms/symlinks; -H preserves hard links inside the overlay.
    # --no-times so we don't pollute mtimes of files that haven't changed.
    run([
        "rsync", "-aH", "--no-times",
        f"{ctx.overlay_dir}/", f"{ctx.mnt}/",
    ])

    # Record the branch so the firstboot daemon knows what to clone.
    sorteros_etc = ctx.mnt / "etc" / "sorteros"
    sorteros_etc.mkdir(parents=True, exist_ok=True)
    (sorteros_etc / "branch").write_text(ctx.branch + "\n")
    log(f"branch baked into image: {ctx.branch}")


# ─── chroot ────────────────────────────────────────────────────────────────

CHROOT_BINDS = ["dev", "proc", "sys", "dev/pts"]


def _bind_mounts_up(ctx: BuildCtx) -> None:
    for b in CHROOT_BINDS:
        target = ctx.mnt / b
        target.mkdir(parents=True, exist_ok=True)
        if not is_mounted(target):
            run(["mount", "--bind", f"/{b}", str(target)])


def _bind_mounts_down(ctx: BuildCtx) -> None:
    # Unmount in reverse order to avoid "busy" on the nested /dev/pts.
    for b in reversed(CHROOT_BINDS):
        target = ctx.mnt / b
        if is_mounted(target):
            # lazy unmount as a fallback for stubborn binds
            p = subprocess.run(["umount", str(target)])
            if p.returncode != 0:
                run(["umount", "-l", str(target)])


def phase_chroot(ctx: BuildCtx) -> None:
    if not is_mounted(ctx.mnt):
        sys.exit("rootfs not mounted — run --phase mount first")

    chroot_script_src = SCRIPT_DIR / "chroot_apt.sh"
    if not chroot_script_src.exists():
        sys.exit(f"{chroot_script_src} missing")

    tmp_dst = ctx.mnt / "tmp" / "chroot_apt.sh"
    tmp_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(chroot_script_src, tmp_dst)
    tmp_dst.chmod(0o755)

    _bind_mounts_up(ctx)
    try:
        # /etc/resolv.conf inside the chroot may be a stub symlink; the
        # chroot_apt.sh script will write a fallback if needed.
        run(["chroot", str(ctx.mnt), "/tmp/chroot_apt.sh"])
    finally:
        _bind_mounts_down(ctx)
        try:
            tmp_dst.unlink()
        except FileNotFoundError:
            pass


# ─── firstboot-config ──────────────────────────────────────────────────────

def phase_firstboot_config(ctx: BuildCtx) -> None:
    if not is_mounted(ctx.mnt):
        sys.exit("rootfs not mounted — run --phase mount first")

    kb = int(ctx.config["firstboot"]["placeholder_kb"])
    total = kb * 1024

    # Layout inside the placeholder file (raw bytes, fixed total size):
    #
    #   # __SORTEROS_CFG_START__
    #   <TOML body — initially blank/comment so the file is a valid TOML>
    #   # __SORTEROS_CFG_END__
    #   <newline padding to total bytes>
    #
    # sorteros-setup (the browser-side patcher) finds the markers and
    # overwrites the region between them. ext4 metadata doesn't move
    # because total file size is fixed.
    header = f"# {CFG_START_MARKER}\n# sorteros boot-time config — overwrite via setup.basically.website\n"
    footer = f"# {CFG_END_MARKER}\n"
    body = header + ("# (blank — boot into AP setup mode)\n" * 4) + footer

    if len(body) > total:
        sys.exit(f"placeholder header/footer too large ({len(body)} > {total})")
    payload = body + ("\n" * (total - len(body)))
    assert len(payload) == total

    dest = ctx.mnt / "etc" / "sorteros-config.toml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(payload)
    os.chmod(dest, 0o644)
    log(f"wrote {dest} ({total} bytes)")


# ─── finalize ──────────────────────────────────────────────────────────────

def phase_finalize(ctx: BuildCtx) -> None:
    # Tear down any leftover binds (paranoia — phase_chroot does it, but
    # we might be running --phase finalize after a hard crash).
    _bind_mounts_down(ctx)

    if is_mounted(ctx.mnt):
        run(["umount", str(ctx.mnt)])

    s = state_read(ctx)
    loop = s.get("loop")
    if loop and Path(loop).exists():
        run(["losetup", "-d", loop])
        state_write(ctx, loop=None, partition=None)

    date = dt.date.today().isoformat()
    name = ctx.config["output"]["name"].format(date=date)
    final = ctx.out_dir / name
    if final.exists():
        final.unlink()
    ctx.work_img.rename(final)

    size = final.stat().st_size
    log(f"image ready: {final}  ({size / 1024 / 1024:.0f} MiB)")


# ─── orchestration ────────────────────────────────────────────────────────

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
        state_file=SCRIPT_DIR / "out" / ".build-state.json",
        branch=branch,
    )

    phases = [args.phase] if args.phase else PHASES
    for p in phases:
        log(f"=== phase: {p} ===")
        PHASE_FNS[p](ctx)
    log("done.")


if __name__ == "__main__":
    main()
