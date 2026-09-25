"""
SorterOS image builder.

Runs as root on Linux: natively on arm64, or on x86_64 with qemu-user-static
registered for aarch64 so the chroot step can run arm64 binaries. Builds a
bootable Orange Pi 5 .img from the vendor base image: the overlay, a minimal
apt delta, and the filesystem/boot settings a headless appliance needs. No
partition surgery, no FAT. Single ext4.

Phases (run with --phase <name> for a partial rerun):
  prep              — fetch base img if missing, copy to working file
  grow              — grow the .img by GROW_MIB before mount
  mount             — loop-mount the ext4 partition
  overlay           — rsync overlay/ into the rootfs
  portal            — build + bake the SorterOS captive portal (../portal/)
  chroot            — run chroot_apt.sh inside the rootfs
  finalize          — unmount, rename, report
  zip               — compress .img → .img.zip for GitHub Releases distribution

Default with no --phase: prep through finalize, in order. zip is only for a
release: --phase zip.

--from <image> respins a previous SorterOS build instead of starting from the
vendor image: prep copies it, then mount, overlay, portal and finalize run
(grow and chroot are skipped). A minute or two instead of ~10, for a test image
when only overlay/, the portal or --ref changed. The overlay is copied over
what's there, so a file deleted from overlay/ stays; release builds start from
the vendor image. Each phase is idempotent on its own — re-running a
single phase won't break the overall state.
"""

from __future__ import annotations

import argparse
import importlib.util
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PORTAL_DIR = SCRIPT_DIR.parent / "portal"
PHASES = ["prep", "grow", "mount", "overlay", "portal", "chroot", "finalize", "zip"]

# Bytes of free space to add to the image before chroot. The Orange Pi
# base image is sized for an 8 GB SD card but only ~2.5 GB is free
# inside the ext4; node22 + tailscale fill it.
# Grow by GROW_MIB before mounting; the rootfs will be GROW_MIB / 1024 GiB
# larger than vendor. First-boot growfs on the Pi expands further to fill
# whatever real SD card it's flashed to.
GROW_MIB = 4096

@dataclass
class BuildCtx:
    config: dict
    work_img: Path
    cache_dir: Path
    overlay_dir: Path
    mnt: Path
    out_dir: Path
    state_file: Path
    ref: str
    from_image: Path | None = None


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


