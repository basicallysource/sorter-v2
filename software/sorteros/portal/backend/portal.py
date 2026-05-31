"""SorterOS captive-portal backend.

Runs on the Orange Pi in AP mode (10.42.0.1:80) and answers two kinds of
requests:

  - The Wi-Fi onboarding API (/api/status, /api/wifi-scan, /api/wifi-connect)
    used by the Svelte portal frontend.
  - Captive-portal probes from iOS, Android, Windows and Firefox — we 302
    every unknown request to / so the OS pops a browser tab automatically
    when the user joins the AP.

Three modes:

  --mode=ap     Production AP mode on the device. nmcli scans the radio,
                writes a Client connection on submit, then drops the AP
                profile after a short delay so the Pi reboots into STA mode.
  --mode=mock   No nmcli calls at all. Returns a canned network list and
                accepts any submit. Good for local frontend dev.
  --mode=auto   nmcli if it's on PATH and the binary works, else mock.
                Sensible default for the systemd unit on real hardware.

Single file on purpose — gets dropped into the image overlay as
/usr/local/sbin/sorteros-portal.py and runs under the existing Python 3.11
base. No extra apt packages beyond what firstboot already pulls (fastapi,
uvicorn — already in the sorter backend's pyproject and reused here).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


log = logging.getLogger("sorteros-portal")

# ─── config & constants ────────────────────────────────────────────────────

AP_CON_NAME = "sorteros-ap"
AP_IFACE = "wlan0"
WIFI_CONFIGURED_FLAG = Path("/var/lib/sorteros/wifi-configured")
CONFIG_TOML = Path("/etc/sorteros-config.toml")
# Handoff to firstboot's re-announce: the portal does the fast first
# announce, then persists the rendezvous here so sorteros-firstboot keeps
# re-posting the (possibly changed) LAN IP for a bounded window — covering a
# failed first announce, a late-opened lookup page, or a DHCP renewal.
ANNOUNCE_STATE_FILE = Path("/var/lib/sorteros/ip-announce.json")
PORTAL_HOST = "0.0.0.0"
PORTAL_PORT = 80
AP_TEARDOWN_DELAY_S = 5.0

# A connection-attempt window — after the user submits credentials we keep
# the AP alive for this long while the Pi tries to associate with the
# requested SSID. Long enough for DHCP + IPv4, short enough that a typo'd
# password fails back into AP mode without the user wandering off.
CONNECT_TIMEOUT_S = 30.0

# Where the encrypted LAN-IP rendezvous lives. The browser carries the
# matching private key; Hive only ever stores opaque ciphertext. The portal
# only persists the rendezvous id + hive url; sorteros-firstboot does the
# actual announce (it fetches the browser's public key from Hive and encrypts
# the LAN IP with it), because the pubkey isn't on Hive until the user opens
# the lookup page — long after this portal process is gone.
DEFAULT_HIVE_URL = "https://hive.basically.website"

# Mock data — only used in --mode=mock.
MOCK_NETWORKS = [
    {"ssid": "WohnzimmerWLAN", "signal": 92, "security": "WPA2", "in_use": False},
    {"ssid": "Coffee_Shop_Guest", "signal": 71, "security": "WPA2", "in_use": False},
    {"ssid": "FRITZ!Box 7590", "signal": 64, "security": "WPA3", "in_use": False},
    {"ssid": "Open Network", "signal": 48, "security": "", "in_use": False},
    {"ssid": "weak-uplink", "signal": 22, "security": "WPA2", "in_use": False},
]


# ─── nmcli helpers ─────────────────────────────────────────────────────────

class NMCliError(RuntimeError):
    pass


def _nmcli_available() -> bool:
    return shutil.which("nmcli") is not None


def _run(cmd: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    log.info("$ %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _nmcli_scan(rescan: bool = True) -> list[dict[str, Any]]:
    rescan_flag = "yes" if rescan else "no"
    r = _run(
        ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
         "--rescan", rescan_flag],
        timeout=20.0,
    )
    if r.returncode != 0:
        raise NMCliError(f"wifi scan failed: {r.stderr.strip()}")

    networks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in r.stdout.splitlines():
        # Terse format separates with ':'. SSID can itself contain colons —
        # nmcli escapes them as '\:'. Replace, split, unreplace.
        parts = line.replace(r"\:", "\x00").split(":")
        if len(parts) < 4:
            continue
        in_use_raw, ssid_raw, signal_raw, security_raw = parts[:4]
        ssid = ssid_raw.replace("\x00", ":").strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        try:
            signal = int(signal_raw)
        except ValueError:
            signal = 0
        networks.append({
            "ssid": ssid,
            "signal": signal,
            "security": security_raw.strip() or "",
            "in_use": in_use_raw.strip() == "*",
        })

    networks.sort(key=lambda n: n["signal"], reverse=True)
    return networks


def _nmcli_write_wifi(ssid: str, password: str, hidden: bool = False) -> None:
    """Write a NetworkManager connection file the same way firstboot does."""
    body = (
        "[connection]\n"
        f"id={ssid}\n"
        "type=wifi\n"
        "autoconnect=true\n"
        "\n"
        "[wifi]\n"
        f"ssid={ssid}\n"
        "mode=infrastructure\n"
    )
    if hidden:
        body += "hidden=true\n"
    if password:
        body += (
            "\n[wifi-security]\n"
            "key-mgmt=wpa-psk\n"
            f"psk={password}\n"
        )
    body += (
        "\n[ipv4]\n"
        "method=auto\n"
        "\n[ipv6]\n"
        "method=auto\n"
    )
    target = Path("/etc/NetworkManager/system-connections") / f"{ssid}.nmconnection"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    target.chmod(0o600)

    r = _run(["nmcli", "connection", "reload"])
    if r.returncode != 0:
        raise NMCliError(f"nmcli reload failed: {r.stderr.strip()}")


def _nmcli_bring_up(ssid: str, timeout: float) -> bool:
    """Tell NetworkManager to connect. Returns True on Layer-3 success."""
    r = _run(["nmcli", "connection", "up", ssid], timeout=timeout)
    if r.returncode != 0:
        log.warning("nmcli up %s failed: %s", ssid, r.stderr.strip())
        return False
    # Quick poll — nmcli returns when the activation transaction settles but
    # IPv4 can still be coming up. Re-check state for a few seconds.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        check = _run(["nmcli", "-t", "-f", "GENERAL.STATE", "device", "show", AP_IFACE])
        if "100 (connected)" in check.stdout:
            return True
        time.sleep(0.5)
    return False


def _nmcli_teardown_ap() -> None:
    r = _run(["nmcli", "connection", "down", AP_CON_NAME])
    if r.returncode != 0:
        log.warning("ap teardown returned %d: %s", r.returncode, r.stderr.strip())


# ─── IP-announce handoff to firstboot ──────────────────────────────────────

def _write_announce_state(state: "PortalState", rendezvous_id: str) -> None:
    """Persist the rendezvous so sorteros-firstboot can announce the LAN IP.

    Only the id + hive url — no key material. firstboot fetches the browser's
    public key from Hive and does the encrypting. Best-effort write."""
    try:
        ANNOUNCE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ANNOUNCE_STATE_FILE.write_text(json.dumps({
            "rendezvous_id": rendezvous_id,
            "hive_url": state.hive_url,
            "created_at": time.time(),
        }))
    except OSError as e:
        log.warning("could not persist ip-announce state: %s", e)


# ─── hostname & lego-name ──────────────────────────────────────────────────

def _hostname() -> str:
    name = socket.gethostname() or "sorter"
    # Strip a trailing .local that some systems (notably macOS dev hosts)
    # bake into gethostname — we always append our own .local for mDNS.
    if name.endswith(".local"):
        name = name[: -len(".local")]
    return name or "sorter"


def _suggested_url() -> str:
    """Best-guess URL the user should hit once Wi-Fi is up."""
    return f"http://{_hostname()}.local/"


# ─── config persistence ────────────────────────────────────────────────────

def _write_config_toml(*, hostname: str | None, ssh_key: str | None) -> None:
    """Mirror the format firstboot's stage_apply_config_toml expects.

    Only writes keys the user actually provided; the file becomes the
    single source of truth for what the portal collected.
    """
    if not hostname and not ssh_key:
        return
    lines = ["# Written by sorteros-portal during AP onboarding.\n"]
    if hostname:
        lines.append(f'hostname = "{hostname.strip()}"\n')
    if ssh_key:
        lines.append("\n[ssh]\n")
        escaped = ssh_key.strip().replace('"', '\\"')
        lines.append(f'authorized_key = "{escaped}"\n')
    CONFIG_TOML.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_TOML.write_text("".join(lines))


def _mark_configured() -> None:
    WIFI_CONFIGURED_FLAG.parent.mkdir(parents=True, exist_ok=True)
    WIFI_CONFIGURED_FLAG.touch()


# ─── app ──────────────────────────────────────────────────────────────────


@dataclass
class PortalState:
    mode: str  # "ap" | "mock"
    static_dir: Path | None
    hive_url: str = DEFAULT_HIVE_URL
    last_attempt: dict[str, Any] | None = None


def _validate_ssid(ssid: str) -> str:
    ssid = ssid.strip()
    if not ssid:
        raise HTTPException(status_code=400, detail="ssid required")
    # IEEE 802.11 caps SSID at 32 bytes UTF-8
    if len(ssid.encode("utf-8")) > 32:
        raise HTTPException(status_code=400, detail="ssid too long")
    return ssid


def _validate_password(pwd: str | None) -> str:
    if pwd is None:
        return ""
    pwd = pwd.strip("\r\n")
    if pwd and len(pwd) < 8:
        # WPA-PSK minimum length — anything shorter is a typo or
        # an open network where the field should have been blank.
        raise HTTPException(
            status_code=400,
            detail="Wi-Fi password must be at least 8 characters (or empty for open networks).",
        )
    return pwd


def _validate_hostname(hostname: str | None) -> str | None:
    if not hostname:
        return None
    h = hostname.strip().lower()
    if not h:
        return None
    if len(h) > 63:
        raise HTTPException(status_code=400, detail="hostname too long")
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", h):
        raise HTTPException(
            status_code=400,
            detail="hostname must be lowercase letters, digits and dashes only",
        )
    return h


class WifiConnectPayload(BaseModel):
    ssid: str
    password: str | None = None
    hidden: bool = False
    hostname: str | None = None
    ssh_key: str | None = Field(default=None, alias="sshKey")
    # Rendezvous: just the browser-generated id. The keypair lives on the Hive
    # lookup page (https); the Pi fetches the public key from Hive by this id.
    rendezvous_id: str | None = Field(default=None, alias="rendezvousId")

    class Config:
        populate_by_name = True


_RENDEZVOUS_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def _validate_rendezvous(rendezvous_id: str | None) -> str | None:
    """Return the id iff present and well-formed, else None. Onboarding works
    without it (the user just falls back to the .local address)."""
    if not rendezvous_id:
        return None
    if not _RENDEZVOUS_ID_RE.match(rendezvous_id):
        log.warning("ignoring malformed rendezvous id")
        return None
    return rendezvous_id


def create_app(state: PortalState) -> FastAPI:
    app = FastAPI(title="SorterOS Portal", docs_url=None, redoc_url=None)

    # ── status & wifi API ───────────────────────────────────────────────

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return {
            "mode": state.mode,
            "hostname": _hostname(),
            "suggested_url": _suggested_url(),
            "configured": WIFI_CONFIGURED_FLAG.exists(),
            "last_attempt": state.last_attempt,
        }

    @app.get("/api/wifi-scan")
    def api_wifi_scan(rescan: bool = True) -> dict[str, Any]:
        if state.mode == "mock":
            # tiny jitter so the UI feels alive between rescans
            jittered = []
            for i, net in enumerate(MOCK_NETWORKS):
                copy = dict(net)
                copy["signal"] = max(5, min(100, copy["signal"] + (int(time.time()) + i) % 5 - 2))
                jittered.append(copy)
            return {"networks": jittered, "mocked": True}

        try:
            networks = _nmcli_scan(rescan=rescan)
        except NMCliError as e:
            raise HTTPException(status_code=503, detail=str(e))
        return {"networks": networks, "mocked": False}

    @app.post("/api/wifi-connect")
    async def api_wifi_connect(payload: WifiConnectPayload) -> dict[str, Any]:
        ssid = _validate_ssid(payload.ssid)
        password = _validate_password(payload.password)
        hostname = _validate_hostname(payload.hostname)
        ssh_key = (payload.ssh_key or "").strip() or None
        rendezvous = _validate_rendezvous(payload.rendezvous_id)

        attempt: dict[str, Any] = {
            "ssid": ssid,
            "hostname": hostname,
            "rendezvous": bool(rendezvous),
            "started_at": time.time(),
            "result": "pending",
        }
        state.last_attempt = attempt

        if state.mode == "mock":
            # Pretend everything worked.
            await asyncio.sleep(0.5)
            attempt["result"] = "ok"
            attempt["next_url"] = _suggested_url()
            if rendezvous:
                log.info("mock: firstboot would announce LAN IP to %s (id=%s)", state.hive_url, rendezvous)
            return {
                "ok": True,
                "next_url": _suggested_url(),
                "hostname": hostname or _hostname(),
                "mocked": True,
            }

        # Real device path. Write the connection profile, then schedule the
        # actual association+AP teardown in the background so the HTTP
        # response can land before we kill the AP out from under the
        # client.
        try:
            _nmcli_write_wifi(ssid, password, hidden=payload.hidden)
            _write_config_toml(hostname=hostname, ssh_key=ssh_key)
        except NMCliError as e:
            attempt["result"] = "error"
            attempt["error"] = str(e)
            raise HTTPException(status_code=503, detail=str(e))

        if rendezvous:
            # Persist before switchover so firstboot can announce the LAN IP
            # even if the portal crashes mid-connect.
            _write_announce_state(state, rendezvous)

        asyncio.get_event_loop().create_task(
            _delayed_switchover(state, ssid),
        )
        return {
            "ok": True,
            "next_url": _suggested_url(),
            "hostname": hostname or _hostname(),
            "teardown_in_s": AP_TEARDOWN_DELAY_S,
            "mocked": False,
        }

    # ── captive-portal probe endpoints ──────────────────────────────────

    # iOS / macOS — strongest UX. Apple's CNA only pops the browser sheet
    # when the response does NOT contain the literal string "Success" in a
    # tiny HTML body. Anything else (302 or non-matching 200) opens the
    # portal sheet.
    @app.get("/hotspot-detect.html")
    @app.get("/library/test/success.html")
    def apple_probe() -> RedirectResponse:
        return RedirectResponse(url="/", status_code=302)

    # Android — expects HTTP 204. 302 is interpreted as "captive portal".
    @app.get("/generate_204")
    @app.get("/gen_204")
    def android_probe() -> RedirectResponse:
        return RedirectResponse(url="/", status_code=302)

    # Windows — expects "Microsoft Connect Test". 302 is treated as captive.
    @app.get("/connecttest.txt")
    @app.get("/ncsi.txt")
    def windows_probe() -> RedirectResponse:
        return RedirectResponse(url="/", status_code=302)

    # Firefox — looks for "success" in the body.
    @app.get("/canonical.html")
    def firefox_probe() -> RedirectResponse:
        return RedirectResponse(url="/", status_code=302)

    # ── static frontend ─────────────────────────────────────────────────

    if state.static_dir and state.static_dir.exists():
        index = state.static_dir / "index.html"
        app.mount("/_app", StaticFiles(directory=state.static_dir / "_app"), name="app")

        def _spa() -> HTMLResponse:
            # SPA shell (ssr=false): the client router renders the right route
            # from the URL, so the same index.html serves / and /setup.
            if index.exists():
                return HTMLResponse(index.read_text("utf-8"))
            return HTMLResponse(_fallback_index())

        @app.get("/", response_class=HTMLResponse)
        def root() -> HTMLResponse:
            return _spa()

        # The captive landing (/) sends users here in a real browser; serve the
        # SPA so /setup loads its own route instead of getting probe-302'd.
        @app.get("/setup", response_class=HTMLResponse)
        def setup_page() -> HTMLResponse:
            return _spa()
    else:
        @app.get("/", response_class=HTMLResponse)
        def root_fallback() -> HTMLResponse:
            return HTMLResponse(_fallback_index())

    # ── catch-all: any other URL the captive-portal probe might hit gets
    # redirected to /. This is what triggers the OS captive-portal sheet
    # for vendors we don't have a named route for.
    @app.get("/{rest_of_path:path}", include_in_schema=False, response_model=None)
    def catch_all(request: Request, rest_of_path: str):
        # API and static routes already matched above; if we get here it's
        # a stray probe URL.
        if rest_of_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="unknown api route")
        return RedirectResponse(url="/", status_code=302)

    return app


def _fallback_index() -> str:
    """Inline minimal HTML used when no built frontend is mounted yet."""
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>SorterOS Setup</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e5e5;
       margin:0;padding:2rem;line-height:1.5;max-width:32rem;margin:0 auto}
  h1{font-size:1.4rem;margin:0 0 .25rem}
  .sub{color:#888;margin-bottom:1.5rem}
  code{background:#1a1a1a;padding:.1rem .35rem}
</style></head><body>
<h1>SorterOS Setup</h1>
<div class="sub">Portal backend is running but the frontend bundle wasn't found.</div>
<p>Drop the built frontend into <code>/var/www/portal/</code> (or pass
<code>--static-dir</code>) and reload this page.</p>
<p>Mock API is live: try
<code><a href="/api/wifi-scan" style="color:#60a5fa">/api/wifi-scan</a></code>.</p>
</body></html>"""


