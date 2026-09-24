"""
SorterOS network bring-up, once per boot.

In order:
  0. Ethernet: a cable with DHCP comes up on its own. Nothing to do.
  1. Wi-Fi given to the setup site before flashing: saved in NetworkManager
     (once per distinct network/password) and joined like any saved network.
     Saved networks get WIFI_WAIT_S to connect, no cable WIRED_WAIT_S.
  2. Still offline: scan for networks, then broadcast SorterOS-Setup-XXXXXX
     with the setup page (sorteros-portal), which offers that scan.

Joining a network from the setup page is a restart. The Orange Pi 5's Wi-Fi
(AP6275P, Broadcom's bcmdhd) can't join a network after it has been
broadcasting until it's restarted, and can't scan while broadcasting. So the
page writes what was chosen to PENDING_PATH and restarts the Pi; at the next
boot this service saves it and joins it. If that fails, the profile it
replaced comes back, FAILED_PATH tells the page which network and why (the
password, not found, no address), and the setup network comes back: on the
phone, the setup network reappearing is the sign it didn't work.

This file is the only thing that writes Wi-Fi profiles, as keyfiles: SSIDs as
bytes (any SSID is legal, "/" and all), the rest escaped for GLib's key file
format (a backslash or an edge space in a password would otherwise be lost),
one profile per SSID.

While the setup network is up, a saved network that comes back (a router
slower to boot than the Pi after a power cut) is picked up by restarting, when
nobody is using the setup network: after RETRY_FIRST_S, doubling each time up
to RETRY_MAX_S. A cable plugged in ends it at once.

Once online, if the setup page left a rendezvous, the Pi's address (and the
network it joined) goes to Hive encrypted to the key that the phone's Hive
page made, so only that page can read it.

Nothing hangs off a flag written once: each boot looks at whether the machine
is actually online. Runs only at boot, so it never takes the network down in
the middle of sorting. Everything that touches the system goes through
`System`; the decisions are tested against a fake (test/test_network.py).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

try:
    import tomllib  # type: ignore
except ImportError:  # Python 3.10 on the image
    import tomli as tomllib  # type: ignore

log = logging.getLogger("sorteros-network")

CONFIG_PATH = Path("/etc/sorteros-config.toml")
STATE_DIR = Path("/var/lib/sorteros")
IMPORTED_PATH = STATE_DIR / "wifi-imported"
PENDING_PATH = STATE_DIR / "join-pending.json"
FAILED_PATH = STATE_DIR / "join-failed.json"
RETRY_COUNT_PATH = STATE_DIR / "saved-retry-count"
ANNOUNCE_PATH = STATE_DIR / "ip-announce.json"
NM_DIR = Path("/etc/NetworkManager/system-connections")
RUN_DIR = Path("/run/sorteros")
NETWORKS_PATH = RUN_DIR / "networks.json"
PORTAL_ACTIVITY = RUN_DIR / "portal-activity"
PORTAL_CMD = [
    "/usr/bin/python3", "/usr/local/sbin/sorteros-portal.py",
    "--mode", "ap", "--host", "0.0.0.0", "--port", "80", "--static-dir", "/var/www/portal",
]
# Split so the setup site, which scans the raw image for the marker lines,
# never finds them in this file.
CFG_END_MARKER = "# __SORTEROS_CFG" + "_END__"
SETUP_SSID_PREFIX = "SorterOS-Setup-"

# The Sorter UI holds port 80 once first boot is done. While the setup network
# is up the machine is offline and the UI unreachable anyway, so it steps
# aside for the setup page and comes back after.
UI_UNITS = ("sorter-ui-dev.service", "sorter-ui.service")

AP_CON = "sorteros-ap"
AP_GATEWAY = "10.42.0.1/24"
WIRED_WAIT_S = 45
WIFI_WAIT_S = 90
WIFI_DEVICE_WAIT_S = 15
JOIN_WAIT_S = 90
RETRY_FIRST_S = int(os.environ.get("SORTEROS_RETRY_S", "600"))
RETRY_MAX_S = 7200
PORTAL_IDLE_S = 120
ANNOUNCE_WINDOW_S = 900
ANNOUNCE_EVERY_S = 10
# Hive sits behind Cloudflare, which refuses urllib's own "Python-urllib/3.x"
# with a 403. Any honest name gets through.
HTTP_HEADERS = {"User-Agent": "SorterOS"}
TICK_S = 2
REBOOT_CMD = os.environ.get("SORTEROS_REBOOT_CMD", "systemctl reboot").split()

_CONTROL = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|[\x00-\x08\x0b-\x1f]")


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


def join_failure_reason(error: str) -> str:
    """What NetworkManager's error means for the person on the setup page."""
    e = error.lower()
    if "secrets were required" in e or "supplicant" in e or "4-way" in e:
        return "password"
    if "could not be found" in e or "no network with ssid" in e:
        return "not_found"
    if "ip configuration" in e or "dhcp" in e:
        return "no_address"
    return "other"


