#!/usr/bin/env python3
"""Check a SorterOS image before anyone flashes it.

  sudo ./check.py image out/sorteros-v4.1.0-2026-09-23.img
      What the builder must have baked in, read straight off the image.

  ./check.py boot [--expect-ref sorter/stable/v0.2.0] [--expect-default-model]
      Follows a VM started with ./boot.sh through first boot, then checks the
      running machine over HTTP (progress page, UI, backend API) and SSH.

  ./check.py wifi [--only "3 6"]
      Simulated Wi-Fi (wifi-sim.sh) in the running VM: setup-site Wi-Fi right
      and wrong, the phone joining a network while it watches, the setup
      network's fence, a router that comes back late, a cable, odd names and
      passwords, open, hidden and WPA3 networks, no address, no internet.

Exits non-zero and says which check failed. Standard library only, Python 3.10+
(the image's own Python), so it runs anywhere the image is built.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# The Orange Pi vendor image's default login; SSH is how the boot check looks
# inside the VM.
SSH_USER = "root"
SSH_PASSWORD = "orangepi"

failures: list[str] = []


def check(ok: bool, what: str, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}{f'  ({detail})' if detail and not ok else ''}")
    if not ok:
        failures.append(what)


# ─── image ────────────────────────────────────────────────────────────────────


def check_image(img: Path) -> None:
    loop = subprocess.check_output(["losetup", "--show", "-rfP", str(img)], text=True).strip()
    mnt = Path(tempfile.mkdtemp(prefix="sorteros-check-"))
    try:
        part = f"{loop}p1"
        for _ in range(50):
            if Path(part).exists():
                break
            time.sleep(0.1)
        dumpe2fs = subprocess.run(["dumpe2fs", "-h", part], capture_output=True, text=True).stdout
        subprocess.run(["mount", "-o", "ro", part, str(mnt)], check=True)


        print("filesystem")
        opts = re.search(r"Default mount options:\s*(.*)", dumpe2fs)
        opts_s = opts.group(1) if opts else ""
        check("journal_data_ordered" in opts_s and "journal_data_writeback" not in opts_s,
              "ext4 defaults to data=ordered", opts_s)
        fstab_root = [ln for ln in (mnt / "etc/fstab").read_text().splitlines() if " / " in ln]
        check(bool(fstab_root) and "errors=panic" in fstab_root[0], "fstab root has errors=panic",
              fstab_root[0] if fstab_root else "no root line")
        env = (mnt / "boot/orangepiEnv.txt").read_text()
        extra = re.search(r"^extraargs=(.*)$", env, re.M)
        extra_s = extra.group(1) if extra else ""
        check("fsck.repair=yes" in extra_s.split(), "kernel args: fsck.repair=yes", extra_s)
        check("panic=10" in extra_s.split(), "kernel args: panic=10", extra_s)

        print("identity")
        check((mnt / "etc/hostname").read_text().strip() == "sorter", "hostname is sorter")
        check(re.search(r"^127\.0\.1\.1\s+sorter$", (mnt / "etc/hosts").read_text(), re.M) is not None,
              "/etc/hosts maps sorter")
        ref = (mnt / "etc/sorteros/ref").read_text().strip() if (mnt / "etc/sorteros/ref").exists() else ""
        check(bool(ref), "first boot ref baked", ref)
        print(f"       ref: {ref}   version: {(mnt / 'etc/sorteros/version').read_text().strip()}")

        print("services and packages")
        wants = mnt / "etc/systemd/system/multi-user.target.wants"
        for unit in ("avahi-daemon.service", "sorteros-firstboot.service", "sorteros-network.service"):
            # is_symlink: the link's absolute target only resolves inside the image
            check((wants / unit).is_symlink(), f"{unit} enabled")
        # The overlay must not hand the orangepi user (uid 1000) anything root runs.
        for rel in ("etc", "etc/systemd/system", "usr/local/sbin", "usr/local/sbin/sorteros-firstboot.py",
                    "usr/local/sbin/sorteros-network.py", "etc/systemd/system/sorteros-firstboot.service"):
            st = (mnt / rel).stat()
            check(st.st_uid == 0 and not st.st_mode & 0o022, f"/{rel} owned by root, not group/world-writable",
                  f"uid {st.st_uid} mode {oct(st.st_mode & 0o777)}")
        check("mdns" in (mnt / "etc/nsswitch.conf").read_text(), "nsswitch resolves .local")
        check(not (mnt / "usr/bin/git-lfs").exists(), "git-lfs not installed")
        check(not any((mnt / "etc/systemd/system").glob("sorter-*.service")),
              "no unconfigured sorter-*.service templates in /etc/systemd/system")
        resolv = mnt / "etc/resolv.conf"
        check(resolv.is_symlink() and str(resolv.readlink()).endswith("stub-resolv.conf"),
              "resolv.conf is the systemd-resolved stub")
        check((mnt / "var/www/portal/index.html").exists(), "setup page baked")
        check(not (mnt / "usr/local/sbin/sorteros-portal.py").exists(), "no old setup page server")
        conn = mnt / "etc/NetworkManager/conf.d/20-sorteros-connectivity.conf"
        check(conn.exists() and "uri=" in conn.read_text(), "NetworkManager checks each network for internet")
        cfg = (mnt / "etc/sorteros-config.toml").read_bytes() if (mnt / "etc/sorteros-config.toml").exists() else b""
        start, end = cfg.find(b"# __SORTEROS_CFG_START__"), cfg.find(b"# __SORTEROS_CFG_END__")
        check(0 <= start < end and end - start >= 4096, "setup-site placeholder in /etc/sorteros-config.toml",
              f"{len(cfg)} bytes")
        cfg_path = mnt / "etc/sorteros-config.toml"
        check(cfg_path.exists() and cfg_path.stat().st_mode & 0o077 == 0,
              "setup config is root-only (it will hold the Wi-Fi password)")
        dhd = mnt / "lib/firmware/ap6275p/config.txt"
        check(dhd.exists() and "\nccode=XZ\n" in dhd.read_text(errors="replace"),
              "Wi-Fi country starts worldwide (XZ), not the vendor's CN")
        localtime = mnt / "etc/localtime"
        check(localtime.is_symlink() and str(localtime.readlink()).endswith("/Etc/UTC"),
              "time zone starts at UTC, not the vendor's Asia/Shanghai")
        check(not any((mnt / "usr/local/sbin").rglob("__pycache__")), "no compiled Python in the overlay")
        daemon = mnt / "usr/local/sbin/sorteros-firstboot.py"
        try:
            compile(daemon.read_text(), str(daemon), "exec")
            compiled = True
        except SyntaxError:
            compiled = False
        check(compiled, "firstboot daemon compiles")
    finally:
        subprocess.run(["umount", str(mnt)], capture_output=True)
        subprocess.run(["losetup", "-d", loop], capture_output=True)
        mnt.rmdir()


# ─── boot ─────────────────────────────────────────────────────────────────────


def get(url: str, timeout: float = 10) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return 0, ""


def ssh(port: int, cmd: str) -> tuple[int, str]:
    # OpenSSH's own askpass hook feeds the password (no sshpass needed).
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write(f"#!/bin/sh\necho '{SSH_PASSWORD}'\n")
    askpass = Path(f.name)
    askpass.chmod(0o700)
    env = {**os.environ, "SSH_ASKPASS": str(askpass), "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": ":0"}
    try:
        r = subprocess.run(
            ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
             "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=10", "-o", "PreferredAuthentications=password",
             f"{SSH_USER}@localhost", cmd],
            capture_output=True, text=True, timeout=60, env=env, stdin=subprocess.DEVNULL,
        )
    finally:
        askpass.unlink()
    return r.returncode, (r.stdout + r.stderr).strip()


def first_boot_status(http: str) -> dict | None:
    """The progress page's /status.json, or None once something else has port 80."""
    code, body = get(http + "/status.json")
    if code != 200:
        return None
    try:
        status = json.loads(body)
    except ValueError:
        return None
    return status if isinstance(status, dict) and "stages" in status else None


