"""
SorterOS network: gets the Sorter online, and opens the setup network while it
isn't.

It runs for as long as the machine is up. Every TICK_S it looks at the world
(the cable, the Wi-Fi, whether the internet answers through each, who is on
the setup network) and does what that calls for:

  - Online means the internet answers, not that there's a route: through the
    cable (a router, or a laptop sharing its connection) or a Wi-Fi network.
    NetworkManager checks each network (conf.d/20-sorteros-connectivity.conf)
    and moves traffic off one that doesn't answer, so a cable into a switch
    with no internet never hides a Wi-Fi that works.
  - Not online: after a short grace (a cable or a saved network may still
    come up) it opens the setup network, SorterOS-Setup-XXXXXX, with the setup
    page on it. The Orange Pi 5's Wi-Fi (the AP6275P) can broadcast on a second
    interface, AP_IFACE, while its normal interface stays free: saved networks
    keep being tried, and a network chosen on the phone is joined while the
    phone watches, which says within seconds either where the Sorter now is or
    why it couldn't join. (Broadcasting on the normal interface instead leaves
    this chip unable to join anything until it restarts, so it never does.)
    A radio that can't do both at once broadcasts on its only interface and
    steps off the air to join.
  - Online again: the setup network closes once nobody is on it (after a join
    from the phone, once the phone has had time to read the result).

The setup network is open, so it is fenced: its clients reach the setup page,
DHCP and DNS, nothing else on the machine and nothing beyond it. Every name
resolves to the setup page (dnsmasq-shared.d), which is how phones notice it
and open it by themselves. Port 80 on it is redirected to the page's own port,
so the Sorter UI keeps port 80 on every other network.

Wi-Fi profiles are written only here, as keyfiles: SSIDs as bytes (any SSID is
legal, "/" and all), the rest escaped for GLib's key file format, one profile
per SSID. A failed join puts back the profile it replaced.

The radio's country (the channels it may use) comes from the time zone the
setup site or the phone passed on (zone.tab), else XZ, Broadcom's worldwide
setting. The driver reads it as it loads, so a change counts from the next
start.

Once online: the clock is made right before anything uses HTTPS (no battery
clock, and some networks block NTP), and if the setup page left a Find my
sorter link, the address goes to Hive encrypted to the key that page made.

What it knows goes to STATUS_PATH (every network with its address and whether
the internet answers through it, the name, the ports), which the setup page,
the Sorter software and Hive read; what it did goes to EVENTS_PATH, which
outlives power cuts, so the setup page can say what happened.

Everything that touches the system goes through `System`; the decisions are
tested against a simulated machine (test/test_network.py).
"""

from __future__ import annotations

import argparse
import base64
import email.utils
import hashlib
import http.client
import json
import logging
import mimetypes
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import tomllib  # type: ignore
except ImportError:  # Python 3.10 on the image
    import tomli as tomllib  # type: ignore

log = logging.getLogger("sorteros-network")

CONFIG_PATH = Path("/etc/sorteros-config.toml")
STATE_DIR = Path("/var/lib/sorteros")
IMPORTED_PATH = STATE_DIR / "wifi-imported"
JOIN_PATH = STATE_DIR / "join.json"
EVENTS_PATH = STATE_DIR / "events.jsonl"
ANNOUNCE_PATH = STATE_DIR / "ip-announce.json"
RUN_DIR = Path("/run/sorteros")
STATUS_PATH = RUN_DIR / "network.json"
SOFTWARE_PATH = RUN_DIR / "software.json"  # written by sorteros-firstboot
NM_DIR = Path("/etc/NetworkManager/system-connections")
# Where the AP6275P's driver (Ampak's dhd) reads its country as it loads.
DHD_CONFIG = Path("/lib/firmware/ap6275p/config.txt")
ZONE_TAB = Path("/usr/share/zoneinfo/zone.tab")
ZONEINFO = Path("/usr/share/zoneinfo")
WORLD_COUNTRY = "XZ"
STATIC_DIR = Path("/var/www/portal")
# Split so the setup site, which scans the raw image for the marker lines,
# never finds them in this file.
CFG_END_MARKER = "# __SORTEROS_CFG" + "_END__"

SETUP_SSID_PREFIX = "SorterOS-Setup-"
AP_IFACE = "ap0"
AP_CON = "sorteros-ap"
AP_ADDR = "10.42.0.1"
PORTAL_PORT = 8008
UI_PORT = 80
BACKEND_PORT = 8000
SETUP_CHAIN = "SORTEROS_SETUP"
# After the redirect, what the setup network's clients may reach on the machine.
SETUP_ALLOWED = (("udp", "67"), ("udp", "53"), ("tcp", "53"), ("tcp", str(PORTAL_PORT)))

TICK_S = 2
WIRED_GRACE_S = 20  # a cable with a link, to get an address and answer
SAVED_GRACE_S = 40  # saved Wi-Fi, to join after power-on
LOST_GRACE_S = 60  # was online, to come back before the setup network opens
JOIN_WAIT_S = 90  # longer than NetworkManager's own DHCP timeout (45 s), so its reason comes back
IDLE_CLOSE_S = 30  # online, and nobody on the setup network for this long
AFTER_JOIN_IDLE_CLOSE_S = 300  # after a join: the phone may drop off as the channel changes, and come back
AFTER_JOIN_MAX_S = 600
DONE_CLOSE_S = 5
SCAN_EVERY_S = 120
SECOND_SCAN_S = 15  # the scan at start can come back short: NetworkManager has only just brought up the Wi-Fi
SAVED_RETRY_S = 60  # a saved network seen in a scan while offline is tried this often
SINGLE_RADIO_RETRY_S = 300
STATUS_EVERY_S = 30
EVENTS_KEEP = 200
EVENTS_SHOWN = 20
ANNOUNCE_WINDOW_S = 900
ANNOUNCE_EVERY_S = 10
CLOCK_WAIT_S = 20
CLOCK_HOST = "hive.basically.website"  # any server whose plain-HTTP answer carries a Date header
# Hive sits behind Cloudflare, which refuses urllib's own "Python-urllib/3.x"
# with a 403. Any honest name gets through.
HTTP_HEADERS = {"User-Agent": "SorterOS"}
DEFAULT_HIVE_URL = "https://hive.basically.website"

REASONS = {
    "password": "wrong password",
    "not_found": "not in range",
    "no_address": "no address from the router",
    "timeout": "no answer",
    "other": "it didn't work",
}

_CONTROL = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|[\x00-\x08\x0b-\x1f]")


# ─── pure helpers ──────────────────────────────────────────────────────────

def read_config(path: Path = CONFIG_PATH) -> dict:
    """The setup config, with the setup site's placeholder padding cut off."""
    try:
        raw = path.read_text("utf-8", errors="replace")
    except OSError:
        return {}
    if CFG_END_MARKER in raw:
        raw = raw[: raw.index(CFG_END_MARKER)]
    try:
        return tomllib.loads(raw)
    except Exception as e:
        log.warning("config %s unreadable: %s", path, e)
        return {}


def config_toml(cfg: dict) -> str:
    """`cfg` (strings, and tables of strings) as TOML."""
    lines = [f"{k} = {json.dumps(v)}" for k, v in cfg.items() if isinstance(v, str)]
    for table, values in cfg.items():
        if isinstance(values, dict) and values:
            lines += ["", f"[{table}]"] + [f"{k} = {json.dumps(v)}" for k, v in values.items() if isinstance(v, str)]
    return "\n".join(lines) + "\n"


def wifi_from_config(cfg: dict) -> tuple[str, str] | None:
    wifi = cfg.get("wifi") or {}
    ssid = wifi.get("ssid")
    if not isinstance(ssid, str) or not ssid.strip():
        return None
    password = wifi.get("password")
    return ssid.strip(), password if isinstance(password, str) else ""