def _write_private(path: Path, text: str) -> None:
    """Write a root-only file whole or not at all: a power cut mid-write
    leaves the old one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


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
    strongest first, names exact, hidden networks and the setup network
    itself left out."""
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


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


class System:
    """NetworkManager, ip, the portal process and Hive, for real."""

    def __init__(self) -> None:
        self._portal: subprocess.Popen | None = None

    def _run(self, *cmd: str, timeout: float = 20) -> subprocess.CompletedProcess:
        try:
            p = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(list(cmd), 124, "", "timed out")
        p.stdout = _CONTROL.sub("", p.stdout or "")
        p.stderr = _CONTROL.sub("", p.stderr or "")
        return p

    # clock
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    # network
    def wifi_iface(self) -> str | None:
        """The first Wi-Fi device NetworkManager manages: wlan0 for the M.2
        module, wlx<mac> for a USB adapter."""
        for line in self._run("nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device").stdout.splitlines():
            device, kind, state = (nmcli_fields(line) + ["", ""])[:3]
            if kind == "wifi" and state != "unmanaged":
                return device
        return None

    def online(self) -> bool:
        """A default route on any interface: Ethernet, or a joined Wi-Fi
        network. The setup network (NM shared mode) never adds one."""
        return bool(self._run("ip", "-4", "route", "show", "default").stdout.strip())

    def joined_ssid(self) -> str | None:
        for line in self._run("nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi", "list", "--rescan", "no").stdout.splitlines():
            active, ssid = (nmcli_fields(line) + [""])[:2]
            if active == "yes":
                return ssid or None
        return None

    def lan_ip(self) -> str | None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))  # selects the egress interface; sends nothing
            return s.getsockname()[0]
        except OSError:
            return None
        finally:
            s.close()

    def saved_wifi(self) -> list[str]:
        names = []
        for line in self._run("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show").stdout.splitlines():
            name, kind = (nmcli_fields(line) + [""])[:2]
            if kind == "802-11-wireless" and name != AP_CON:
                names.append(name)
        return names

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
            if self._run("nmcli", "--escape", "no", "-g", "802-11-wireless.ssid", "connection", "show",
                         "uuid", con_uuid).stdout.rstrip("\n") != ssid:
                continue
            try:
                replaced[filename] = Path(filename).read_text()
                Path(filename).unlink()
            except OSError:
                pass
        new_uuid = str(uuid.uuid4())
        _write_private(profile_path(ssid), nm_keyfile(ssid, password, new_uuid, hidden, security))
        self._run("nmcli", "connection", "reload")
        return new_uuid, replaced

    def join(self, con_uuid: str, iface: str) -> str | None:
        """Bring a saved profile up on `iface`. None once it's joined with an
        address, else NetworkManager's reason."""
        r = self._run("nmcli", "--wait", str(JOIN_WAIT_S), "connection", "up", "uuid", con_uuid,
                      "ifname", iface, timeout=JOIN_WAIT_S + 15)
        if r.returncode == 0:
            return None
        # nmcli can lead with warnings and trail a journalctl hint; keep the error.
        lines = [_CONTROL.sub("", line).strip() for line in (r.stderr + r.stdout).splitlines()]
        errors = [line.removeprefix("Error: ") for line in lines if line.startswith("Error:")]
        return errors[0] if errors else next((line for line in lines if line), f"nmcli exited {r.returncode}")

    def forget_wifi(self, con_uuid: str, replaced: dict[str, str]) -> None:
        """Undo write_wifi: drop the new profile, put back the ones it replaced."""
        self._run("nmcli", "connection", "delete", "uuid", con_uuid)
        for filename, text in replaced.items():
            _write_private(Path(filename), text)
        self._run("nmcli", "connection", "reload")

    def scan(self, iface: str) -> list[dict]:
        r = self._run("nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                      "ifname", iface, "--rescan", "yes", timeout=30)
        return parse_scan(r.stdout)

    def write_networks(self, networks: list[dict]) -> None:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        NETWORKS_PATH.write_text(json.dumps(networks))

    def ap_up(self, iface: str) -> str:
        mac = Path(f"/sys/class/net/{iface}/address")
        suffix = (mac.read_text().strip() if mac.exists() else "00:00:00:00:00:00").replace(":", "")[-6:].upper()
        ssid = f"{SETUP_SSID_PREFIX}{suffix}"
        self._run("nmcli", "connection", "delete", AP_CON)
        self._run(
            "nmcli", "connection", "add", "type", "wifi", "ifname", iface, "con-name", AP_CON,
            "autoconnect", "no", "ssid", ssid,
            "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg", "802-11-wireless.channel", "6",
            "ipv4.method", "shared", "ipv4.addresses", AP_GATEWAY, "ipv6.method", "ignore",
        )
        r = self._run("nmcli", "--wait", "20", "connection", "up", AP_CON, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"setup network would not start: {(r.stderr or r.stdout).strip()}")
        return ssid

    def ap_down(self) -> None:
        self._run("nmcli", "connection", "down", AP_CON)
        self._run("nmcli", "connection", "delete", AP_CON)

    def ap_has_clients(self, iface: str) -> bool:
        if shutil.which("iw") is None:
            return False
        return "Station" in self._run("iw", "dev", iface, "station", "dump").stdout

    def reboot(self) -> None:
        self._run(*REBOOT_CMD, timeout=30)

    # the Sorter UI
    def ui_stop(self) -> list[str]:
        stopped = []
        for unit in UI_UNITS:
            if self._run("systemctl", "is-active", "--quiet", unit).returncode == 0:
                self._run("systemctl", "stop", unit, timeout=60)
                stopped.append(unit)
        return stopped

    def ui_start(self, units: list[str]) -> None:
        for unit in units:
            self._run("systemctl", "start", unit, timeout=60)

    # the setup page
    def start_portal(self) -> None:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        PORTAL_ACTIVITY.unlink(missing_ok=True)
        self._portal = subprocess.Popen(PORTAL_CMD)

    def portal_alive(self) -> bool:
        return self._portal is not None and self._portal.poll() is None

    def stop_portal(self) -> None:
        if self._portal is None:
            return
        self._portal.terminate()
        try:
            self._portal.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._portal.kill()
        self._portal = None

    def portal_idle_s(self) -> float:
        try:
            return time.time() - PORTAL_ACTIVITY.stat().st_mtime
        except OSError:
            return float("inf")

    # state that survives the restart
    def imported(self) -> str:
        try:
            return IMPORTED_PATH.read_text().strip()
        except OSError:
            return ""

    def mark_imported(self, digest: str) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        IMPORTED_PATH.write_text(digest + "\n")

    def pending(self) -> dict | None:
        return _read_json(PENDING_PATH)

    def clear_pending(self) -> None:
        PENDING_PATH.unlink(missing_ok=True)

    def record_failure(self, ssid: str, reason: str, detail: str) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        FAILED_PATH.write_text(json.dumps({"ssid": ssid, "reason": reason, "detail": detail, "at": time.time()}))

    def clear_failure(self) -> None:
        FAILED_PATH.unlink(missing_ok=True)

    def retry_count(self) -> int:
        try:
            return int(RETRY_COUNT_PATH.read_text())
        except (OSError, ValueError):
            return 0

    def set_retry_count(self, n: int) -> None:
        if n:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            RETRY_COUNT_PATH.write_text(f"{n}\n")
        else:
            RETRY_COUNT_PATH.unlink(missing_ok=True)

    # the encrypted address for the phone's Hive page
    def announce_state(self) -> dict | None:
        return _read_json(ANNOUNCE_PATH)

    def clear_announce(self) -> None:
        ANNOUNCE_PATH.unlink(missing_ok=True)

    def rendezvous(self, state: dict) -> tuple[str | None, bool]:
        """The public key the phone's Hive page posted (None until it has)
        and whether Hive already holds an address for it. Raises
        URLError/OSError when Hive can't be reached or refuses."""
        base = f"{str(state['hive_url']).rstrip('/')}/api/machine-ip-lookup/{state['rendezvous_id']}"
        pubkey = _get_json(f"{base}/pubkey").get("pubkey")
        ready = _get_json(base).get("ready")
        return (pubkey if isinstance(pubkey, str) and pubkey else None), bool(ready)

    def publish_address(self, state: dict, pubkey: str, payload: dict) -> None:
        """Encrypt `payload` to the phone's public key and hand it to Hive,
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


def import_config_wifi(sys_: System, cfg: dict) -> bool:
    """Hand the setup site's Wi-Fi to NetworkManager, once per distinct
    network and password. NetworkManager joins it like any saved network."""
    wifi = wifi_from_config(cfg)
    if wifi is None:
        return False
    digest = hashlib.sha256("\0".join(wifi).encode()).hexdigest()
    if sys_.imported() == digest:
        return False
    sys_.write_wifi(*wifi)
    sys_.mark_imported(digest)
    log.info("saved Wi-Fi network %r from the setup config", wifi[0])
    return True


def wait_online(sys_: System, seconds: float) -> bool:
    deadline = sys_.now() + seconds
    while True:
        if sys_.online():
            return True
        if sys_.now() >= deadline:
            return False
        sys_.sleep(TICK_S)


def announce_address(sys_: System) -> None:
    """If the setup page left a rendezvous, keep the phone's Hive page told
    where the machine is until the window closes: a reloaded page brings a
    new key, and a restarted Hive forgets what it held."""
    state = sys_.announce_state()
    if not state or not state.get("rendezvous_id") or not state.get("hive_url"):
        return
    payload = {
        "ip": sys_.lan_ip(),
        "hostname": f"{socket.gethostname() or 'sorter'}.local",
        "port": 80,
        "ssid": sys_.joined_ssid(),
    }
    # From now, on this boot's clock: a Pi with no battery clock can come
    # back from days unplugged with its wall clock days behind until it
    # reaches the internet, so the setup page's timestamp can't be trusted.
    deadline = sys_.now() + ANNOUNCE_WINDOW_S
    last_error = ""
    sent_to = None
    while sys_.now() < deadline:
        try:
            pubkey, ready = sys_.rendezvous(state)
            if pubkey and (pubkey != sent_to or not ready):
                sys_.publish_address(state, pubkey, payload)
                sent_to = pubkey
                log.info("gave the setup page's Hive link the address: %s on %s",
                         payload["ip"], payload["ssid"] or "Ethernet")
        except (urllib.error.URLError, OSError) as e:
            if str(e) != last_error:
                log.warning("can't reach Hive for the address announce yet: %s", e)
                last_error = str(e)
        except Exception as e:
            log.warning("address announce failed: %s", e)
            break
        sys_.sleep(ANNOUNCE_EVERY_S)
    sys_.clear_announce()


def online_now(sys_: System) -> int:
    sys_.set_retry_count(0)
    announce_address(sys_)
    return 0


def hotspot(sys_: System, iface: str) -> int:
    """Broadcast the setup network until the machine is online, with the
    Sorter UI stepped aside so the setup page has port 80."""
    ui = sys_.ui_stop()
    if ui:
        log.info("stopped %s for the setup page", ", ".join(ui))
    try:
        return _hotspot(sys_, iface)
    finally:
        sys_.ui_start(ui)


def _hotspot(sys_: System, iface: str) -> int:
    # Scan first: some chips (the AP6275P) can't scan while they broadcast.
    networks = sys_.scan(iface)
    if not networks:  # the radio can take a moment after boot
        sys_.sleep(5)
        networks = sys_.scan(iface)
    sys_.write_networks(networks)
    ssid = sys_.ap_up(iface)
    sys_.start_portal()
    log.info("offline: broadcasting %s with the setup page (%d networks to offer)", ssid, len(networks))
    started = sys_.now()
    tries = sys_.retry_count()
    retry_after = min(RETRY_FIRST_S * 2 ** tries, RETRY_MAX_S)
    while True:
        sys_.sleep(TICK_S)
        if sys_.online():
            log.info("online over a cable: closing the setup network")
            sys_.stop_portal()
            sys_.ap_down()
            return online_now(sys_)
        if not sys_.portal_alive():
            log.warning("setup page stopped; restarting it")
            sys_.start_portal()
        if (
            sys_.now() - started >= retry_after
            and sys_.saved_wifi()
            and not sys_.ap_has_clients(iface)
            and sys_.portal_idle_s() >= PORTAL_IDLE_S
        ):
            log.info("nobody has used the setup network for %d min: restarting to try the saved networks",
                     retry_after // 60)
            sys_.set_retry_count(tries + 1)
            sys_.stop_portal()
            sys_.reboot()
            return 0


def join_pending(sys_: System, iface: str, pending: dict) -> bool:
    """Save and join the network chosen on the setup page before the restart.
    A failed join puts back what it replaced and tells the page why."""
    ssid = pending.get("ssid")
    if not isinstance(ssid, str) or not ssid:
        return False
    con_uuid, replaced = sys_.write_wifi(ssid, str(pending.get("password") or ""),
                                         bool(pending.get("hidden")), str(pending.get("security") or ""))
    error = sys_.join(con_uuid, iface)
    if error is None:
        log.info("joined %s, given on the setup page", ssid)
        sys_.clear_failure()
        return True
    reason = join_failure_reason(error)
    log.warning("couldn't join %s, given on the setup page (%s): %s", ssid, reason, error)
    sys_.record_failure(ssid, reason, error)
    sys_.forget_wifi(con_uuid, replaced)
    return False


def bring_up(sys_: System, cfg: dict) -> int:
    # A service restarted without the machine (after a crash) finds its own
    # setup network still up, which keeps saved networks from joining and
    # the chip from scanning.
    sys_.ap_down()
    iface = None
    deadline = sys_.now() + WIFI_DEVICE_WAIT_S
    while iface is None and sys_.now() < deadline:
        iface = sys_.wifi_iface()
        if iface is None:
            sys_.sleep(1)
    import_config_wifi(sys_, cfg)
    pending = sys_.pending()
    if pending:
        sys_.clear_pending()  # one attempt; it holds the password
        if iface and join_pending(sys_, iface, pending):
            return online_now(sys_)
    wait = WIFI_WAIT_S if iface and sys_.saved_wifi() else WIRED_WAIT_S
    if wait_online(sys_, wait):
        log.info("online")
        return online_now(sys_)
    if iface is None:
        log.warning("offline and there is no Wi-Fi device: waiting for a cable")
        while not sys_.online():
            sys_.sleep(10)
        return online_now(sys_)
    return hotspot(sys_, iface)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    return bring_up(System(), read_config())


if __name__ == "__main__":
    raise SystemExit(main())
