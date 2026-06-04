"""
v3 SorterOS image builder.

Runs inside a Linux environment (a colima VM on the Mac, or any Linux box).
Builds a bootable Orange Pi 5 .img with the v3 overlay applied and a
minimal apt delta. No partition surgery, no FAT, no qemu. Single ext4.

Phases (run with --phase <name> for a partial rerun):
  fetch-base        — download/decompress/checksum the configured base image
  prep              — fetch base img if missing, copy to working file
  grow              — grow the .img by GROW_MIB before mount
  mount             — loop-mount the ext4 partition
  overlay           — rsync overlay/ into the rootfs
  portal            — build + bake the SorterOS captive portal (../portal/)
  chroot            — run chroot_apt.sh inside the rootfs
  finalize          — unmount, rename, report
  zip               — compress .img → .img.zip for GitHub Releases distribution

Default with no --phase: run all of them in order. Each phase is
idempotent on its own — re-running a single phase won't break the
overall state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PORTAL_DIR = SCRIPT_DIR.parent / "portal"
PHASES = ["fetch-base", "prep", "grow", "mount", "overlay", "portal", "chroot", "finalize", "zip"]

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


def _camera_transport_contract(ctx: BuildCtx) -> dict | None:
    section = ctx.config.get("camera_transport")
    if not isinstance(section, dict):
        return None
    return {
        "schema_version": 1,
        "image_version": ctx.config["output"]["version"],
        "branch": ctx.branch,
        "profile": section.get("profile", "rk3588-rockchip-mpp-h264-webrtc"),
        "description": section.get("description", ""),
        "required_kernel_release_patterns": list(
            section.get("required_kernel_release_patterns", [])
        ),
        "required_machine": section.get("required_machine"),
        "required_runtime_gates": list(section.get("required_runtime_gates", [])),
        "required_device_nodes": list(section.get("required_device_nodes", [])),
        "required_packages": list(section.get("required_packages", [])),
        "backend_env": dict(section.get("backend_env", {})),
        "probe_command": section.get(
            "probe_command",
            (
                "cd /home/orangepi/sorter-v2/software/sorter/backend && "
                ".venv/bin/python scripts/probe_camera_transport_stack.py"
            ),
        ),
        "acceptance_probe_commands": list(section.get("acceptance_probe_commands", [])),
    }


def is_mounted(path: Path) -> bool:
    try:
        return subprocess.run(["mountpoint", "-q", str(path)]).returncode == 0
    except FileNotFoundError:
        # mountpoint not available — fallback to /proc/mounts grep
        return any(str(path) in ln for ln in Path("/proc/mounts").read_text().splitlines())


def _root_partition_number(ctx: BuildCtx) -> int:
    return int(ctx.config.get("base", {}).get("root_partition", 1))


def _loop_partition(loop: str, partition: int) -> str:
    return f"{loop}p{partition}"


def _losetup_attach(img: Path, *, wait_partition: int = 1) -> str:
    """losetup --show -fP + wait for /dev/loopNpN to appear.

    In bare-metal Linux + udev the partition device shows up immediately.
    In privileged Docker containers (e.g. OrbStack with /dev bind-mounted),
    the host udev creates the node asynchronously, so wait for the configured
    rootfs partition before the next step touches it.
    """
    loop = subprocess.check_output(
        ["losetup", "--show", "-fP", str(img)], text=True
    ).strip()
    if shutil.which("partprobe"):
        subprocess.run(["partprobe", loop], check=False)
    if shutil.which("partx"):
        subprocess.run(["partx", "-u", loop], check=False)
    # Prefer udevadm settle if available (idempotent, blocks until done).
    subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)
    # Fallback poll: some containers have no udev at all, partitions appear
    # when devtmpfs propagates from the host.
    part = Path(_loop_partition(loop, wait_partition))
    for _ in range(120):
        if part.exists():
            break
        time.sleep(0.1)
    if not part.exists():
        available = ", ".join(sorted(str(path) for path in Path("/dev").glob(f"{Path(loop).name}*")))
        log(f"partition node {part} did not appear after losetup; available: {available or 'none'}")
    return loop


def _root_partition_spec(img: Path, partition: int) -> tuple[int, int]:
    if not shutil.which("sfdisk"):
        sys.exit("sfdisk is required when loop partition nodes are unavailable")
    raw = subprocess.check_output(["sfdisk", "--json", str(img)], text=True)
    table = json.loads(raw)["partitiontable"]
    sector_size = int(table.get("sectorsize", 512))
    partitions = table.get("partitions", [])
    if partition < 1 or partition > len(partitions):
        sys.exit(f"image has {len(partitions)} partitions; root_partition={partition} is invalid")
    item = partitions[partition - 1]
    return int(item["start"]) * sector_size, int(item["size"]) * sector_size


def _root_partition_device(ctx: BuildCtx, disk_loop: str, img: Path) -> tuple[str, str | None]:
    partition = _root_partition_number(ctx)
    part = _loop_partition(disk_loop, partition)
    if Path(part).exists():
        return part, None

    offset, size = _root_partition_spec(img, partition)
    part_loop = subprocess.check_output(
        [
            "losetup",
            "--show",
            "-f",
            "-o",
            str(offset),
            "--sizelimit",
            str(size),
            str(img),
        ],
        text=True,
    ).strip()
    log(
        "attached root partition via offset loop "
        f"{part_loop} (p{partition}, offset={offset}, size={size})"
    )
    return part_loop, part_loop


def _detach_loop_device(loop: str | None) -> None:
    if loop and Path(loop).exists():
        subprocess.run(["losetup", "-d", loop])


# ─── prep ──────────────────────────────────────────────────────────────────

def phase_fetch_base(ctx: BuildCtx) -> None:
    ctx.cache_dir.mkdir(parents=True, exist_ok=True)
    base = _ensure_base_image(ctx)
    log(f"base image ready: {base}")


def _teardown_mnt(ctx: BuildCtx) -> None:
    """Unmount everything under ctx.mnt and detach the loop device."""
    _bind_mounts_down(ctx)
    if is_mounted(ctx.mnt):
        subprocess.run(["umount", str(ctx.mnt)])
    s = state_read(ctx)
    _detach_loop_device(s.get("partition_loop"))
    loop = s.get("loop")
    _detach_loop_device(loop)

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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_sha256(ctx: BuildCtx, path: Path) -> str:
    base_cfg = ctx.config["base"]
    if path.name.endswith(".xz"):
        return str(base_cfg.get("sha256_xz") or base_cfg.get("sha256") or "").strip()
    if base_cfg.get("sha256_img"):
        return str(base_cfg["sha256_img"]).strip()
    if str(base_cfg.get("url", "")).endswith(".xz") and base_cfg.get("sha256"):
        return ""
    return str(base_cfg.get("sha256") or "").strip()


def _verify_sha256(ctx: BuildCtx, path: Path) -> None:
    expected = _expected_sha256(ctx, path)
    if not expected:
        if path.suffix != ".partial":
            log(f"no sha256 configured for {path.name}; skipping checksum")
        return
    actual = _sha256(path)
    if actual != expected:
        sys.exit(f"sha256 mismatch for {path}: expected {expected}, got {actual}")
    log(f"sha256 verified for {path.name}")


def _download_file(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".partial")
    tmp.unlink(missing_ok=True)
    log(f"downloading {url} → {dest}")
    with urllib.request.urlopen(url) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)
    tmp.rename(dest)


def _ensure_base_image(ctx: BuildCtx) -> Path:
    """Return an uncompressed base .img, downloading/decompressing if needed."""
    try:
        base = _find_base_image(ctx)
    except SystemExit:
        base = None
    if base is not None:
        _verify_sha256(ctx, base)
        return base

    filename = ctx.config["base"]["filename"]
    img_path = ctx.cache_dir / filename
    xz_path = ctx.cache_dir / f"{filename}.xz"
    url = ctx.config["base"].get("url", "").strip()
    if not xz_path.exists() and url:
        if not (url.endswith(".img") or url.endswith(".img.xz")):
            sys.exit(
                f"[base].url is not a direct .img/.img.xz URL: {url}\n"
                f"Download the base image manually and place {filename} in {ctx.cache_dir}/, "
                "or set SORTEROS_BASE_IMG=<path>."
            )
        download_path = xz_path if url.endswith(".xz") else img_path
        _download_file(url, download_path)

    if img_path.exists():
        _verify_sha256(ctx, img_path)
        return img_path

    if xz_path.exists():
        _verify_sha256(ctx, xz_path)
        log(f"decompressing {xz_path.name} → {img_path.name}")
        run(["xz", "-dkf", str(xz_path)])
        if not img_path.exists():
            sys.exit(f"xz did not produce expected image: {img_path}")
        _verify_sha256(ctx, img_path)
        return img_path

    sys.exit(
        "base image not found and no downloadable [base].url is configured. "
        f"Set SORTEROS_BASE_IMG=<path> or drop {filename} into {ctx.cache_dir}/."
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

    base = _ensure_base_image(ctx)
    log(f"base image: {base}")
    log(f"copying base → {ctx.work_img}")
    shutil.copy2(base, ctx.work_img)


# ─── grow ──────────────────────────────────────────────────────────────────

def phase_grow(ctx: BuildCtx) -> None:
    """Grow the image file and extend the configured rootfs partition.

    Not partition surgery in the v2 sense — we keep the base image's partition
    layout, push only the configured rootfs partition end further out, and
    resize the filesystem.
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
    partition = _root_partition_number(ctx)
    loop = _losetup_attach(ctx.work_img, wait_partition=partition)
    part_loop: str | None = None
    try:
        # Grow the configured rootfs partition to fill the new space.
        run(["growpart", loop, str(partition)])
        # Detach + reattach so the kernel rescans the (now larger) partition.
        _detach_loop_device(loop)
        loop = _losetup_attach(ctx.work_img, wait_partition=partition)
        part, part_loop = _root_partition_device(ctx, loop, ctx.work_img)
        # e2fsck before resize2fs (refuses unclean fs)
        p = subprocess.run(["e2fsck", "-fy", part])
        if p.returncode not in (0, 1):
            sys.exit(f"e2fsck exit {p.returncode}")
        run(["resize2fs", part])
    finally:
        _detach_loop_device(part_loop)
        _detach_loop_device(loop)
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
    partition = _root_partition_number(ctx)
    loop = _losetup_attach(ctx.work_img, wait_partition=partition)
    state_write(ctx, loop=loop)

    part, part_loop = _root_partition_device(ctx, loop, ctx.work_img)
    state_write(ctx, partition_loop=part_loop)

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
    camera_transport_contract = _camera_transport_contract(ctx)
    if camera_transport_contract is not None:
        contract_path = sorteros_etc / "camera-transport-target.json"
        contract_path.write_text(json.dumps(camera_transport_contract, indent=2, sort_keys=True) + "\n")
        log(f"camera transport target baked into image: {camera_transport_contract['profile']}")

    # MOTD so `ssh root-pi` immediately shows the image version.
    motd = ctx.mnt / "etc" / "motd"
    motd.write_text(f"\nSorterOS  v{version}  ({ctx.branch})\n\n")
    log(f"wrote /etc/motd")

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
    """Bake the SorterOS captive-portal backend script and static frontend
    bundle into the rootfs. Portal source lives at ../portal/ and is
    reused for local development via mock mode."""
    if not is_mounted(ctx.mnt):
        sys.exit("rootfs not mounted — run --phase mount first")

    backend_src = PORTAL_DIR / "backend" / "portal.py"
    frontend_dir = PORTAL_DIR / "frontend"
    frontend_build = frontend_dir / "build"

    if not backend_src.exists():
        sys.exit(f"portal backend missing at {backend_src} — repo layout broken?")
    if not frontend_dir.exists():
        sys.exit(f"portal frontend missing at {frontend_dir} — repo layout broken?")

    # Build the Svelte frontend if no build/ output exists yet, or if any
    # source file is newer than the existing build manifest.
    if _portal_frontend_needs_build(frontend_dir, frontend_build):
        log("building portal frontend (pnpm install + pnpm build)")
        if not (frontend_dir / "node_modules").exists():
            run(["pnpm", "install", "--frozen-lockfile"], cwd=str(frontend_dir))
        run(["pnpm", "build"], cwd=str(frontend_dir))
    else:
        log(f"portal frontend build/ up to date — skipping pnpm")

    # Backend script → /usr/local/sbin/sorteros-portal.py
    backend_dst = ctx.mnt / "usr" / "local" / "sbin" / "sorteros-portal.py"
    backend_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(backend_src, backend_dst)
    os.chmod(backend_dst, 0o755)
    log(f"copied portal backend → {backend_dst.relative_to(ctx.mnt)}")

    # Frontend bundle → /var/www/portal
    www_dst = ctx.mnt / "var" / "www" / "portal"
    if www_dst.exists():
        shutil.rmtree(www_dst)
    www_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(frontend_build, www_dst)
    log(f"copied portal frontend → {www_dst.relative_to(ctx.mnt)}")

    # The portal will also need an empty /etc/sorteros-config.toml so
    # firstboot's stage_apply_config_toml has a known path to read once
    # the user completes onboarding. No markers, no placeholder — just a
    # comment so the file isn't empty.
    cfg = ctx.mnt / "etc" / "sorteros-config.toml"
    if not cfg.exists():
        cfg.write_text("# Populated by sorteros-portal during AP onboarding.\n")
        os.chmod(cfg, 0o644)
        log(f"created {cfg.relative_to(ctx.mnt)}")


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
    _detach_loop_device(s.get("partition_loop"))
    loop = s.get("loop")
    _detach_loop_device(loop)
    state_write(ctx, loop=None, partition=None, partition_loop=None)

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
    "fetch-base": phase_fetch_base,
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
    ap.add_argument("--branch", default=None, help="override branch from config.toml")
    ap.add_argument("--config", default=str(SCRIPT_DIR / "config.toml"))
    args = ap.parse_args()

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

    if args.phase != "fetch-base":
        require_root()

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