def keyfile_value(text: str) -> str:
    """`text` as a GLib key file value: backslashes and line breaks escaped,
    and spaces at either end kept (GLib trims them otherwise)."""
    text = text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    if text.startswith(" "):
        text = "\\s" + text[1:]
    if text.endswith(" "):
        text = text[:-1] + "\\s"
    return text


def nm_keyfile(ssid: str, password: str, uuid_: str, hidden: bool = False, security: str = "") -> str:
    """A NetworkManager profile for a network. WPA3-only networks take SAE;
    everything else with a password takes WPA-PSK (WPA2, and WPA2/WPA3 mixed
    mode). It must get an IPv4 address to count as joined."""
    lines = [
        "[connection]", f"id={keyfile_value(ssid)}", f"uuid={uuid_}", "type=wifi", "autoconnect=true", "",
        "[wifi]", "mode=infrastructure", "ssid=" + "".join(f"{b};" for b in ssid.encode()),
    ]
    if hidden:
        lines.append("hidden=true")
    if password:
        sae = "WPA3" in security and not re.search(r"WPA[12]", security)
        lines += ["", "[wifi-security]", f"key-mgmt={'sae' if sae else 'wpa-psk'}", f"psk={keyfile_value(password)}"]
    lines += ["", "[ipv4]", "method=auto", "may-fail=false", "", "[ipv6]", "method=auto", ""]
    return "\n".join(lines)


def profile_path(ssid: str) -> Path:
    """Where the profile for `ssid` lives: named after it, made safe for a
    file name (NetworkManager ignores dotfiles, and "/" is a directory)."""
    safe = re.sub(r"[^A-Za-z0-9 _.-]", "_", ssid).strip(" .") or "wifi"
    return NM_DIR / f"{safe}-{hashlib.sha256(ssid.encode()).hexdigest()[:8]}.nmconnection"


def country_for_timezone(timezone: str, zone_tab: str) -> str | None:
    for line in zone_tab.splitlines():
        cols = line.split("\t")
        if not line.startswith("#") and len(cols) >= 3 and cols[2] == timezone:
            return cols[0]
    return None


def wifi_country(cfg: dict, zone_tab: str) -> str:
    timezone = cfg.get("timezone")
    return (isinstance(timezone, str) and country_for_timezone(timezone, zone_tab)) or WORLD_COUNTRY


def with_country(text: str, country: str) -> str:
    """A dhd config.txt with its country set (and any old setting dropped)."""
    lines = [line for line in text.splitlines() if not re.match(r"\s*(ccode|regrev)\s*=", line)]
    return "\n".join(lines + [f"ccode={country}", "regrev=0"]) + "\n"


def join_failure_reason(error: str) -> str:
    """What NetworkManager's error means for the person on the setup page."""
    e = error.lower()
    if "secrets were required" in e or "supplicant" in e or "4-way" in e:
        return "password"
    if "could not be found" in e or "no network with ssid" in e:
        return "not_found"
    if "ip configuration" in e or "dhcp" in e:
        return "no_address"
    if "timeout" in e or "timed out" in e:
        return "timeout"
    return "other"


def nmcli_fields(line: str) -> list[str]:
    """One line of `nmcli -t` output as its fields: they end at an unescaped
    ":", and "\\:" and "\\\\" stand for ":" and "\\"."""
    fields, field, chars = [], [], iter(line)
    for c in chars:
        if c == "\\":
            field.append(next(chars, ""))
        elif c == ":":
            fields.append("".join(field))
            field = []
        else:
            field.append(c)
    fields.append("".join(field))
    return fields


def parse_scan(text: str) -> list[dict]:
    """`nmcli -t -f SSID,SIGNAL,SECURITY dev wifi list` → one entry per SSID,
    strongest first, names exact, hidden networks and setup networks left out."""
    best: dict[str, dict] = {}
    for line in text.splitlines():
        parts = nmcli_fields(line)
        if len(parts) < 3:
            continue
        ssid, signal_raw, security = parts[0], parts[1], parts[2].strip()
        if not ssid.strip() or ssid.startswith(SETUP_SSID_PREFIX):
            continue
        try:
            signal = int(signal_raw)
        except ValueError:
            signal = 0
        if ssid not in best or signal > best[ssid]["signal"]:
            best[ssid] = {"ssid": ssid, "signal": signal, "security": security}
    return sorted(best.values(), key=lambda n: -n["signal"])


def connectivity(value: str) -> str:
    """nmcli's "4 (full)" → "full"."""
    m = re.search(r"\((\w+)\)", value)
    return m.group(1) if m else (value.strip() or "unknown")


