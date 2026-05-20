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
  zip               — compress .img → .img.zip for GitHub Releases distribution

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
import zipfile
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PHASES = ["prep", "grow", "mount", "overlay", "chroot", "firstboot-config", "finalize", "zip"]

# Bytes of free space to add to the image before chroot. The Orange Pi
# base image is sized for an 8 GB SD card but only ~2.5 GB is free
# inside the ext4; node22 + tailscale fill it.
# Grow by GROW_MIB before mounting; the rootfs will be GROW_MIB / 1024 GiB
# larger than vendor. First-boot growfs on the Pi expands further to fill
# whatever real SD card it's flashed to.
GROW_MIB = 4096

# Markers found by the browser-side patcher in sorteros-setup.
# Must match software/sorteros/sorteros-setup/src/lib/img-patch.ts.
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

def _teardown_mnt(ctx: BuildCtx) -> None:
    """Unmount everything under ctx.mnt and detach the loop device."""
    _bind_mounts_down(ctx)
    if is_mounted(ctx.mnt):
        subprocess.run(["umount", str(ctx.mnt)])
    s = state_read(ctx)
    loop = s.get("loop")
    if loop and Path(loop).exists():
        subprocess.run(["losetup", "-d", loop])

def _find_base_image(ctx: BuildCtx) -> Path:
    """Look for the base .img in order of preference:
        1. $SORTEROS_BASE_IMG env var (explicit override)
        2. cache/<filename> in this build dir
        3. ~/Downloads/<filename> (Spencer's usual landing zone)
        4. /Users/spencer/Downloads/<filename> (same, from inside colima)
        5. /Volumes/macHome/Downloads/<filename> (some colima setups)
    """
    filename = ctx.config["base"]["filename"]
    candidates: list[Path] = []
    env = os.environ.get("SORTEROS_BASE_IMG")
    if env:
        candidates.append(Path(env))
    candidates.append(ctx.cache_dir / filename)
    home = Path(os.environ.get("HOME", "/root"))
    candidates.append(home / "Downloads" / filename)
    candidates.append(Path("/Users/spencer/Downloads") / filename)
    candidates.append(Path("/Volumes/macHome/Downloads") / filename)
    for c in candidates:
        if c.exists():
            return c
    sys.exit(
        "base image not found. Looked at:\n  "
        + "\n  ".join(str(c) for c in candidates)
        + f"\nSet SORTEROS_BASE_IMG=<path> or drop it in {ctx.cache_dir}/."
    )


def phase_prep(ctx: BuildCtx) -> None:
    ctx.cache_dir.mkdir(parents=True, exist_ok=True)
    ctx.out_dir.mkdir(parents=True, exist_ok=True)

    # Clean up any leftover state from a previous failed build so grow/mount
    # don't refuse to run because the mountpoint is still active.
    _teardown_mnt(ctx)
    if ctx.work_img.exists():
        log(f"removing stale {ctx.work_img.name}")
        ctx.work_img.unlink()
    ctx.state_file.unlink(missing_ok=True)

    base = _find_base_image(ctx)
    log(f"base image: {base}")
    log(f"copying base → {ctx.work_img}")
    shutil.copy2(base, ctx.work_img)


# ─── grow ──────────────────────────────────────────────────────────────────