# ─── switchover background task ────────────────────────────────────────────

async def _delayed_switchover(state: PortalState, ssid: str) -> None:
    """Wait briefly so the HTTP response reaches the client, then bring the
    requested SSID up. On success, mark onboarding done and tear down the AP
    (firstboot announces the LAN IP from here on, using the persisted
    rendezvous). On failure, leave the AP up so the user can retry."""
    await asyncio.sleep(AP_TEARDOWN_DELAY_S)
    attempt = state.last_attempt or {}
    try:
        ok = _nmcli_bring_up(ssid, timeout=CONNECT_TIMEOUT_S)
        if ok:
            _mark_configured()
            _nmcli_teardown_ap()
            attempt["result"] = "connected"
        else:
            attempt["result"] = "associate_failed"
            log.warning("association with %s failed; AP stays up", ssid)
    except Exception:
        log.exception("switchover crashed")
        attempt["result"] = "error"
    finally:
        state.last_attempt = attempt


# ─── entrypoint ────────────────────────────────────────────────────────────


def _resolve_mode(arg: str) -> str:
    if arg == "ap":
        return "ap"
    if arg == "mock":
        return "mock"
    return "ap" if _nmcli_available() else "mock"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--mode", choices=("auto", "ap", "mock"), default="auto",
                        help="auto picks ap if nmcli is on PATH, else mock")
    parser.add_argument("--port", type=int, default=PORTAL_PORT)
    parser.add_argument("--host", default=PORTAL_HOST)
    parser.add_argument("--static-dir",
                        default="/var/www/portal",
                        help="directory holding the built SvelteKit static output")
    parser.add_argument("--hive-url", default=DEFAULT_HIVE_URL,
                        help="base URL of the Hive instance to announce the LAN IP to")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mode = _resolve_mode(args.mode)
    static = Path(args.static_dir)
    state = PortalState(
        mode=mode,
        static_dir=static if static.exists() else None,
        hive_url=args.hive_url,
    )
    app = create_app(state)

    log.info("starting portal — mode=%s static_dir=%s hive=%s listen=%s:%d",
             mode, state.static_dir, state.hive_url, args.host, args.port)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