def _write_file(path: Path, text: str, mode: int = 0o600) -> None:
    """Write a file whole or not at all: a power cut mid-write leaves the old
    one. Root-only unless `mode` says otherwise."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w") as f:
        os.fchmod(f.fileno(), mode)
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


class BadRequest(Exception):
    """What a join request got wrong, in words for the page."""


def validate_join(body: dict, scanned: list[dict], zoneinfo: Path = ZONEINFO) -> dict:
    """A join request from the page, checked. The SSID is kept exactly as
    given: spaces at either end are legal in one."""
    ssid = body.get("ssid")
    if not isinstance(ssid, str) or not ssid.strip():
        raise BadRequest("Pick a network or type its name.")
    if len(ssid.encode()) > 32:
        raise BadRequest("Network names are at most 32 characters.")
    password = body.get("password") or ""
    if not isinstance(password, str):
        raise BadRequest("The password must be text.")
    password = password.strip("\r\n")
    if password and len(password) < 8:
        raise BadRequest("Wi-Fi passwords are at least 8 characters.")
    if len(password) > 63 and not re.fullmatch(r"[0-9A-Fa-f]{64}", password):
        raise BadRequest("Wi-Fi passwords are at most 63 characters.")
    security = next((n.get("security") or "" for n in scanned if n.get("ssid") == ssid), "")
    if not password and re.search(r"WPA|SAE", security):
        raise BadRequest(f"Type the password for {ssid}.")
    if "802.1X" in security:
        raise BadRequest(f"{ssid} needs a username as well as a password, which the Sorter can't do. Use a cable.")
    if "WEP" in security:
        raise BadRequest(f"{ssid} uses WEP, an old kind of security the Sorter can't use. Use a cable.")
    name = body.get("name")
    if name is not None and name != "":
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", name.strip().lower()):
            raise BadRequest("Names are lowercase letters, digits and dashes.")
        name = name.strip().lower()
    else:
        name = None
    timezone = body.get("timezone")
    if not (isinstance(timezone, str) and re.fullmatch(r"[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*", timezone)
            and (zoneinfo / timezone).is_file()):
        timezone = None
    rendezvous = body.get("rendezvous_id")
    if not (isinstance(rendezvous, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,64}", rendezvous)):
        rendezvous = None
    return {"ssid": ssid, "password": password, "hidden": bool(body.get("hidden")), "security": security,
            "name": name, "timezone": timezone, "rendezvous": rendezvous, "source": "phone"}


# ─── the machine ───────────────────────────────────────────────────────────

class System:
    """NetworkManager, the radio, the firewall, files and Hive, for real."""

    def _run(self, *cmd: str, timeout: float = 20) -> subprocess.CompletedProcess:
        try:
            p = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(list(cmd), 124, "", "timed out")
        except FileNotFoundError:
            return subprocess.CompletedProcess(list(cmd), 127, "", f"{cmd[0]} not found")
        p.stdout = _CONTROL.sub("", p.stdout or "")
        p.stderr = _CONTROL.sub("", p.stderr or "")
        return p

    # clock
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def wall_now(self) -> float:
        return time.time()

    def boot_id(self) -> str:
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip()[:8]
        except OSError:
            return ""

    def clock_synced(self) -> bool:
        return self._run("timedatectl", "show", "-p", "NTPSynchronized", "--value").stdout.strip() == "yes"

    def http_date(self) -> float | None:
        """The time a web server says it is, over plain HTTP (a redirect to
        HTTPS still carries it; HTTPS itself needs the clock to be right)."""
        conn = http.client.HTTPConnection(CLOCK_HOST, 80, timeout=8)
        try:
            conn.request("HEAD", "/", headers=HTTP_HEADERS)
            date = conn.getresponse().getheader("Date")
            return email.utils.parsedate_to_datetime(date).timestamp() if date else None
        except (OSError, ValueError, TypeError, http.client.HTTPException):
            return None
        finally:
            conn.close()

    def set_clock(self, t: float) -> None:
        self._run("date", "-u", "-s", f"@{int(t)}")

    # what the machine is on
    def devices(self) -> list[dict]:
        """Ethernet and Wi-Fi devices: iface, kind ("ethernet"/"wifi"), state."""
        out = []
        for line in self._run("nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device").stdout.splitlines():
            iface, kind, state = (nmcli_fields(line) + ["", ""])[:3]
            if kind in ("ethernet", "wifi") and state != "unmanaged":
                out.append({"iface": iface, "kind": kind, "state": state.split(" ")[0]})
        return out

    def device_info(self, iface: str) -> dict:
        """Its IPv4 address, whether the internet answers through it (full,
        limited, portal, none, unknown), and its profile's uuid."""
        info = {"address": None, "internet": "unknown", "uuid": None}
        r = self._run("nmcli", "-t", "-f", "IP4.ADDRESS,GENERAL.IP4-CONNECTIVITY,GENERAL.CON-UUID", "device", "show", iface)
        for line in r.stdout.splitlines():
            key, _, value = line.partition(":")
            if key.startswith("IP4.ADDRESS") and info["address"] is None and value:
                info["address"] = value.split("/")[0]
            elif key == "GENERAL.IP4-CONNECTIVITY":
                info["internet"] = connectivity(value)
            elif key == "GENERAL.CON-UUID" and value:
                info["uuid"] = value
        return info

    def check_internet(self) -> None:
        """Have NetworkManager check every network now rather than at its next turn."""
        self._run("nmcli", "networking", "connectivity", "check", timeout=30)

    def ssid_of(self, con_uuid: str) -> str | None:
        r = self._run("nmcli", "--escape", "no", "-g", "802-11-wireless.ssid", "connection", "show", "uuid", con_uuid)
        return r.stdout.rstrip("\n") or None

    def carrier(self, iface: str) -> bool:
        try:
            return Path(f"/sys/class/net/{iface}/carrier").read_text().strip() == "1"
        except OSError:
            return False

    def tailscale_ip(self) -> str | None:
        out = self._run("ip", "-4", "-o", "addr", "show", "dev", "tailscale0").stdout
        m = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)/", out)
        return m.group(1) if m else None

    def hostname(self) -> str:
        return socket.gethostname() or "sorter"

    def mdns_name(self) -> str:
        """The name the machine answers to on the network: avahi's, which is
        <hostname>-2.local when another machine already has <hostname>.local."""
        out = self._run("busctl", "call", "org.freedesktop.Avahi", "/", "org.freedesktop.Avahi.Server",
                        "GetHostNameFqdn").stdout.strip()
        m = re.fullmatch(r's "(.+)"', out)
        return m.group(1) if m else f"{self.hostname()}.local"

    def mac(self, iface: str) -> str:
        try:
            return Path(f"/sys/class/net/{iface}/address").read_text().strip()
        except OSError:
            return "00:00:00:00:00:00"

    # Wi-Fi profiles
    def saved_wifi(self) -> list[str]:
        """The SSIDs of the saved Wi-Fi networks."""
        ssids = []
        for line in self._run("nmcli", "-t", "-f", "UUID,TYPE,NAME", "connection", "show").stdout.splitlines():
            con_uuid, kind, name = (nmcli_fields(line) + ["", ""])[:3]
            if kind == "802-11-wireless" and name != AP_CON:
                ssid = self.ssid_of(con_uuid)
                if ssid:
                    ssids.append(ssid)
        return ssids

    def write_wifi(self, ssid: str, password: str, hidden: bool = False,
                   security: str = "") -> tuple[str, dict[str, str]]:
        """Save `ssid` as the one profile for that network. Returns the new
        profile's uuid and the profiles it replaced (file → text), so a
        failed join can put them back."""
        replaced = {}
        for line in self._run("nmcli", "-t", "-f", "UUID,TYPE,FILENAME", "connection", "show").stdout.splitlines():
            con_uuid, kind, filename = (nmcli_fields(line) + ["", ""])[:3]
            if kind != "802-11-wireless" or not filename.startswith(f"{NM_DIR}/"):
                continue
            if self.ssid_of(con_uuid) != ssid:
                continue
            try:
                replaced[filename] = Path(filename).read_text()
                Path(filename).unlink()
            except OSError:
                pass
        new_uuid = str(uuid.uuid4())
        _write_file(profile_path(ssid), nm_keyfile(ssid, password, new_uuid, hidden, security))
        self._run("nmcli", "connection", "reload")
        return new_uuid, replaced

    def forget_wifi(self, con_uuid: str, replaced: dict[str, str]) -> None:
        """Undo write_wifi: drop the new profile, put back the ones it replaced."""
        self._run("nmcli", "connection", "delete", "uuid", con_uuid)
        for filename, text in replaced.items():
            _write_file(Path(filename), text)
        self._run("nmcli", "connection", "reload")

    def join(self, con_uuid: str, iface: str) -> str | None:
        """Bring a saved profile up on `iface`. None once it's joined with an
        address, else NetworkManager's reason."""
        r = self._run("nmcli", "--wait", str(JOIN_WAIT_S), "connection", "up", "uuid", con_uuid,
                      "ifname", iface, timeout=JOIN_WAIT_S + 15)
        if r.returncode == 0:
            return None
        state = self._run("nmcli", "-g", "GENERAL.STATE", "device", "show", iface).stdout
        if "getting IP" in state:  # still waiting for the router to hand out an address
            self._run("nmcli", "device", "disconnect", iface)
            return "IP configuration could not be reserved: no address in time"
        if r.returncode == 124:
            return "timed out"
        # nmcli can lead with warnings and trail a journalctl hint; keep the error.
        lines = [line.strip() for line in (r.stderr + r.stdout).splitlines()]
        errors = [line.removeprefix("Error: ") for line in lines if line.startswith("Error:")]
        return errors[0] if errors else next((line for line in lines if line), f"nmcli exited {r.returncode}")

    def join_saved(self, ssid: str, iface: str) -> str | None:
        for line in self._run("nmcli", "-t", "-f", "UUID,TYPE", "connection", "show").stdout.splitlines():
            con_uuid, kind = (nmcli_fields(line) + [""])[:2]
            if kind == "802-11-wireless" and self.ssid_of(con_uuid) == ssid:
                return self.join(con_uuid, iface)
        return "not saved"

    def scan(self, iface: str) -> list[dict]:
        r = self._run("nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                      "ifname", iface, "--rescan", "yes", timeout=30)
        return parse_scan(r.stdout)

    # the setup network
    def add_ap_iface(self, wifi_iface: str) -> str | None:
        """A second interface on the radio to broadcast from, or None if the
        radio can't. Never deleted or set down: on the AP6275P either one
        switches the whole radio off."""
        if Path(f"/sys/class/net/{AP_IFACE}").exists():
            return AP_IFACE
        try:
            phy = Path(f"/sys/class/net/{wifi_iface}/phy80211/name").read_text().strip()
        except OSError:
            return None
        r = self._run("iw", "phy", phy, "interface", "add", AP_IFACE, "type", "__ap")
        if r.returncode != 0:
            log.info("the radio can't broadcast beside its normal interface: %s", (r.stderr or r.stdout).strip())
            return None
        for _ in range(20):  # NetworkManager picks it up
            if any(d["iface"] == AP_IFACE for d in self.devices()):
                break
            time.sleep(0.5)
        self._run("nmcli", "device", "set", AP_IFACE, "autoconnect", "no")
        return AP_IFACE

    def ap_up(self, iface: str, ssid: str) -> str | None:
        """Broadcast `ssid` on `iface`. None, or why it wouldn't."""
        self._run("nmcli", "connection", "delete", AP_CON)
        self._run(
            "nmcli", "connection", "add", "type", "wifi", "ifname", iface, "con-name", AP_CON,
            "autoconnect", "no", "ssid", ssid,
            "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg", "802-11-wireless.channel", "6",
            "ipv4.method", "shared", "ipv4.addresses", f"{AP_ADDR}/24", "ipv6.method", "ignore",
        )
        r = self._run("nmcli", "--wait", "20", "connection", "up", AP_CON, timeout=30)
        return None if r.returncode == 0 else (r.stderr or r.stdout).strip() or "nmcli failed"

    def ap_down(self) -> None:
        self._run("nmcli", "connection", "down", AP_CON)

    def ap_clients(self, iface: str) -> int:
        return self._run("iw", "dev", iface, "station", "dump").stdout.count("Station ")

    def fence(self, iface: str) -> None:
        """Its clients reach the setup page, DHCP and DNS on this machine and
        nothing else: not SSH, not the Sorter, not the networks beyond it."""
        self.unfence(iface)
        ipt = lambda *a: self._run("iptables", *a)  # noqa: E731
        ipt("-N", SETUP_CHAIN)
        for proto, port in SETUP_ALLOWED:
            ipt("-A", SETUP_CHAIN, "-p", proto, "--dport", port, "-j", "ACCEPT")
        ipt("-A", SETUP_CHAIN, "-p", "icmp", "-j", "ACCEPT")
        ipt("-A", SETUP_CHAIN, "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT")
        ipt("-A", SETUP_CHAIN, "-j", "DROP")
        rules = [("INPUT", "-i", iface, "-j", SETUP_CHAIN), ("FORWARD", "-i", iface, "-j", "DROP"),
                 ("FORWARD", "-o", iface, "-j", "DROP")]
        for chain, *rule in rules:
            r = ipt("-I", chain, "1", *rule)
            if r.returncode != 0:
                log.warning("the setup network is NOT fenced (%s): %s", chain, (r.stderr or r.stdout).strip())
        ipt("-t", "nat", "-I", "PREROUTING", "1", "-i", iface, "-p", "tcp", "--dport", "80",
            "-j", "REDIRECT", "--to-ports", str(PORTAL_PORT))
        for chain in ("INPUT", "FORWARD"):  # link-local IPv6 would get around all of the above
            self._run("ip6tables", "-I", chain, "1", "-i", iface, "-j", "DROP")

    def fenced(self, iface: str) -> bool:
        """The fence's forwarding rules are still first: NetworkManager puts
        its own sharing rules at the top when it starts the network."""
        forward = [r for r in self._run("iptables", "-S", "FORWARD").stdout.splitlines() if r.startswith("-A")]
        return bool(forward) and forward[0] in (f"-A FORWARD -i {iface} -j DROP", f"-A FORWARD -o {iface} -j DROP")

    def unfence(self, iface: str) -> None:
        """Take down what `fence` put up (and nothing of NetworkManager's)."""
        for tool, table in (("iptables", "filter"), ("iptables", "nat"), ("ip6tables", "filter")):
            for rule in self._run(tool, "-t", table, "-S").stdout.splitlines():
                words = rule.split()
                pairs = set(zip(words, words[1:]))
                on_iface = ("-i", iface) in pairs or ("-o", iface) in pairs
                ours = ("-j", SETUP_CHAIN) in pairs or ("-j", "DROP") in pairs or ("-j", "REDIRECT") in pairs
                if words[:1] == ["-A"] and on_iface and ours:
                    self._run(tool, "-t", table, "-D", *words[1:])
        self._run("iptables", "-F", SETUP_CHAIN)
        self._run("iptables", "-X", SETUP_CHAIN)

    # files
    def config(self) -> dict:
        return read_config()

    def update_config(self, **values: str) -> None:
        """Merge values into the setup config (keeping what the setup site
        wrote), and have sorteros-firstboot apply it now."""
        cfg = read_config()
        cfg.update({k: v for k, v in values.items() if v})
        _write_file(CONFIG_PATH, config_toml(cfg))
        self._run("systemctl", "start", "--no-block", "sorteros-firstboot.service")

    def zone_tab(self) -> str:
        try:
            return ZONE_TAB.read_text()
        except OSError:
            return ""

    def set_wifi_country(self, country: str) -> bool:
        """Set the radio's country for the next time the driver loads. True
        if it changed."""
        try:
            text = DHD_CONFIG.read_text(errors="replace")
        except OSError:
            return False  # not an AP6275P
        new = with_country(text, country)
        if new == text:
            return False
        _write_file(DHD_CONFIG, new, 0o644)
        return True

    def imported(self) -> str:
        try:
            return IMPORTED_PATH.read_text().strip()
        except OSError:
            return ""

    def mark_imported(self, digest: str) -> None:
        _write_file(IMPORTED_PATH, digest + "\n", 0o644)

    def load_join(self) -> dict | None:
        return _read_json(JOIN_PATH)

    def save_join(self, join: dict | None) -> None:
        if join is None:
            JOIN_PATH.unlink(missing_ok=True)
        else:
            _write_file(JOIN_PATH, json.dumps(join), 0o644)

    def load_events(self) -> list[dict]:
        events = []
        try:
            for line in EVENTS_PATH.read_text().splitlines()[-EVENTS_KEEP:]:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass  # a line a power cut cut short
        except OSError:
            pass
        return events

    def save_event(self, event: dict, keep: list[dict]) -> None:
        """Append one; now and then rewrite the file down to `keep`."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if EVENTS_PATH.stat().st_size > 64_000:
                _write_file(EVENTS_PATH, "".join(json.dumps(e) + "\n" for e in keep), 0o644)
                return
        except OSError:
            pass
        with open(EVENTS_PATH, "a") as f:
            f.write(json.dumps(event) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def software(self) -> dict | None:
        return _read_json(SOFTWARE_PATH)

    def write_status(self, status: dict) -> None:
        _write_file(STATUS_PATH, json.dumps(status), 0o644)

    def announce_state(self) -> dict | None:
        return _read_json(ANNOUNCE_PATH)

    def set_announce(self, rendezvous_id: str) -> None:
        _write_file(ANNOUNCE_PATH, json.dumps({"rendezvous_id": rendezvous_id, "hive_url": DEFAULT_HIVE_URL}), 0o644)

    def clear_announce(self) -> None:
        ANNOUNCE_PATH.unlink(missing_ok=True)

    # Hive: the encrypted address for the phone's Find my sorter page
    def rendezvous(self, state: dict) -> tuple[str | None, bool]:
        """The public key the page posted (None until it has) and whether
        Hive already holds an address for it. Raises URLError/OSError when
        Hive can't be reached or refuses."""
        base = f"{str(state['hive_url']).rstrip('/')}/api/machine-ip-lookup/{state['rendezvous_id']}"
        pubkey = _get_json(f"{base}/pubkey").get("pubkey")
        ready = _get_json(base).get("ready")
        return (pubkey if isinstance(pubkey, str) and pubkey else None), bool(ready)

    def publish_address(self, state: dict, pubkey: str, payload: dict) -> None:
        """Encrypt `payload` to the page's public key and hand it to Hive,
        which only ever sees the ciphertext."""
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        key = serialization.load_der_public_key(base64.b64decode(pubkey))
        ciphertext = key.encrypt(
            json.dumps(payload).encode(),
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        req = urllib.request.Request(
            f"{str(state['hive_url']).rstrip('/')}/api/machine-ip-lookup/{state['rendezvous_id']}",
            data=json.dumps({"ciphertext": base64.b64encode(ciphertext).decode()}).encode(),
            headers={**HTTP_HEADERS, "Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=8).close()


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=HTTP_HEADERS), timeout=8) as resp:
        data = json.loads(resp.read().decode())
    return data if isinstance(data, dict) else {}


# ─── the decisions ─────────────────────────────────────────────────────────

class Network:
    """What the Sorter is on, and what to do about it, one tick at a time.
    The setup page's requests arrive through `request_*` from its own thread
    and are carried out on the next tick."""

    def __init__(self, sys_: System, *, single_radio: bool = False):
        self.sys = sys_
        self.single_radio = single_radio  # force broadcasting on the normal interface
        self.lock = threading.Lock()
        self.requests: queue.Queue = queue.Queue()
        self.boot = sys_.boot_id()
        self.started = sys_.now()
        self.events = sys_.load_events()
        self.join = self._restored_join()
        self.scan = {"scanning": False, "at": None, "networks": []}
        self.networks: list[dict] = []
        self.online = False
        self.was_online = False
        self.offline_since = self.started
        self.cable = "none"
        self.wifi_iface: str | None = None
        self.ap_iface: str | None = None  # where the setup network broadcasts from, once there is one
        self.ap: dict | None = None  # {"ssid", "since", "last_client"} while broadcasting
        self.ap_clients = 0
        self.done_at: float | None = None
        self.dismissed_on: str | None = None  # the network the person said Done on
        self.phone_joined_at: float | None = None
        self.next_scan = 0.0
        self.saved_tried: dict[str, float] = {}
        self.single_radio_retry_at = 0.0
        self.clock_ok = False
        self.announcing = False
        self.clock_settling = False
        self.status: dict = {}
        self.status_written_at = -1e9
        self._ssids: dict[str, str] = {}  # profile uuid → SSID
        self._noted: set = set()
        self._seen: set = set()

    @staticmethod
    def spawn(target) -> None:
        threading.Thread(target=target, daemon=True).start()

    # events
    def event(self, text: str) -> None:
        e = {"at": round(self.sys.wall_now()), "boot": self.boot, "text": text}
        log.info("%s", text)
        with self.lock:
            self.events = (self.events + [e])[-EVENTS_KEEP:]
            keep = list(self.events)
        try:
            self.sys.save_event(e, keep)
        except OSError as err:
            log.warning("couldn't save the event: %s", err)

    def _restored_join(self) -> dict | None:
        join = self.sys.load_join()
        if join and join.get("state") == "joining":  # interrupted: a crash or a power cut
            join.update(state="failed", reason="other", detail="interrupted")
        return join

    def _set_join(self, **join) -> None:
        join.setdefault("at", round(self.sys.wall_now()))
        join["boot"] = self.boot
        with self.lock:
            self.join = join
        self.sys.save_join(join)

    # requests from the setup page
    def request_join(self, body: dict) -> None:
        with self.lock:
            if self.join and self.join.get("state") == "joining":
                raise BadRequest("The Sorter is already joining a network.")
            scanned = list(self.scan["networks"])
        req = validate_join(body, scanned)
        self._set_join(ssid=req["ssid"], state="joining", source="phone")
        self.requests.put(("join", req))

    def request_scan(self) -> None:
        with self.lock:
            self.scan["scanning"] = True
        self.requests.put(("scan", None))

    def request_done(self) -> None:
        self.requests.put(("done", None))

    # one tick
    def tick(self) -> None:
        self.observe()
        self.handle_requests()
        self.policy()
        self.publish()

    def observe(self) -> None:
        devices = self.sys.devices()
        wifi = [d for d in devices if d["kind"] == "wifi" and d["iface"] != AP_IFACE]
        self.wifi_iface = wifi[0]["iface"] if wifi else None
        networks = []
        for d in devices:
            if d["iface"] == AP_IFACE or d["state"] != "connected":
                continue
            if self.ap and d["iface"] == self.ap_iface:
                continue  # broadcasting from the normal interface
            info = self.sys.device_info(d["iface"])
            if not info["address"]:
                continue
            if d["kind"] == "wifi":
                if info["uuid"] and info["uuid"] not in self._ssids:
                    self._ssids[info["uuid"]] = self.sys.ssid_of(info["uuid"]) or d["iface"]
                name = self._ssids.get(info["uuid"]) or d["iface"]
            else:
                name = "Ethernet"
            networks.append({"kind": d["kind"], "iface": d["iface"], "name": name, "address": info["address"],
                             "internet": info["internet"] == "full", "connectivity": info["internet"]})
        cables = [d for d in devices if d["kind"] == "ethernet"]
        if any(n["kind"] == "ethernet" for n in networks):
            cable = "connected"
        elif any(self.sys.carrier(d["iface"]) for d in cables):
            cable = "plugged"
        else:
            cable = "none"
        ts = self.sys.tailscale_ip()
        if ts:
            networks.append({"kind": "tailscale", "iface": "tailscale0", "name": "Tailscale", "address": ts,
                             "internet": None, "connectivity": None})
        online = any(n["internet"] for n in networks)
        now = self.sys.now()
        self._note_changes(networks, cable, online)
        with self.lock:
            self.networks, self.cable, self.online = networks, cable, online
        if online:
            self.offline_since = None
            self.was_online = True
        elif self.offline_since is None:
            self.offline_since = now
        if self.ap and self.ap_iface:
            clients = self.sys.ap_clients(self.ap_iface)
            if clients > self.ap_clients:
                self.event("A phone joined the setup network")
            self.ap_clients = clients
            if clients:
                self.ap["last_client"] = now

    def _note_changes(self, networks: list[dict], cable: str, online: bool) -> None:
        """Events for what changed. A network without internet is noted only
        once it has stayed that way for a tick: right after it connects,
        NetworkManager hasn't asked the internet yet."""
        now_keys = {}
        for n in networks:
            if n["kind"] != "tailscale":
                now_keys[(n["kind"], n["name"], n["address"], n["internet"], n["connectivity"])] = n
        for k, n in now_keys.items():
            if k in self._noted:
                continue
            where = "by cable" if n["kind"] == "ethernet" else f"on {n['name']}"
            if n["internet"]:
                self.event(f"Online {where} at {n['address']}")
                self._noted.add(k)
            elif n["connectivity"] in ("none", "limited", "portal") and k in self._seen:
                what = "a sign-in page in the way" if n["connectivity"] == "portal" else "no internet"
                self.event(f"Connected {where} at {n['address']}, but {what}")
                self._noted.add(k)
        self._noted &= set(now_keys)  # one that went away is noted again when it's back
        self._seen = set(now_keys)
        if self.online and not online:
            self.event("Lost the internet")
        if cable != self.cable and cable == "none" and self.cable != "none":
            self.event("Cable unplugged")

    def handle_requests(self) -> None:
        while True:
            try:
                kind, req = self.requests.get_nowait()
            except queue.Empty:
                return
            if kind == "join":
                self.do_join(req)
            elif kind == "scan":
                self.do_scan()
            elif kind == "done":
                self.done_at = self.sys.now()
                joined = [n for n in self.networks if n["kind"] == "wifi"]
                self.dismissed_on = joined[0]["name"] if joined else None

    def do_scan(self) -> None:
        if not self.wifi_iface or (self.ap and self.ap_iface == self.wifi_iface):
            with self.lock:  # broadcasting from the only interface: it can't scan
                self.scan["scanning"] = False
            return
        with self.lock:
            first = self.scan["at"] is None
            self.scan["scanning"] = True
        networks = self.sys.scan(self.wifi_iface)
        saved = set(self.sys.saved_wifi())
        for n in networks:
            n["saved"] = n["ssid"] in saved
        with self.lock:
            self.scan = {"scanning": False, "at": round(self.sys.wall_now()), "networks": networks}
        self.next_scan = self.sys.now() + (SECOND_SCAN_S if first else SCAN_EVERY_S)

    def do_join(self, req: dict) -> None:
        """Save the network and join it, while the setup network stays up
        (or, on a radio that can't do both, with it off the air)."""
        ssid, source = req["ssid"], req["source"]
        self._set_join(ssid=ssid, state="joining", source=source)
        if req.get("timezone") or req.get("name"):
            self.sys.update_config(timezone=req.get("timezone") or "", hostname=req.get("name") or "")
            sync_wifi_country(self.sys, self.sys.config())
        if req.get("rendezvous"):
            self.sys.set_announce(req["rendezvous"])
        if not self.wifi_iface:
            self._set_join(ssid=ssid, state="failed", source=source, reason="other", detail="no Wi-Fi hardware")
            return
        security = req.get("security")
        if security is None:  # the setup site's: the scan says whether it's WPA3
            if not self.scan["at"]:
                self.do_scan()
            security = next((n["security"] for n in self.scan["networks"] if n["ssid"] == ssid), "")
        self.event(f"Trying {ssid}" + (", from the setup site" if source == "setup_site" else ""))
        con_uuid, replaced = self.sys.write_wifi(ssid, req["password"], req.get("hidden", False), security)
        if self.ap and self.ap_iface == self.wifi_iface:
            self.close_ap("to join " + ssid)
        error = self.sys.join(con_uuid, self.wifi_iface)
        if error is None:
            self.sys.check_internet()
            info = self.sys.device_info(self.wifi_iface)
            internet = info["internet"] == "full"
            self._set_join(ssid=ssid, state="joined", source=source, address=info["address"], internet=internet)
            self.event(f"Joined {ssid} at {info['address']}" + ("" if internet else ", but no internet"))
            if source == "phone":
                self.phone_joined_at = self.sys.now()
            self.observe()
            return
        reason = join_failure_reason(error)
        self._set_join(ssid=ssid, state="failed", source=source, reason=reason, detail=error)
        self.event(f"Couldn't join {ssid}: {REASONS[reason]}")
        if source == "setup_site" and reason != "password":
            log.info("keeping %s, from the setup site: its router may not be up yet", ssid)
        else:
            self.sys.forget_wifi(con_uuid, replaced)

    def import_config_wifi(self, cfg: dict) -> None:
        """The setup site's Wi-Fi, the first time this machine sees it (once
        per network and password; after that it is a saved network)."""
        wifi = wifi_from_config(cfg)
        if wifi is None:
            return
        digest = hashlib.sha256("\0".join(wifi).encode()).hexdigest()
        if self.sys.imported() == digest:
            return
        self.sys.mark_imported(digest)
        self.requests.put(("join", {"ssid": wifi[0], "password": wifi[1], "source": "setup_site"}))

    # the setup network
    def grace(self) -> float:
        if self.was_online:
            return LOST_GRACE_S
        g = 0.0
        if self.cable != "none":  # a link: an address, or the internet check, may be on its way
            g = WIRED_GRACE_S
        if self.wifi_iface and self.sys.saved_wifi():
            g = max(g, SAVED_GRACE_S)
        return g

    def policy(self) -> None:
        now = self.sys.now()
        if self.ap:
            self._while_broadcasting(now)
            return
        wifi_joined = any(n["kind"] == "wifi" for n in self.networks)
        if self.dismissed_on and any(n["name"] == self.dismissed_on for n in self.networks):
            return  # said Done on a network without internet: leave it be
        self.dismissed_on = None
        if self.online or not self.wifi_iface:
            return
        if (self.single_radio or self.ap_iface == self.wifi_iface) and wifi_joined:
            return  # its only interface is on a network, internet or not
        offline_since = now if self.offline_since is None else self.offline_since
        if now - offline_since >= self.grace():
            self.open_ap(self.wifi_iface, now)

    def open_ap(self, wifi: str, now: float) -> None:
        if self.ap_iface is None:
            self.ap_iface = (None if self.single_radio else self.sys.add_ap_iface(wifi)) or wifi
            if self.ap_iface == wifi:
                self.event("This Wi-Fi can't broadcast beside a connection: it steps off the air to join")
        ap_iface = self.ap_iface
        if ap_iface == wifi or not self.scan["at"]:
            self.do_scan()  # before broadcasting: the only interface can't scan while it broadcasts
        ssid = SETUP_SSID_PREFIX + self.sys.mac(wifi).replace(":", "")[-6:].upper()
        self.sys.fence(ap_iface)
        error = self.sys.ap_up(ap_iface, ssid)
        if error:
            self.sys.unfence(ap_iface)
            self.event(f"Couldn't open the setup network: {error}")
            self.offline_since = now  # try again after another grace
            return
        self.ap = {"ssid": ssid, "since": now, "last_client": None}
        self.ap_clients = 0
        self.done_at = None
        self.single_radio_retry_at = now + SINGLE_RADIO_RETRY_S
        if not self.sys.fenced(ap_iface):
            self.sys.fence(ap_iface)
        why = self._why_offline()
        self.event(f"Opened the setup network {ssid}: {why}")

    def _why_offline(self) -> str:
        if self.was_online:
            return "no internet"
        parts = []
        if self.cable == "none":
            parts.append("no cable")
        elif not any(n["kind"] == "ethernet" and n["internet"] for n in self.networks):
            parts.append("the cable has no internet")
        saved = self.sys.saved_wifi()
        parts.append("no saved Wi-Fi" if not saved else f"{', '.join(saved)} not answering")
        return ", ".join(parts)

    def close_ap(self, why: str) -> None:
        self.sys.ap_down()
        if self.ap_iface:
            self.sys.unfence(self.ap_iface)
        self.ap = None
        self.ap_clients = 0
        self.phone_joined_at = None
        self.event(f"Closed the setup network ({why})")

    def _while_broadcasting(self, now: float) -> None:
        assert self.ap is not None and self.ap_iface is not None
        if not self.sys.fenced(self.ap_iface):
            self.sys.fence(self.ap_iface)
        idle = now - (self.ap["last_client"] or self.ap["since"])
        if self.done_at is not None and now - self.done_at >= DONE_CLOSE_S:
            self.close_ap("done")
            return
        if self.online:
            if self.phone_joined_at is not None:
                if now - self.phone_joined_at >= AFTER_JOIN_MAX_S or idle >= AFTER_JOIN_IDLE_CLOSE_S:
                    self.close_ap("online")
            elif idle >= IDLE_CLOSE_S:
                self.close_ap("online")
            return
        if self.ap_iface != self.wifi_iface and self.wifi_iface:
            if now >= self.next_scan and not self.ap_clients:
                self.do_scan()
            self._try_saved_in_range(self.wifi_iface, now)
        elif self.ap_clients == 0 and now >= self.single_radio_retry_at and self.sys.saved_wifi():
            self.close_ap("to try the saved networks")
            self.single_radio_retry_at = now + SINGLE_RADIO_RETRY_S
            self.offline_since = now  # the grace again, while NetworkManager tries them

    def _try_saved_in_range(self, wifi: str, now: float) -> None:
        """A saved network that has come back in a scan (a router slower to
        start than the Pi after a power cut) is tried at once, not whenever
        NetworkManager next gets to it."""
        if any(n["kind"] == "wifi" for n in self.networks):
            return
        saved = set(self.sys.saved_wifi())
        for n in self.scan["networks"]:
            ssid = n["ssid"]
            if ssid in saved and now - self.saved_tried.get(ssid, -1e9) >= SAVED_RETRY_S:
                self.saved_tried[ssid] = now
                error = self.sys.join_saved(ssid, wifi)
                self.event(f"Joined {ssid}, saved" if error is None else f"Couldn't join {ssid}, saved: {error}")
                return

    # what it knows
    def publish(self) -> None:
        hostname = self.sys.hostname()
        status = {
            "version": 1,
            "clock_ok": self.clock_ok,
            "hostname": hostname,
            "mdns": self.sys.mdns_name(),
            "ports": {"ui": UI_PORT, "backend": BACKEND_PORT},
            "networks": [{k: n[k] for k in ("kind", "iface", "name", "address", "internet")} for n in self.networks],
            "setup_network": {"ssid": self.ap["ssid"], "clients": self.ap_clients} if self.ap else None,
        }
        now = self.sys.now()
        with self.lock:
            changed = status != self.status
            self.status = status
        if changed or now - self.status_written_at >= STATUS_EVERY_S:
            try:
                self.sys.write_status({**status, "at": round(self.sys.wall_now())})
                self.status_written_at = now
            except OSError as e:
                log.warning("couldn't write %s: %s", STATUS_PATH, e)
        if self.online:
            self._start_threads()

    def _page_state(self, status: dict) -> dict:
        """What GET /api/state answers (see portal/README.md). Called with the lock held."""
        join = dict(self.join) if self.join else None
        if join and join.get("state") == "failed" and join.get("boot") != self.boot and self.online:
            join = None  # a failure from before is history once the Sorter is online
        if join:
            join = {k: join.get(k) for k in ("ssid", "state", "reason", "detail", "address", "internet", "source", "at")}
            now_on = next((n for n in self.networks if n["kind"] == "wifi" and n["name"] == join["ssid"]), None)
            if join["state"] == "joined" and now_on:  # as it is now: the internet can answer a moment after the join
                join.update(address=now_on["address"], internet=now_on["internet"])
        software = self.sys.software() or {"state": "waiting", "step": None, "done": 0, "total": 0}
        return {
            "now": round(self.sys.wall_now()),
            "clock_ok": self.clock_ok,
            "sorter": {"name": status["hostname"], "mdns": status["mdns"], "software": software},
            "setup_network": {"ssid": self.ap["ssid"], "live_join": self.ap_iface != self.wifi_iface}
                             if self.ap else None,
            "networks": [{k: n[k] for k in ("kind", "name", "address", "internet")}
                         for n in self.networks if n["kind"] != "tailscale"],
            "cable": self.cable,
            "join": join,
            "scan": dict(self.scan),
            "events": [{"at": e.get("at"), "text": e.get("text")} for e in self.events[-EVENTS_SHOWN:]],
        }

    def page_state(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self._page_state(self.status or {"hostname": "sorter", "mdns": "sorter.local"})))

    # once online
    def _start_threads(self) -> None:
        if not self.clock_settling:
            self.clock_settling = True
            self.spawn(self._settle_clock)
        if not self.announcing and self.sys.announce_state():
            self.announcing = True
            self.spawn(lambda: announce_address(self))

    def _settle_clock(self) -> None:
        shift = settle_clock(self.sys)
        with self.lock:
            if shift:  # this boot's events were stamped by the wrong clock
                for e in self.events:
                    if e.get("boot") == self.boot:
                        e["at"] = round(e["at"] + shift)
            self.clock_ok = True

    def primary_address(self) -> dict | None:
        """The network to point people at: the Wi-Fi they gave on the setup
        page if the Sorter is on it, else one with internet, Wi-Fi first."""
        with self.lock:
            networks = [n for n in self.networks if n["kind"] != "tailscale"]
            wanted = self.join.get("ssid") if self.join and self.join.get("state") == "joined" else None
        for n in networks:
            if n["kind"] == "wifi" and n["name"] == wanted:
                return n
        ranked = sorted(networks, key=lambda n: (not n["internet"], n["kind"] != "wifi"))
        return ranked[0] if ranked else None


def sync_wifi_country(sys_: System, cfg: dict) -> None:
    country = wifi_country(cfg, sys_.zone_tab())
    if sys_.set_wifi_country(country):
        log.info("Wi-Fi country set to %s, from the next start", country)


def settle_clock(sys_: System) -> float:
    """Wait for NTP; failing that, take the time from a web server. Returns
    how far the clock was moved."""
    deadline = sys_.now() + CLOCK_WAIT_S
    while not sys_.clock_synced():
        if sys_.now() >= deadline:
            t = sys_.http_date()
            if t is not None and abs(t - sys_.wall_now()) > 60:
                shift = t - sys_.wall_now()
                log.info("no NTP after %d s: clock set from %s's Date header (it was %d s off)",
                         CLOCK_WAIT_S, CLOCK_HOST, round(shift))
                sys_.set_clock(t)
                return shift
            return 0.0
        sys_.sleep(TICK_S)
    return 0.0


def announce_address(net: Network) -> None:
    """If the setup page left a Find my sorter link, keep that page told
    where the Sorter is until the window closes: a reloaded page brings a new
    key, a restarted Hive forgets what it held, and the address or the name
    can change."""
    sys_ = net.sys
    rendezvous, deadline, last_error, sent = None, 0.0, "", None
    while True:
        state = sys_.announce_state()
        if not state or not state.get("rendezvous_id") or not state.get("hive_url"):
            break
        if state["rendezvous_id"] != rendezvous:  # a new link: its own window, from now on this boot's clock
            rendezvous, deadline, sent = state["rendezvous_id"], sys_.now() + ANNOUNCE_WINDOW_S, None
        if sys_.now() >= deadline:
            sys_.clear_announce()
            break
        try:
            primary = net.primary_address()
            if primary:
                with net.lock:
                    networks = [{k: n[k] for k in ("kind", "name", "address", "internet")}
                                for n in net.networks if n["kind"] != "tailscale"]
                    mdns = net.status.get("mdns") or "sorter.local"
                payload = {"ip": primary["address"], "hostname": mdns, "port": UI_PORT,
                           "ssid": primary["name"] if primary["kind"] == "wifi" else None, "networks": networks}
                pubkey, ready = sys_.rendezvous(state)
                if pubkey and ((pubkey, payload) != sent or not ready):
                    sys_.publish_address(state, pubkey, payload)
                    sent = (pubkey, payload)
                    log.info("told Find my sorter: %s (%s) on %s", payload["ip"], mdns, payload["ssid"] or "Ethernet")
        except (urllib.error.URLError, OSError) as e:
            if str(e) != last_error:
                log.warning("can't reach Hive for Find my sorter yet: %s", e)
                last_error = str(e)
        except Exception as e:
            log.warning("Find my sorter failed: %s", e)
            sys_.clear_announce()
            break
        sys_.sleep(ANNOUNCE_EVERY_S)
    with net.lock:
        net.announcing = False


# ─── the setup page ────────────────────────────────────────────────────────

class PortalHandler(BaseHTTPRequestHandler):
    """The setup page and its API, for the setup network's clients only."""

    net: Network
    static_dir: Path
    only_on: str | None = AP_ADDR  # the local address requests must arrive at; None serves everyone
    server_version = "SorterOS"
    sys_version = ""

    def _allowed(self) -> bool:
        return self.only_on is None or self.connection.getsockname()[0] == self.only_on

    def _send(self, code: int, body: bytes, content_type: str, cache: str = "no-store", head: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _json(self, code: int, value: dict) -> None:
        self._send(code, json.dumps(value).encode(), "application/json")

    def _redirect(self) -> None:
        # Relative, so the name the phone asked for (captive.apple.com and so
        # on, all of which resolve here) stays in its address bar.
        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self, head: bool = False) -> None:  # noqa: N802
        if not self._allowed():
            self._send(404, b"", "text/plain", head=head)
            return
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == "/api/state":
            self._json(200, self.net.page_state())
            return
        if path.startswith("/api/"):
            self._json(404, {"detail": "unknown"})
            return
        if path in ("/", "/index.html"):
            index = self.static_dir / "index.html"
            body = index.read_bytes() if index.is_file() else b"<!doctype html><title>Sorter setup</title><p>The setup page is missing from this image."
            self._send(200, body, "text/html; charset=utf-8", head=head)
            return
        target = (self.static_dir / path.lstrip("/")).resolve()
        if self.static_dir.resolve() in target.parents and target.is_file():
            cache = "public, max-age=31536000, immutable" if "/immutable/" in path else "no-cache"
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), ctype, cache, head=head)
            return
        self._redirect()  # a phone checking for a captive portal, or anything else

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET(head=True)

    def do_POST(self) -> None:  # noqa: N802
        if not self._allowed():
            self._send(404, b"", "text/plain")
            return
        path = urllib.parse.urlsplit(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length > 8192:
            self._json(413, {"detail": "Too long."})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            self._json(400, {"detail": "Not JSON."})
            return
        try:
            if path == "/api/join":
                self.net.request_join(body)
            elif path == "/api/scan":
                self.net.request_scan()
            elif path == "/api/done":
                self.net.request_done()
            else:
                self._json(404, {"detail": "unknown"})
                return
        except BadRequest as e:
            self._json(400, {"detail": str(e)})
            return
        self._json(202, {"ok": True})

    def log_message(self, fmt: str, *args) -> None:
        log.debug("setup page: " + fmt, *args)


def serve_portal(net: Network, host: str, port: int, static_dir: Path, only_on: str | None) -> ThreadingHTTPServer:
    handler = type("Handler", (PortalHandler,), {"net": net, "static_dir": static_dir, "only_on": only_on})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="setup-page", daemon=True).start()
    return server