def phase_grow(ctx: BuildCtx) -> None:
    """Grow the image file and extend p1 + ext4 to use the new space.

    Not partition surgery in the v2 sense — the partition table layout
    stays the same (single ext4 at p1), we just push the partition end
    further out and resize the filesystem. No second partition, no FAT,
    no bootloader region touched.
    """
    if not ctx.work_img.exists():
        sys.exit(f"{ctx.work_img} missing — run --phase prep first")
    if is_mounted(ctx.mnt):
        sys.exit("rootfs is mounted — grow must run before mount")

    orig = ctx.work_img.stat().st_size
    log(f"growing image by {GROW_MIB} MiB ({orig // (1024 * 1024)} MiB → {orig // (1024 * 1024) + GROW_MIB} MiB)")
    # truncate appends zero bytes to the end of the file
    with open(ctx.work_img, "rb+") as f:
        f.seek(orig + GROW_MIB * 1024 * 1024 - 1)
        f.write(b"\0")

    # Attach via losetup so partition tools see partitions.
    loop = subprocess.check_output(
        ["losetup", "--show", "-fP", str(ctx.work_img)], text=True
    ).strip()
    try:
        # Grow partition 1 to fill the new space.
        run(["growpart", loop, "1"])
        # Detach + reattach so the kernel rescans the (now larger) partition.
        run(["losetup", "-d", loop])
        loop = subprocess.check_output(
            ["losetup", "--show", "-fP", str(ctx.work_img)], text=True
        ).strip()
        part = f"{loop}p1"
        # e2fsck before resize2fs (refuses unclean fs)
        p = subprocess.run(["e2fsck", "-fy", part])
        if p.returncode not in (0, 1):
            sys.exit(f"e2fsck exit {p.returncode}")
        run(["resize2fs", part])
    finally:
        run(["losetup", "-d", loop])
    log("grow complete")


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

    # Record the branch and version so the firstboot daemon knows what to clone
    # and so anyone who SSHes in can identify the image.
    sorteros_etc = ctx.mnt / "etc" / "sorteros"
    sorteros_etc.mkdir(parents=True, exist_ok=True)
    version = ctx.config["output"]["version"]
    (sorteros_etc / "branch").write_text(ctx.branch + "\n")
    (sorteros_etc / "version").write_text(version + "\n")
    log(f"branch baked into image: {ctx.branch}")
    log(f"version baked into image: {version}")

    # MOTD so `ssh root-pi` immediately shows the image version.
    motd = ctx.mnt / "etc" / "motd"
    motd.write_text(f"\nSorterOS  v{version}  ({ctx.branch})\n\n")
    log(f"wrote /etc/motd")

    # Tailscale auth key is intentionally NOT baked in at build time.
    # It is supplied at setup time via the sorteros-setup browser customizer,
    # written into /etc/sorteros-config.toml, and applied by firstboot
    # stage_apply_config_toml → stage_tailscale_up.
    #
    # The key is kept in .env as TAILSCALE_AUTH_KEY for reference but build.py
    # no longer reads it. To re-enable baking (e.g. for internal test images),
    # rename it to SORTEROS_BAKE_TAILSCALE_AUTH_KEY and update the lookup below.
    ts_key = os.environ.get("SORTEROS_BAKE_TAILSCALE_AUTH_KEY", "")
    ts_tags = os.environ.get("TAILSCALE_TAGS", "tag:sorter")
    if ts_key:
        ts_env = sorteros_etc / "tailscale.env"
        ts_env.write_text(f"TAILSCALE_AUTH_KEY={ts_key}\nTAILSCALE_TAGS={ts_tags}\n")
        ts_env.chmod(0o600)
        log("baked tailscale auth key into /etc/sorteros/tailscale.env")

    # Without this overlay the AP6275P wifi chip is invisible to the kernel.
    env_txt = ctx.mnt / "boot" / "orangepiEnv.txt"
    if env_txt.exists():
        content = env_txt.read_text()
        if "wifi-ap6275p" not in content:
            with env_txt.open("a") as f:
                f.write("\noverlays=wifi-ap6275p\n")
            log("appended overlays=wifi-ap6275p to /boot/orangepiEnv.txt")
        else:
            log("overlays=wifi-ap6275p already present in /boot/orangepiEnv.txt")
    else:
        log("WARN: /boot/orangepiEnv.txt not found; wifi overlay not set")



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

    # Copy the host's working resolv.conf into the chroot. The Orange Pi
    # base image has a stub or hardcoded nameserver that may be unreachable
    # from inside the build VM; the host resolver is always correct.
    resolv_dst = ctx.mnt / "etc" / "resolv.conf"
    resolv_dst.unlink(missing_ok=True)
    shutil.copy2("/etc/resolv.conf", resolv_dst)

    _bind_mounts_up(ctx)
    try:
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
    #   <newline padding — the patchable region>
    #   # __SORTEROS_CFG_END__
    #
    # The padding goes BETWEEN the markers so the browser-side patcher
    # (sorteros-setup) has the full (total - overhead) bytes of capacity.
    # ext4 metadata doesn't move because total file size is fixed.
    header = f"# {CFG_START_MARKER}\n"
    footer = f"# {CFG_END_MARKER}\n"
    overhead = len(header.encode()) + len(footer.encode())

    if overhead > total:
        sys.exit(f"placeholder header/footer too large ({overhead} > {total})")
    payload = header + ("\n" * (total - overhead)) + footer
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
    version = ctx.config["output"]["version"]
    name = ctx.config["output"]["name"].format(date=date, version=version)
    final = ctx.out_dir / name
    if final.exists():
        final.unlink()
    ctx.work_img.rename(final)

    size = final.stat().st_size
    log(f"image ready: {final}  ({size / 1024 / 1024:.0f} MiB)")


# ─── zip ───────────────────────────────────────────────────────────────────

def phase_zip(ctx: BuildCtx) -> None:
    imgs = sorted(ctx.out_dir.glob("sorteros-v*.img"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not imgs:
        sys.exit("zip phase: no .img found in out/ — run finalize first")
    img = imgs[0]
    zip_path = img.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    log(f"zipping {img.name} → {zip_path.name} ...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(img, arcname=img.name)
    raw_mb = img.stat().st_size / 1024 ** 2
    zip_mb = zip_path.stat().st_size / 1024 ** 2
    log(f"zip ready: {zip_path}  ({zip_mb:.0f} MiB, {raw_mb / zip_mb:.1f}x compression)")


# ─── orchestration ────────────────────────────────────────────────────────

PHASE_FNS = {
    "prep": phase_prep,
    "grow": phase_grow,
    "mount": phase_mount,
    "overlay": phase_overlay,
    "chroot": phase_chroot,
    "firstboot-config": phase_firstboot_config,
    "finalize": phase_finalize,
    "zip": phase_zip,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=PHASES, help="run only this phase")
    ap.add_argument("--branch", default=None, help="override branch from config.toml")
    ap.add_argument("--config", default=str(SCRIPT_DIR / "config.toml"))
    args = ap.parse_args()

    require_root()

    # Load .env from the build dir (gitignored — contains Tailscale auth key).
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

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