def follow_first_boot(http: str, timeout_s: int) -> bool:
    """Print stage changes until the UI replaces the progress page."""
    print(f"following first boot at {http} (up to {timeout_s // 60} min)")
    deadline = time.time() + timeout_s
    seen: dict[str, tuple[str, str]] = {}
    phase = None
    status_seen = False
    while time.time() < deadline:
        status = first_boot_status(http)
        if status is not None:
            status_seen = True
            if status.get("phase") != phase:
                phase = status.get("phase")
                print(f"  {time.strftime('%H:%M:%S')}  -- {phase}")
            for st in status["stages"]:
                if seen.get(st["name"]) != (st["state"], st["info"]):
                    seen[st["name"]] = (st["state"], st["info"])
                    print(f"  {time.strftime('%H:%M:%S')}  {st['name']:20s} {st['state']:8s} {st['info']}")
        elif status_seen and get(http + "/")[0] == 200:
            print(f"  {time.strftime('%H:%M:%S')}  the Sorter UI has port 80")
            return True
        time.sleep(5)
    return False


def check_boot(args: argparse.Namespace) -> None:
    http = f"http://localhost:{args.http_port}"
    api = f"http://localhost:{args.api_port}"
    handed_over = follow_first_boot(http, args.timeout * 60)
    check(handed_over, "first boot hands port 80 to the Sorter UI")
    if handed_over:
        # The page keeps port 80 until the backend answers, so the UI it
        # opens has a machine to show.
        code, _ = get(api + "/health", timeout=5)
        check(code == 200, "the backend answers when the UI takes port 80", f"HTTP {code}")
    if failures:
        return

    print("backend")
    code, body = 0, ""
    for _ in range(40):
        code, body = get(api + "/api/system/versions?refresh=false", timeout=20)
        if code == 200:
            break
        time.sleep(15)
    check(code == 200, "backend API answers", f"HTTP {code}")
    if code == 200:
        current = json.loads(body).get("current", {})
        ref = current.get("ref") or current.get("describe") or ""
        want = args.expect_ref
        check(ref == want if want else ref.startswith("sorter/stable/v"),
              f"checked out {want or 'the newest sorter/stable/v* tag'}", ref)

    if args.expect_default_model:
        print("default model")
        installed: list[dict] = []
        items: list[dict] = []
        for _ in range(60):
            _, body = get(api + "/api/hive/models/installed")
            installed = (json.loads(body or "{}").get("items") or []) if body.startswith("{") else []
            _, body = get(api + "/api/hive/models/active-assignments")
            items = (json.loads(body or "{}").get("items") or []) if body.startswith("{") else []
            if installed and items and all((i.get("algorithm_id") or "").startswith("hive:") for i in items):
                break
            time.sleep(20)
        check(bool(installed), "a model was installed from Hive",
              f"{len(installed)} installed")
        for it in items:
            check((it.get("algorithm_id") or "").startswith("hive:"),
                  f"{it.get('label')} uses a Hive model", str(it.get("algorithm_id")))

    print("inside the machine")
    rc, out = ssh(args.ssh_port, "hostname; systemctl is-active avahi-daemon; "
                  "test -d /home/orangepi/sorter-v2/software/sorter/backend/bundled_models && echo BUNDLED; "
                  "command -v git-lfs || true; ls /var/lib/sorteros/")
    lines = out.splitlines()
    check(rc == 0 and lines[:1] == ["sorter"], "hostname is sorter", out)
    check("active" in lines[1:2], "avahi-daemon is running", out)
    check("BUNDLED" not in lines, "no models committed in the checkout")
    check(not any("git-lfs" in ln for ln in lines), "git-lfs absent")
    check(not any(ln.endswith(".failed") for ln in lines), "no first-boot stage gave up", out)