# ─── a pretend machine, to work on the setup page without one ──────────────

class MockSystem(System):
    """A Sorter with no cable and nothing saved. Joining works unless the
    password is "wrong-password"; "Faraway" is out of range, and "Cafe Guest"
    joins but has a sign-in page in the way of the internet."""

    AIR = [("HomeNet", 82, "WPA2"), ("Neighbours 5G", 61, "WPA2 WPA3"), ("Office", 54, "WPA2 802.1X"),
           ("Cafe Guest", 40, ""), ("Faraway", 12, "WPA2")]

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.saved: dict[str, str] = {}
        self.joined: str | None = None
        self.ap_on = False
        self.events: list[dict] = []
        self.join_record: dict | None = None
        self.cfg: dict = {}

    def _run(self, *cmd: str, timeout: float = 20):
        return subprocess.CompletedProcess(list(cmd), 0, "", "")

    def boot_id(self): return "mock"
    def clock_synced(self): return True
    def devices(self):
        return [{"iface": "eth0", "kind": "ethernet", "state": "unavailable"},
                {"iface": "wlan0", "kind": "wifi", "state": "connected" if self.joined else "disconnected"}]
    def device_info(self, iface):
        if iface == "wlan0" and self.joined:
            return {"address": "192.168.1.68", "internet": "full" if self.joined != "Cafe Guest" else "portal",
                    "uuid": self.joined}
        return {"address": None, "internet": "unknown", "uuid": None}
    def ssid_of(self, con_uuid): return con_uuid
    def carrier(self, iface): return False
    def tailscale_ip(self): return None
    def hostname(self): return self.cfg.get("hostname") or "sorter"
    def mdns_name(self): return f"{self.hostname()}.local"
    def mac(self, iface): return "02:11:22:ab:cd:ef"
    def saved_wifi(self): return list(self.saved)
    def write_wifi(self, ssid, password, hidden=False, security=""):
        replaced = {ssid: self.saved[ssid]} if ssid in self.saved else {}
        self.saved[ssid] = password
        return ssid, replaced
    def forget_wifi(self, con_uuid, replaced):
        self.saved.pop(con_uuid, None)
        self.saved.update(replaced)
    def join(self, con_uuid, iface):
        time.sleep(3)
        if con_uuid not in {s for s, *_ in self.AIR} or con_uuid == "Faraway":
            return "The Wi-Fi network could not be found"
        if self.saved.get(con_uuid) == "wrong-password":
            return "Connection activation failed: (7) Secrets were required, but not provided."
        self.joined = con_uuid
        return None
    def join_saved(self, ssid, iface): return self.join(ssid, iface)
    def scan(self, iface):
        time.sleep(1.5)
        return [{"ssid": s, "signal": g, "security": sec} for s, g, sec in self.AIR]
    def add_ap_iface(self, wifi_iface): return AP_IFACE
    def ap_up(self, iface, ssid):
        self.ap_on = True
        return None
    def ap_down(self): self.ap_on = False
    def ap_clients(self, iface): return 1 if self.ap_on else 0
    def fence(self, iface): pass
    def fenced(self, iface): return True
    def unfence(self, iface): pass
    def config(self): return dict(self.cfg)
    def update_config(self, **values): self.cfg.update({k: v for k, v in values.items() if v})
    def set_wifi_country(self, country): return False
    def imported(self): return ""
    def mark_imported(self, digest): pass
    def load_join(self): return self.join_record
    def save_join(self, join): self.join_record = join
    def load_events(self): return list(self.events)
    def save_event(self, event, keep): self.events = keep
    def software(self):
        if not self.joined:
            return {"state": "waiting", "step": None, "done": 3, "total": 10}
        done = min(10, 3 + int((time.monotonic() - self.t0) / 20))
        return {"state": "ready" if done == 10 else "installing", "step": None if done == 10 else "Installing packages",
                "done": done, "total": 10}
    def write_status(self, status): pass
    def announce_state(self): return None
    def set_announce(self, rendezvous_id): pass


