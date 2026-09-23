"""
SorterOS network bring-up, once per boot.

In order:
  0. Ethernet: a cable with DHCP comes up on its own. Nothing to do.
  1. Wi-Fi given to the setup site before flashing: imported into
     NetworkManager (once per distinct network/password) and joined like any
     saved network. Saved networks get WIFI_WAIT_S to connect, no cable
     WIRED_WAIT_S.
  2. Still offline: broadcast the SorterOS-Setup-XXXXXX network with the setup
     page (sorteros-portal) until the machine is online, by any of:
       - the page connects it to a network (the portal tears the setup
         network down and signals PORTAL_DONE);
       - a cable is plugged in;
       - a saved network comes back (a router slower to boot than the Pi
         after a power cut): every RETRY_EVERY_S, when nobody is on the setup
         network, it is dropped for one try at the saved networks.

Nothing is decided from a flag written once: each boot looks at whether the
machine is actually online. A wrong password costs one bounded try per boot,
never a loop, and never locks the setup network away. Runs only at boot, so it
never takes the network down in the middle of sorting.

Everything that touches the system goes through `System`; the decisions in
`bring_up` and `hotspot` are tested against a fake (test/test_network.py).
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path

try:
    import tomllib  # type: ignore
except ImportError:  # Python 3.10 on the image
    import tomli as tomllib  # type: ignore

log = logging.getLogger("sorteros-network")

CONFIG_PATH = Path("/etc/sorteros-config.toml")
STATE_DIR = Path("/var/lib/sorteros")
IMPORTED_PATH = STATE_DIR / "wifi-imported"
BACKUP_DIR = STATE_DIR / "wifi-backups"
NM_DIR = Path("/etc/NetworkManager/system-connections")
RUN_DIR = Path("/run/sorteros")
PORTAL_DONE = RUN_DIR / "portal-connected"
PORTAL_ACTIVITY = RUN_DIR / "portal-activity"
PORTAL_CMD = [
    "/usr/bin/python3", "/usr/local/sbin/sorteros-portal.py",
    "--mode", "ap", "--host", "0.0.0.0", "--port", "80", "--static-dir", "/var/www/portal",
]
# Split so the setup site, which scans the raw image for the marker lines,
# never finds them in this file.
CFG_END_MARKER = "# __SORTEROS_CFG" + "_END__"

# The Sorter UI holds port 80 once first boot is done. While the setup network
# is up the machine is offline and the UI unreachable anyway, so it steps
# aside for the setup page and comes back after.
UI_UNITS = ("sorter-ui-dev.service", "sorter-ui.service")

AP_CON = "sorteros-ap"
AP_GATEWAY = "10.42.0.1/24"
WIRED_WAIT_S = 45
WIFI_WAIT_S = 90
WIFI_DEVICE_WAIT_S = 15
RETRY_EVERY_S = 180
PORTAL_IDLE_S = 120
CONNECT_TIMEOUT_S = 30
TICK_S = 2

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


def nm_keyfile(ssid: str, password: str, hidden: bool = False) -> str:
    body = f"[connection]\nid={ssid}\ntype=wifi\nautoconnect=true\n\n[wifi]\nssid={ssid}\nmode=infrastructure\n"
    if hidden:
        body += "hidden=true\n"
    if password:
        body += f"\n[wifi-security]\nkey-mgmt=wpa-psk\npsk={password}\n"
    return body + "\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n"


class System:
    """NetworkManager, ip and the portal process, for real."""

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

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def wifi_iface(self) -> str | None:
        """The first Wi-Fi device NetworkManager manages: wlan0 for the M.2
        module, wlx<mac> for a USB adapter."""
        for line in self._run("nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device").stdout.splitlines():
            device, kind, state = (line.split(":") + ["", ""])[:3]
            if kind == "wifi" and state != "unmanaged":
                return device
        return None

    def online(self) -> bool:
        """A default route on any interface: Ethernet, or a joined Wi-Fi
        network. The setup network (NM shared mode) never adds one."""
        return bool(self._run("ip", "-4", "route", "show", "default").stdout.strip())

    def saved_wifi(self) -> list[str]:
        names = []
        for line in self._run("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show").stdout.splitlines():
            name, _, kind = line.rpartition(":")
            name = name.replace("\\:", ":")
            if kind == "802-11-wireless" and name != AP_CON:
                names.append(name)
        return names

    def write_wifi(self, ssid: str, password: str) -> None:
        body = nm_keyfile(ssid, password)
        for d in (NM_DIR, BACKUP_DIR):
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{ssid}.nmconnection"
            f.write_text(body)
            f.chmod(0o600)
        self._run("nmcli", "connection", "reload")

    def connect(self, name: str, iface: str) -> bool:
        r = self._run("nmcli", "--wait", str(CONNECT_TIMEOUT_S), "connection", "up", name,
                      "ifname", iface, timeout=CONNECT_TIMEOUT_S + 10)
        if r.returncode != 0:
            log.info("joining %s failed: %s", name, (r.stderr or r.stdout).strip())
        return r.returncode == 0

    def ap_up(self, iface: str) -> str:
        mac = Path(f"/sys/class/net/{iface}/address")
        suffix = (mac.read_text().strip() if mac.exists() else "00:00:00:00:00:00").replace(":", "")[-6:].upper()
        ssid = f"SorterOS-Setup-{suffix}"
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

    def start_portal(self) -> None:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        PORTAL_DONE.unlink(missing_ok=True)
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

    def portal_connected(self) -> bool:
        return PORTAL_DONE.exists()

    def portal_idle_s(self) -> float:
        try:
            return time.time() - PORTAL_ACTIVITY.stat().st_mtime
        except OSError:
            return float("inf")

    def imported(self) -> str:
        try:
            return IMPORTED_PATH.read_text().strip()
        except OSError:
            return ""

    def mark_imported(self, digest: str) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        IMPORTED_PATH.write_text(digest + "\n")


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


def try_saved(sys_: System, iface: str) -> bool:
    for name in sys_.saved_wifi():
        if sys_.connect(name, iface) and wait_online(sys_, 10):
            log.info("joined %s", name)
            return True
    return False


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
    ssid = sys_.ap_up(iface)
    sys_.start_portal()
    log.info("offline: broadcasting %s with the setup page", ssid)
    last_retry = sys_.now()
    while True:
        sys_.sleep(TICK_S)
        if sys_.portal_connected():
            if wait_online(sys_, 20):
                log.info("the setup page connected the machine")
                sys_.stop_portal()
                sys_.ap_down()
                return 0
            log.warning("the setup page joined a network but no route came up: back to the setup network")
            sys_.stop_portal()
            ssid = sys_.ap_up(iface)
            sys_.start_portal()
            continue
        if sys_.online():
            log.info("online (a cable, or a network came back): closing the setup network")
            sys_.stop_portal()
            sys_.ap_down()
            return 0
        if not sys_.portal_alive():
            log.warning("setup page stopped; restarting it")
            sys_.start_portal()
        if (
            sys_.now() - last_retry >= RETRY_EVERY_S
            and sys_.saved_wifi()
            and not sys_.ap_has_clients(iface)
            and sys_.portal_idle_s() >= PORTAL_IDLE_S
        ):
            log.info("nobody is on the setup network: trying the saved networks once")
            sys_.stop_portal()
            sys_.ap_down()
            if try_saved(sys_, iface):
                return 0
            ssid = sys_.ap_up(iface)
            sys_.start_portal()
            last_retry = sys_.now()


def bring_up(sys_: System, cfg: dict) -> int:
    iface = None
    deadline = sys_.now() + WIFI_DEVICE_WAIT_S
    while iface is None and sys_.now() < deadline:
        iface = sys_.wifi_iface()
        if iface is None:
            sys_.sleep(1)
    import_config_wifi(sys_, cfg)
    wait = WIFI_WAIT_S if iface and sys_.saved_wifi() else WIRED_WAIT_S
    if wait_online(sys_, wait):
        log.info("online")
        return 0
    if iface is None:
        log.warning("offline and there is no Wi-Fi device: waiting for a cable")
        while not sys_.online():
            sys_.sleep(10)
        return 0
    return hotspot(sys_, iface)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    return bring_up(System(), read_config())


if __name__ == "__main__":
    raise SystemExit(main())