def _losetup_attach(img: Path) -> str:
    """losetup --show -fP + wait for /dev/loopNp1 to appear.

    In bare-metal Linux + udev the partition device shows up immediately.
    In privileged Docker containers (e.g. OrbStack with /dev bind-mounted),
    the host udev creates the node asynchronously — we have to wait briefly
    or the next step races and sees no p1.
    """
    loop = subprocess.check_output(
        ["losetup", "--show", "-fP", str(img)], text=True
    ).strip()
    # Prefer udevadm settle if available (idempotent, blocks until done).
    subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)
    # Fallback poll: some containers have no udev at all, partitions appear
    # when devtmpfs propagates from the host.
    part = Path(f"{loop}p1")
    for _ in range(50):
        if part.exists():
            break
        time.sleep(0.1)
    return loop


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
    """$SORTEROS_BASE_IMG if set, else cache/<filename> in this build dir.
    Verified against [base].sha256 so a truncated download can't become an
    image."""
    filename = ctx.config["base"]["filename"]
    env = os.environ.get("SORTEROS_BASE_IMG")
    base = Path(env) if env else ctx.cache_dir / filename
    if not base.exists():
        sys.exit(
            f"base image not found at {base}.\n"
            f"Download {filename} ({ctx.config['base']['url']}) into {ctx.cache_dir}/ "
            "or set SORTEROS_BASE_IMG=<path>."
        )
    want = ctx.config["base"].get("sha256", "")
    if want:
        log(f"verifying sha256 of {base.name}")
        h = hashlib.sha256()
        with base.open("rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            sys.exit(f"{base} sha256 {h.hexdigest()} != expected {want}")
    return base


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

    base = ctx.from_image or _find_base_image(ctx)
    if not base.exists():
        sys.exit(f"{base} not found")
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
    loop = _losetup_attach(ctx.work_img)
    try:
        # Grow partition 1 to fill the new space.
        run(["growpart", loop, "1"])
        # Detach + reattach so the kernel rescans the (now larger) partition.
        run(["losetup", "-d", loop])
        loop = _losetup_attach(ctx.work_img)
        part = f"{loop}p1"
        # e2fsck before resize2fs (refuses unclean fs)
        p = subprocess.run(["e2fsck", "-fy", part])
        if p.returncode not in (0, 1):
            sys.exit(f"e2fsck exit {p.returncode}")
        run(["resize2fs", part])
        # The vendor superblock defaults to data=writeback, under which a power
        # cut can leave garbage inside files ext4 thinks are intact; it
        # corrupted SQLite on machines in the field. data=ordered prevents
        # that. The superblock setting applies whatever fstab says.
        run(["tune2fs", "-o", "^journal_data_writeback,journal_data_ordered", part])
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
    loop = _losetup_attach(ctx.work_img)
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

    # -a keeps modes and symlinks; -H hard links. Everything in the overlay is
    # system files, so it lands owned by root and never group/world-writable,
    # whoever owns the checkout (rsync -a alone copied the build user's uid,
    # which is orangepi's uid 1000 in the image, onto /etc and onto scripts
    # root runs at boot). --no-times keeps unchanged files' mtimes.
    run([
        "rsync", "-aH", "--no-times", "--chown=0:0", "--chmod=Dgo-w,Fgo-w", "--exclude=__pycache__",
        f"{ctx.overlay_dir}/", f"{ctx.mnt}/",
    ])

    # Record what firstboot checks out and the image version, so anyone who
    # SSHes in can identify the image.
    sorteros_etc = ctx.mnt / "etc" / "sorteros"
    sorteros_etc.mkdir(parents=True, exist_ok=True)
    version = ctx.config["output"]["version"]
    (sorteros_etc / "ref").write_text(ctx.ref + "\n")
    (sorteros_etc / "version").write_text(version + "\n")
    log(f"ref baked into image: {ctx.ref}")
    log(f"version baked into image: {version}")

    motd = ctx.mnt / "etc" / "motd"
    motd.write_text(f"\nSorterOS  v{version}  ({ctx.ref})\n\n")
    log("wrote /etc/motd")

    _set_hostname(ctx)
    _harden_root_fs(ctx)
    _set_wifi_country(ctx)
    _set_timezone_utc(ctx)

    # Tailscale auth key is intentionally NOT baked in at build time.
    # It is supplied at setup time via the AP captive portal (../portal/),
    # written into /etc/sorteros-config.toml, and applied by firstboot
    # stage_apply_config_toml → stage_tailscale_up.
    #
    # The key can still be baked for internal test images via the env var
    # below — useful when you don't want to walk through the portal flow
    # on every test boot.
    ts_key = os.environ.get("SORTEROS_BAKE_TAILSCALE_AUTH_KEY", "")
    ts_tags = os.environ.get("TAILSCALE_TAGS", "tag:sorter")
    if ts_key:
        ts_env = sorteros_etc / "tailscale.env"
        ts_env.write_text(f"TAILSCALE_AUTH_KEY={ts_key}\nTAILSCALE_TAGS={ts_tags}\n")
        ts_env.chmod(0o600)
        log("baked tailscale auth key into /etc/sorteros/tailscale.env")

    # WiFi overlay is board-specific: OPi 5 onboard needs wifi-ap6275p, the
    # CM5 Tablet carrier auto-detects via the vendor image. Configurable in
    # [overlay].wifi_overlay (default "wifi-ap6275p" preserves OPi 5 behavior).
    wifi_overlay = ctx.config.get("overlay", {}).get("wifi_overlay", "wifi-ap6275p")
    env_txt = ctx.mnt / "boot" / "orangepiEnv.txt"
    if not wifi_overlay:
        log("skip wifi overlay patch ([overlay].wifi_overlay is empty)")
    elif env_txt.exists():
        content = env_txt.read_text()
        if wifi_overlay not in content:
            with env_txt.open("a") as f:
                f.write(f"\noverlays={wifi_overlay}\n")
            log(f"appended overlays={wifi_overlay} to /boot/orangepiEnv.txt")
        else:
            log(f"overlays={wifi_overlay} already present in /boot/orangepiEnv.txt")
    else:
        log("WARN: /boot/orangepiEnv.txt not found; wifi overlay not set")


HOSTNAME = "sorter"


def _set_hostname(ctx: BuildCtx) -> None:
    """Every image answers as sorter.local (avahi, installed in the chroot
    step, advertises it; a second machine on the same network becomes
    sorter-2.local). The captive portal can still set another name."""
    (ctx.mnt / "etc" / "hostname").write_text(HOSTNAME + "\n")
    hosts = ctx.mnt / "etc" / "hosts"
    lines = [
        ln for ln in hosts.read_text().splitlines()
        if not ln.startswith("127.0.1.1") and not ln.startswith("::1")
    ]
    lines[1:1] = [f"127.0.1.1   {HOSTNAME}", f"::1         localhost {HOSTNAME} ip6-localhost ip6-loopback"]
    hosts.write_text("\n".join(lines) + "\n")
    log(f"hostname: {HOSTNAME}")


def _harden_root_fs(ctx: BuildCtx) -> None:
    """A headless machine must get itself back up after a filesystem error.

    - errors=panic (fstab) + panic=10 (kernel): an ext4 error reboots the
      machine instead of leaving it half-alive on a read-only root.
    - fsck.repair=yes (kernel): the boot-time fsck repairs instead of
      dropping to an initramfs prompt nobody can type into.
    """
    fstab = ctx.mnt / "etc" / "fstab"
    content = fstab.read_text()
    if "errors=remount-ro" in content:
        fstab.write_text(content.replace("errors=remount-ro", "errors=panic"))
        log("fstab: errors=remount-ro -> errors=panic")
    elif "errors=panic" not in content:
        sys.exit("fstab has no errors= option on the root line; base image changed?")

    env_txt = ctx.mnt / "boot" / "orangepiEnv.txt"
    if not env_txt.exists():
        log("WARN: /boot/orangepiEnv.txt not found; kernel args not set")
        return
    lines = env_txt.read_text().splitlines()
    wanted = ["fsck.repair=yes", "panic=10"]
    for i, ln in enumerate(lines):
        if ln.startswith("extraargs="):
            args = ln[len("extraargs="):].split()
            lines[i] = "extraargs=" + " ".join(args + [a for a in wanted if a not in args])
            break
    else:
        lines.append("extraargs=" + " ".join(wanted))
    env_txt.write_text("\n".join(lines) + "\n")
    log(f"orangepiEnv.txt: {next(ln for ln in lines if ln.startswith('extraargs='))}")


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
        # Replace the build-host's /etc/resolv.conf with the standard
        # systemd-resolved symlink. Otherwise (e.g. when building in a
        # Docker container that has a hardcoded internal DNS like
        # 0.250.250.200) the dead nameserver gets baked into the image
        # and the first-boot stages can't resolve github.com.
        resolv_dst.unlink(missing_ok=True)
        resolv_dst.symlink_to("/run/systemd/resolve/stub-resolv.conf")


# ─── portal ───────────────────────────────────────────────────────────────

def phase_portal(ctx: BuildCtx) -> None:
    """Bake the setup page (../portal/frontend, static files) into the
    rootfs. sorteros-network serves it on the setup network."""
    if not is_mounted(ctx.mnt):
        sys.exit("rootfs not mounted — run --phase mount first")

    frontend_dir = PORTAL_DIR / "frontend"
    frontend_build = frontend_dir / "build"

    if not frontend_dir.exists():
        sys.exit(f"portal frontend missing at {frontend_dir} — repo layout broken?")

    # Build the Svelte frontend if no build/ output exists yet, or if any
    # source file is newer than the existing build manifest.
    if _portal_frontend_needs_build(frontend_dir, frontend_build):
        log("building portal frontend (pnpm install + pnpm build)")
        # Every time, not only when node_modules is missing: one installed from
        # an older lockfile builds against the wrong packages. It's a no-op
        # when they match.
        run(["pnpm", "install", "--frozen-lockfile"], cwd=str(frontend_dir))
        run(["pnpm", "build"], cwd=str(frontend_dir))
    else:
        log("portal frontend build/ up to date — skipping pnpm")

    # An image respun from an older one still has the old setup page server.
    (ctx.mnt / "usr" / "local" / "sbin" / "sorteros-portal.py").unlink(missing_ok=True)

    # Frontend bundle → /var/www/portal
    www_dst = ctx.mnt / "var" / "www" / "portal"
    if www_dst.exists():
        shutil.rmtree(www_dst)
    www_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(frontend_build, www_dst)
    log(f"copied portal frontend → {www_dst.relative_to(ctx.mnt)}")

    _write_config_placeholder(ctx)


# The setup site (sorteros-setup, setup.basically.website) finds these two
# comment lines in the raw .img and overwrites the newline padding between
# them with the user's settings (Wi-Fi, hostname, SSH key, Tailscale key),
# keeping the file's size so no ext4 metadata moves. firstboot and
# sorteros-network read the file up to the end marker. Split so this source
# doesn't contain the literal lines the site searches for.
CFG_START_MARKER = "# __SORTEROS_CFG" + "_START__\n"
CFG_END_MARKER = "# __SORTEROS_CFG" + "_END__\n"
CFG_PLACEHOLDER_BYTES = 8192


def _set_timezone_utc(ctx: BuildCtx) -> None:
    """The vendor image is on Asia/Shanghai. Start at UTC; first boot moves to
    the owner's time zone once the setup site or page has passed it on."""
    localtime = ctx.mnt / "etc" / "localtime"
    localtime.unlink(missing_ok=True)
    localtime.symlink_to("/usr/share/zoneinfo/Etc/UTC")
    (ctx.mnt / "etc" / "timezone").write_text("Etc/UTC\n")
    log("time zone: Etc/UTC")


def _set_wifi_country(ctx: BuildCtx) -> None:
    """The vendor image leaves the Orange Pi 5's Wi-Fi on CN, which hides 5 GHz
    channels 100-144. Start at XZ, Broadcom's worldwide setting; sorteros-network
    moves it to the owner's country once it knows their time zone."""
    spec = importlib.util.spec_from_file_location(
        "sorteros_network", SCRIPT_DIR / "overlay/usr/local/sbin/sorteros-network.py")
    net = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(net)
    config = ctx.mnt / net.DHD_CONFIG.relative_to("/")
    if not config.exists():
        log(f"no {net.DHD_CONFIG} in this image: Wi-Fi country left alone")
        return
    config.write_text(net.with_country(config.read_text(errors="replace"), net.WORLD_COUNTRY))
    log(f"Wi-Fi country: {net.WORLD_COUNTRY} in {net.DHD_CONFIG}")


def _write_config_placeholder(ctx: BuildCtx) -> None:
    padding = CFG_PLACEHOLDER_BYTES - len(CFG_START_MARKER) - len(CFG_END_MARKER)
    cfg = ctx.mnt / "etc" / "sorteros-config.toml"
    cfg.write_text(CFG_START_MARKER + "\n" * padding + CFG_END_MARKER)
    os.chmod(cfg, 0o600)  # the setup site puts the Wi-Fi password and Tailscale key here
    log(f"wrote the setup-site placeholder: {cfg.relative_to(ctx.mnt)} ({padding} bytes of room)")


def _portal_frontend_needs_build(src_dir: Path, build_dir: Path) -> bool:
    manifest = build_dir / "index.html"
    if not manifest.exists():
        return True
    build_mtime = manifest.stat().st_mtime
    for path in (src_dir / "src").rglob("*"):
        if path.is_file() and path.stat().st_mtime > build_mtime:
            return True
    for cfg in ("svelte.config.js", "vite.config.ts", "package.json"):
        p = src_dir / cfg
        if p.exists() and p.stat().st_mtime > build_mtime:
            return True
    return False


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
    "portal": phase_portal,
    "chroot": phase_chroot,
    "finalize": phase_finalize,
    "zip": phase_zip,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=PHASES, help="run only this phase")
    ap.add_argument(
        "--ref", default=None,
        help="what firstboot checks out: 'stable' (the default in config.toml), or a branch/tag/commit for a test image",
    )
    ap.add_argument("--config", default=str(SCRIPT_DIR / "config.toml"))
    ap.add_argument(
        "--from", dest="from_image", type=Path, default=None,
        help="respin this previous SorterOS image (skips grow and chroot); test images only",
    )
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

    ref = args.ref or config["source"]["ref"]

    ctx = BuildCtx(
        config=config,
        work_img=SCRIPT_DIR / "out" / "work.img",
        cache_dir=SCRIPT_DIR / "cache",
        overlay_dir=SCRIPT_DIR / "overlay",
        mnt=Path("/mnt/sorteros-build"),
        out_dir=SCRIPT_DIR / "out",
        state_file=SCRIPT_DIR / "out" / ".build-state.json",
        ref=ref,
        from_image=args.from_image,
    )

    if args.phase:
        phases = [args.phase]
    elif args.from_image:
        phases = ["prep", "mount", "overlay", "portal", "finalize"]
    else:
        phases = PHASES[:PHASES.index("zip")]
    for p in phases:
        log(f"=== phase: {p} ===")
        PHASE_FNS[p](ctx)
    log("done.")


if __name__ == "__main__":
    main()