# ─── running it ────────────────────────────────────────────────────────────

def take_down(sys_: System) -> None:
    """The setup network off the air, its fence gone."""
    sys_.ap_down()
    for d in sys_.devices():
        if d["kind"] == "wifi":
            sys_.unfence(d["iface"])


def start(net: Network, cfg: dict) -> None:
    net.event("Started")
    take_down(net.sys)  # a service that crashed left its setup network up, with no one to close it
    sync_wifi_country(net.sys, cfg)
    net.import_config_wifi(cfg)


def run(net: Network, cfg: dict) -> None:
    start(net, cfg)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while True:
            try:
                net.tick()
            except Exception:
                log.exception("tick failed")
            net.sys.sleep(TICK_S)
    finally:
        take_down(net.sys)  # stopped: nothing left on the air that nobody manages


def main() -> int:
    p = argparse.ArgumentParser(description="SorterOS network: online, or the setup network.")
    p.add_argument("--mock", action="store_true", help="a pretend Sorter, to work on the setup page")
    p.add_argument("--port", type=int, default=PORTAL_PORT)
    p.add_argument("--static-dir", type=Path, default=STATIC_DIR)
    p.add_argument("--single-radio", action="store_true", default=os.environ.get("SORTEROS_SINGLE_RADIO") == "1",
                   help="broadcast on the normal interface even if the radio could do both")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.mock:
        net = Network(MockSystem())
        serve_portal(net, "127.0.0.1", args.port, args.static_dir, only_on=None)
        log.info("pretend Sorter: http://127.0.0.1:%d/", args.port)
        run(net, {})
        return 0
    if shutil.which("nmcli") is None:
        log.error("NetworkManager isn't installed")
        return 1
    net = Network(System(), single_radio=args.single_radio)
    serve_portal(net, "0.0.0.0", args.port, args.static_dir, only_on=AP_ADDR)
    run(net, read_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
