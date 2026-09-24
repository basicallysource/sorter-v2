"""SorterOS captive-portal backend.

Runs on the Orange Pi in AP mode (10.42.0.1:80) and answers two kinds of
requests:

  - The Wi-Fi onboarding API (/api/status, /api/wifi-scan, /api/wifi-connect)
    used by the Svelte portal frontend.
  - Captive-portal probes from iOS, Android, Windows and Firefox — we 302
    every unknown request to / so the OS pops a browser tab automatically
    when the user joins the AP.

Three modes:

  --mode=ap     On the device, started by sorteros-network while the setup
                network is up. Offers the networks sorteros-network scanned
                before broadcasting; on submit it records the choice and
                restarts, and sorteros-network joins it at the next boot.
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
import os
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
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


log = logging.getLogger("sorteros-portal")

# ─── config & constants ────────────────────────────────────────────────────

AP_CON_NAME = "sorteros-ap"
CONFIG_TOML = Path("/etc/sorteros-config.toml")
# Shared with sorteros-network, which started this portal. Joining a network
# is a restart (the Orange Pi 5's Wi-Fi can't join after broadcasting until
# it restarts): the page leaves the choice in JOIN_PENDING and restarts, and
# sorteros-network saves and joins it at the next boot or reports why not in
# JOIN_FAILED. It is the only thing that writes Wi-Fi profiles. It
# scanned before broadcasting (NETWORKS), since the chip can't scan while it
# broadcasts. ACTIVITY is touched on every API request so it never restarts to
# retry saved networks while someone is using the page.
JOIN_PENDING = Path("/var/lib/sorteros/join-pending.json")
JOIN_FAILED = Path("/var/lib/sorteros/join-failed.json")
NETWORKS = Path("/run/sorteros/networks.json")
PORTAL_ACTIVITY = Path("/run/sorteros/portal-activity")
REBOOT_CMD = os.environ.get("SORTEROS_REBOOT_CMD", "systemctl reboot").split()
# Split so the setup site, which scans the raw image for the marker lines,
# never finds them in this file.
CFG_END_MARKER = "# __SORTEROS_CFG" + "_END__"
# The rendezvous for the phone's Hive page, for sorteros-network to announce
# the address to after the restart.
ANNOUNCE_STATE_FILE = Path("/var/lib/sorteros/ip-announce.json")
PORTAL_HOST = "0.0.0.0"
PORTAL_PORT = 80
AP_TEARDOWN_DELAY_S = 5.0


# Where the encrypted LAN-IP rendezvous lives. The browser carries the
# matching private key; Hive only ever stores opaque ciphertext. The portal
# only persists the rendezvous id + hive url; sorteros-network does the
# announce (it fetches the browser's public key from Hive and encrypts the
# address with it), because the pubkey isn't on Hive until the user opens the
# lookup page, after this portal process is gone.
DEFAULT_HIVE_URL = "https://hive.basically.website"

# Mock data — only used in --mode=mock.
MOCK_NETWORKS = [
    {"ssid": "WohnzimmerWLAN", "signal": 92, "security": "WPA2"},
    {"ssid": "Coffee_Shop_Guest", "signal": 71, "security": "WPA2"},
    {"ssid": "FRITZ!Box 7590", "signal": 64, "security": "WPA3"},
    {"ssid": "Open Network", "signal": 48, "security": ""},
    {"ssid": "weak-uplink", "signal": 22, "security": "WPA2"},
]


# ─── nmcli helpers ─────────────────────────────────────────────────────────

def _nmcli_available() -> bool:
    return shutil.which("nmcli") is not None


def _scan_before_broadcast() -> list[dict[str, Any]]:
    """What sorteros-network scanned just before the setup network went up,
    strongest first. The page offers only this: the Orange Pi 5's Wi-Fi can't
    scan while it broadcasts, and asking it to stalls for the whole timeout."""
    try:
        networks = json.loads(NETWORKS.read_text())
    except (OSError, ValueError):
        return []
    return [n for n in networks if isinstance(n, dict) and isinstance(n.get("ssid"), str)]


# ─── IP-announce handoff to sorteros-network ───────────────────────────────

def _write_announce_state(state: "PortalState", rendezvous_id: str) -> None:
    """Persist the rendezvous so sorteros-network can announce the address
    after the restart. Only the id + hive url, no key material:
    sorteros-network fetches the phone's public key from Hive and encrypts to
    it. Best-effort write."""
    try:
        ANNOUNCE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ANNOUNCE_STATE_FILE.write_text(json.dumps({
            "rendezvous_id": rendezvous_id,
            "hive_url": state.hive_url,
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


def _suggested_url(hostname: str | None = None) -> str:
    """Best-guess URL the user should hit once Wi-Fi is up: the name they
    just gave it, if any."""
    return f"http://{hostname or _hostname()}.local/"


def _last_failed_join() -> dict[str, Any] | None:
    """The network sorteros-network couldn't join after the last restart."""
    try:
        failed = json.loads(JOIN_FAILED.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(failed, dict) or not isinstance(failed.get("ssid"), str):
        return None
    return {
        "ssid": failed["ssid"],
        "hostname": None,
        "result": "join_failed",
        "reason": failed.get("reason") or "other",
        "error": failed.get("detail"),
    }


def _restart_to_join(ssid: str, password: str, hidden: bool, security: str) -> None:
    """Leave the choice for sorteros-network, root-only (it holds the
    password until the next boot uses it)."""
    JOIN_PENDING.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOIN_PENDING.with_name(JOIN_PENDING.name + ".tmp")
    with open(tmp, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump({"ssid": ssid, "password": password, "hidden": hidden, "security": security, "at": time.time()}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, JOIN_PENDING)
    JOIN_FAILED.unlink(missing_ok=True)


def _security_of(ssid: str) -> str:
    """The security the scan saw for `ssid` ("" for a hidden network)."""
    return next((n.get("security") or "" for n in _scan_before_broadcast() if n.get("ssid") == ssid), "")


async def _restart_soon() -> None:
    """Let the HTTP response reach the phone, then restart. The next boot
    joins the saved network (sorteros-network)."""
    await asyncio.sleep(AP_TEARDOWN_DELAY_S)
    log.info("restarting to join the network: %s", " ".join(REBOOT_CMD))
    subprocess.run(REBOOT_CMD, timeout=30)


# ─── config persistence ────────────────────────────────────────────────────

def _read_config_toml() -> dict[str, Any]:
    try:
        raw = CONFIG_TOML.read_text("utf-8", errors="replace")
    except OSError:
        return {}
    if CFG_END_MARKER in raw:
        raw = raw[: raw.index(CFG_END_MARKER)]
    try:
        import tomllib  # type: ignore
    except ImportError:
        import tomli as tomllib  # type: ignore
    try:
        return tomllib.loads(raw)
    except Exception:
        log.warning("existing config unreadable; starting a fresh one")
        return {}


def _toml_str(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid TOML basic string


def _write_config_toml(*, hostname: str | None, ssh_key: str | None) -> None:
    """Merge the hostname and SSH key from the page into
    /etc/sorteros-config.toml, keeping anything else the setup site put there
    (its Wi-Fi, the Tailscale key). firstboot applies the file whenever it
    changes. The network itself lives in NetworkManager."""
    cfg = _read_config_toml()
    if hostname:
        cfg["hostname"] = hostname.strip()
    if ssh_key:
        cfg.setdefault("ssh", {})["authorized_key"] = ssh_key.strip()
    lines = ["# Written by sorteros-portal during Wi-Fi setup.\n"]
    if isinstance(cfg.get("hostname"), str):
        lines.append(f"hostname = {_toml_str(cfg['hostname'])}\n")
    for table in ("wifi", "ssh", "tailscale"):
        values = cfg.get(table)
        if isinstance(values, dict) and values:
            lines.append(f"\n[{table}]\n")
            for key, value in values.items():
                if isinstance(value, str):
                    lines.append(f"{key} = {_toml_str(value)}\n")
    CONFIG_TOML.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_TOML.write_text("".join(lines))


# ─── app ──────────────────────────────────────────────────────────────────


@dataclass
class PortalState:
    mode: str  # "ap" | "mock"
    static_dir: Path | None
    hive_url: str = DEFAULT_HIVE_URL
    last_attempt: dict[str, Any] | None = None


def _validate_ssid(ssid: str) -> str:
    # Kept exactly as given: spaces at either end are legal in an SSID.
    if not ssid.strip():
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
    if len(pwd) > 63 and not re.fullmatch(r"[0-9A-Fa-f]{64}", pwd):
        raise HTTPException(status_code=400, detail="Wi-Fi passwords are at most 63 characters.")
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

    @app.middleware("http")
    async def note_activity(request: Request, call_next):
        if request.url.path.startswith("/api/") and state.mode == "ap":
            try:
                PORTAL_ACTIVITY.parent.mkdir(parents=True, exist_ok=True)
                PORTAL_ACTIVITY.touch()
            except OSError:
                pass
        return await call_next(request)

    # ── status & wifi API ───────────────────────────────────────────────

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return {
            "mode": state.mode,
            "hostname": _hostname(),
            "suggested_url": _suggested_url(),
            "last_attempt": state.last_attempt or _last_failed_join(),
        }

    @app.get("/api/wifi-scan")
    def api_wifi_scan() -> dict[str, Any]:
        if state.mode == "mock":
            return {"networks": MOCK_NETWORKS, "mocked": True}
        return {"networks": _scan_before_broadcast(), "mocked": False}

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
                log.info("mock: the Pi would announce its address to %s (id=%s)", state.hive_url, rendezvous)
            return {
                "ok": True,
                "next_url": _suggested_url(hostname),
                "hostname": hostname or _hostname(),
                "mocked": True,
            }

        # Real device: leave the network, the hostname and key, and the
        # rendezvous, then restart once the response has landed. The next
        # boot joins the network (sorteros-network), announces the address to
        # the phone's Hive page, and brings the setup network back if the
        # join fails.
        security = _security_of(ssid)
        if "802.1X" in security:
            attempt["result"] = "error"
            raise HTTPException(
                status_code=400,
                detail=f"{ssid} signs in with a username and password (enterprise Wi-Fi), which the setup "
                "page can't do. Use another network or plug in a cable.",
            )
        try:
            _write_config_toml(hostname=hostname, ssh_key=ssh_key)
            _restart_to_join(ssid, password, payload.hidden, security)
        except OSError as e:
            attempt["result"] = "error"
            attempt["error"] = str(e)
            raise HTTPException(status_code=503, detail=f"Couldn't save the network: {e}")

        if rendezvous:
            _write_announce_state(state, rendezvous)

        attempt["result"] = "restarting"
        asyncio.get_event_loop().create_task(_restart_soon())
        return {
            "ok": True,
            "next_url": _suggested_url(hostname),
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