def check_wifi(args: argparse.Namespace) -> None:
    """Run wifi-sim.sh inside the VM and relay its PASS/FAIL lines."""
    script = Path(__file__).with_name("wifi-sim.sh")
    rc, out = ssh(args.ssh_port, f"cat > /tmp/wifi-sim.sh <<'SCRIPT'\n{script.read_text()}SCRIPT\n"
                                 f"ONLY='{args.only}' nohup bash /tmp/wifi-sim.sh > /tmp/wifi-sim.log 2>&1 < /dev/null & echo started")
    check(rc == 0 and "started" in out, "wifi-sim started in the VM", out)
    if failures:
        return
    shown = 0
    deadline = time.time() + args.timeout * 60
    while time.time() < deadline:
        time.sleep(20)
        rc, out = ssh(args.ssh_port, "cat /tmp/wifi-sim.log")
        lines = out.splitlines()
        for line in lines[shown:]:
            print(f"  {line}")
            if line.startswith("FAIL"):
                failures.append(line[5:])
        shown = len(lines)
        if any(line.startswith("DONE") for line in lines):
            return
    check(False, "wifi-sim finished in time")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="what", required=True)
    p_img = sub.add_parser("image")
    p_img.add_argument("img", type=Path)
    p_boot = sub.add_parser("boot")
    p_boot.add_argument("--http-port", type=int, default=8080)
    p_boot.add_argument("--api-port", type=int, default=8000)
    p_boot.add_argument("--ssh-port", type=int, default=2222)
    p_boot.add_argument("--timeout", type=int, default=240, help="minutes to wait for first boot")
    p_boot.add_argument("--expect-ref", default="", help="exact ref first boot must check out")
    p_boot.add_argument("--expect-default-model", action="store_true",
                        help="require Hive's default model on every channel")
    p_wifi = sub.add_parser("wifi", help="simulated Wi-Fi scenarios inside a running VM (wifi-sim.sh)")
    p_wifi.add_argument("--ssh-port", type=int, default=2222)
    p_wifi.add_argument("--timeout", type=int, default=40, help="minutes")
    p_wifi.add_argument("--only", default="", help='scenario numbers to run, e.g. "3 6" (default: all)')
    args = ap.parse_args()

    if args.what == "image":
        check_image(args.img)
    elif args.what == "wifi":
        check_wifi(args)
    else:
        check_boot(args)
    print(f"\n{len(failures)} failed" if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
