"""Record every change to the camera USB path, so the next failure has evidence.

The cameras fail in ways that leave no trace once they recover: a hub half that
renegotiates at a lower speed, a SuperSpeed camera that silently re-attaches as
a USB2 device, a role that rebinds to a different /dev/video node. By the time
anyone notices the pictures are wrong, the kernel ring buffer has moved on and
the journal has rotated (the backend writes tens of KB/s while sorting, so even
a 500 MB cap is a couple of hours).

This watches the cheap, safe sources on a short poll — sysfs for USB topology,
the backend's own health endpoint — and writes a line only when something
changes. On a change it dumps the expensive detail too: negotiated formats,
kernel USB lines, role assignment, and what the machine was doing at the time.
Steady state costs one heartbeat line a minute.

Runs as sorter-usb-watch.service. Read it with:

    tail -f /var/log/sorter-usb-watch.log
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from typing import Any

LOG_PATH = "/var/log/sorter-usb-watch.log"
MAX_LOG_BYTES = 32 * 1024 * 1024
POLL_INTERVAL_S = 2.0
HEARTBEAT_INTERVAL_S = 60.0
BACKEND = "http://127.0.0.1:8000"
USB_DEVICES_DIR = "/sys/bus/usb/devices"
V4L_BY_PATH_DIR = "/dev/v4l/by-path"
PLATFORM_DRIVERS_DIR = "/sys/bus/platform/drivers"

# A camera or hub enumerated at 12M is on the OHCI companion, i.e. its
# high-speed link failed. Nothing errors when this happens — the driver just
# publishes a shrunken mode list, so every camera on that hub loses resolution
# and frame rate together and the machine keeps running on bad pictures.
FULL_SPEED = "12"
# Give a re-enumeration time to settle before judging it, and never let a
# recovery loop turn into a reset storm of its own.
DEGRADED_CONFIRM_S = 15.0
RECOVERY_COOLDOWN_S = 300.0
MAX_RECOVERIES_PER_HOUR = 3


def readAttr(path: str) -> str | None:
    try:
        with open(path) as handle:
            return handle.read().strip()
    except OSError:
        return None


def platformControllerFor(sysfs_path: str) -> str:
    """The platform device a USB device ultimately hangs off.

    Walking up to the nearest entry in /sys/bus/platform/devices lands on the
    thing that has a bind/unbind — `xhci-hcd.8.auto`, `fc880000.usb`. The naive
    parent-of-the-realpath is the root hub (`usb2`), which has no driver to
    rebind, so recovery would find nothing to do.
    """
    path = os.path.realpath(sysfs_path)
    while path not in ("/", ""):
        name = os.path.basename(path)
        if os.path.exists(os.path.join("/sys/bus/platform/devices", name)):
            return name
        path = os.path.dirname(path)
    return "?"


def usbDevices() -> dict[str, dict[str, str]]:
    """Every attached USB device by sysfs name, with the facts that matter here.

    Speed is the one to watch: a hub or camera that comes back at 12 or 480
    instead of 5000 is the failure, and it is invisible from userspace
    otherwise — nothing errors, the pictures just get worse.
    """
    devices: dict[str, dict[str, str]] = {}
    try:
        names = sorted(os.listdir(USB_DEVICES_DIR))
    except OSError:
        return devices
    for name in names:
        base = os.path.join(USB_DEVICES_DIR, name)
        vendor = readAttr(os.path.join(base, "idVendor"))
        if vendor is None:
            continue  # interfaces and root-hub links, not devices
        devices[name] = {
            "id": f"{vendor}:{readAttr(os.path.join(base, 'idProduct'))}",
            "product": readAttr(os.path.join(base, "product")) or "?",
            "speed": readAttr(os.path.join(base, "speed")) or "?",
            "controller": platformControllerFor(base),
        }
    return devices


def videoNodesByPath() -> dict[str, str]:
    """Stable physical-port name -> /dev/video node.

    The node numbers are reassigned on every re-enumeration; the by-path name
    is not, so a change here means a camera actually moved ports (or the roles
    are about to rebind to the wrong camera).
    """
    nodes: dict[str, str] = {}
    try:
        names = sorted(os.listdir(V4L_BY_PATH_DIR))
    except OSError:
        return nodes
    for name in names:
        target = os.path.realpath(os.path.join(V4L_BY_PATH_DIR, name))
        nodes[name] = os.path.basename(target)
    return nodes


def fetchJson(path: str, timeout: float = 2.0) -> Any:
    try:
        with urllib.request.urlopen(f"{BACKEND}{path}", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def cameraStatuses() -> dict[str, str]:
    health = fetchJson("/api/cameras/health")
    if not isinstance(health, dict):
        return {}
    return {
        role: str(entry.get("status"))
        for role, entry in health.items()
        if isinstance(entry, dict)
    }


def run(command: list[str], timeout: float = 10.0) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
        return (result.stdout or result.stderr or "").rstrip()
    except Exception as exc:
        return f"({' '.join(command)} failed: {exc})"


def negotiatedFormats(nodes: dict[str, str]) -> list[str]:
    """Ask each capture node what it is actually streaming.

    Only called when something already changed. G_FMT is read-only and does not
    disturb the backend's stream, but there is no reason to poke the cameras
    every two seconds to learn nothing.
    """
    lines: list[str] = []
    for by_path, node in sorted(nodes.items()):
        if not by_path.endswith("index0"):
            continue  # index1 is the metadata node, it has no picture
        out = run(["v4l2-ctl", "-d", f"/dev/{node}", "--get-fmt-video"])
        size = "?"
        pixel = "?"
        for line in out.splitlines():
            if "Width/Height" in line:
                size = line.split(":", 1)[1].strip()
            elif "Pixel Format" in line:
                pixel = line.split(":", 1)[1].strip()
        lines.append(f"  {node:<12} {size:<12} {pixel}  ({by_path})")
    return lines


def machineContext() -> list[str]:
    """What the machine was doing — the half of the correlation we keep losing.

    A USB collapse that only ever happens while the motors run, or only while
    the LEDs draw current, is a different bug from one that happens at idle.
    """
    lines: list[str] = []
    system = fetchJson("/api/system/status")
    if isinstance(system, dict):
        lines.append(f"  hardware_state: {system.get('hardware_state')}")
    state = fetchJson("/state")
    if isinstance(state, dict):
        lines.append(f"  sorter_state: {state.get('state')}")
    leds = fetchJson("/api/leds")
    if isinstance(leds, dict):
        lines.append(f"  led_brightness: {leds.get('brightness')}")
    config = fetchJson("/api/cameras/config")
    if isinstance(config, dict):
        lines.append(f"  camera_roles: {config}")
    load = readAttr("/proc/loadavg")
    if load:
        lines.append(f"  loadavg: {load}")
    temps = []
    for zone in range(0, 8):
        value = readAttr(f"/sys/class/thermal/thermal_zone{zone}/temp")
        if value and value.isdigit():
            temps.append(f"{int(value) / 1000:.0f}C")
    if temps:
        lines.append(f"  thermal: {' '.join(temps)}")
    return lines


def kernelUsbTail(count: int = 40) -> list[str]:
    out = run(["dmesg", "-T", "--level", "emerg,alert,crit,err,warn,notice,info"])
    keep = [
        line
        for line in out.splitlines()
        if "usb" in line.lower() or "uvc" in line.lower()
    ]
    return [f"  {line}" for line in keep[-count:]]


def isCameraGear(info: dict[str, str]) -> bool:
    product = info["product"].lower()
    return "hub" in product or "cam" in product


def degradedReason(state: dict[str, Any], superspeed_seen: set[str]) -> str | None:
    """Is the camera path in the state we keep finding it in?

    Two shapes, and they are the same underlying failure — the hub's uplink
    renegotiating downward. The USB2 half lands on the OHCI companion at 12M
    and every camera behind it loses its mode list; the SuperSpeed half has no
    slower rung to fall to, so its camera simply vanishes.
    """
    for name, info in state["usb"].items():
        if isCameraGear(info) and info["speed"] == FULL_SPEED:
            return f"{name} '{info['product'].strip()}' fell back to {FULL_SPEED}M"

    present = {info["id"] for info in state["usb"].values()}
    for device_id in sorted(superspeed_seen - present):
        return f"{device_id} was on SuperSpeed and is now gone"
    return None


def controllerForDriver(controller: str) -> str | None:
    try:
        drivers = os.listdir(PLATFORM_DRIVERS_DIR)
    except OSError:
        return None
    for driver in drivers:
        if os.path.exists(os.path.join(PLATFORM_DRIVERS_DIR, driver, controller)):
            return driver
    return None


def rebindControllers(controllers: list[str], log: "Log") -> None:
    """Tear the host controllers down and bring them back.

    This is the one deterministic lever there is over a wedged link: the hub
    will not renegotiate on its own, but it re-enumerates from scratch when the
    controller it hangs off is re-initialized — which is what recovered this
    machine by hand, without a reboot, after a 20 minute outage.
    """
    pairs = []
    for controller in controllers:
        driver = controllerForDriver(controller)
        if driver is None:
            log.write(f"recover: no driver found for {controller}, skipping")
            continue
        pairs.append((driver, controller))

    for driver, controller in pairs:
        log.write(f"recover: unbinding {controller} from {driver}")
        try:
            with open(os.path.join(PLATFORM_DRIVERS_DIR, driver, "unbind"), "w") as f:
                f.write(controller)
        except OSError as exc:
            log.write(f"recover: unbind {controller} failed: {exc}")

    time.sleep(3.0)

    for driver, controller in reversed(pairs):
        log.write(f"recover: binding {controller} to {driver}")
        try:
            with open(os.path.join(PLATFORM_DRIVERS_DIR, driver, "bind"), "w") as f:
                f.write(controller)
        except OSError as exc:
            log.write(f"recover: bind {controller} failed: {exc}")


def postJson(path: str, payload: dict[str, Any], timeout: float = 5.0) -> Any:
    request = urllib.request.Request(
        f"{BACKEND}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def rolesByPhysicalPort(nodes: dict[str, str]) -> dict[str, str]:
    """Freeze the role assignment against physical ports rather than node numbers.

    The backend stores each role as a bare /dev/video index, and those indices
    are handed out in enumeration order — so any re-enumeration silently moves
    the roles onto different cameras. Recovering the USB path therefore breaks
    the channel mapping as a side effect, which is worse than leaving it broken.
    Remember which physical port each role pointed at while it was correct, so
    it can be restored afterward.

    Stopgap: this belongs in the backend, keyed on the by-path name at
    assignment time. It lives here until then so recovery is safe to run.
    """
    config = fetchJson("/api/cameras/config")
    if not isinstance(config, dict):
        return {}
    node_to_port = {
        node: by_path for by_path, node in nodes.items() if by_path.endswith("index0")
    }
    mapping: dict[str, str] = {}
    for role, index in config.items():
        if not isinstance(index, int):
            continue
        port = node_to_port.get(f"video{index}")
        if port is not None:
            mapping[role] = port
    return mapping


def restoreRoles(mapping: dict[str, str], nodes: dict[str, str], log: "Log") -> None:
    port_to_node = {
        by_path: node for by_path, node in nodes.items() if by_path.endswith("index0")
    }
    payload: dict[str, Any] = {}
    for role, port in mapping.items():
        node = port_to_node.get(port)
        if node is None:
            log.write(f"restore: {role} port {port} is not present, leaving it alone")
            continue
        payload[role] = int(node.removeprefix("video"))
    if not payload:
        return
    current = fetchJson("/api/cameras/config")
    if isinstance(current, dict) and all(
        current.get(role) == index for role, index in payload.items()
    ):
        return
    log.write(f"restore: re-pinning roles to their physical ports: {payload}")
    if postJson("/api/cameras/assign", payload) is None:
        log.write("restore: the assign call failed")


def describeChanges(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    changes: list[str] = []

    old_usb = before.get("usb", {})
    new_usb = after.get("usb", {})
    for name in sorted(set(old_usb) | set(new_usb)):
        old = old_usb.get(name)
        new = new_usb.get(name)
        if old is None:
            changes.append(
                f"USB ATTACHED {name} {new['id']} '{new['product']}' "
                f"at {new['speed']}M on {new['controller']}"
            )
        elif new is None:
            changes.append(
                f"USB GONE     {name} {old['id']} '{old['product']}' "
                f"(was {old['speed']}M on {old['controller']})"
            )
        elif old != new:
            if old["speed"] != new["speed"]:
                changes.append(
                    f"USB SPEED    {name} '{new['product']}' "
                    f"{old['speed']}M -> {new['speed']}M"
                )
            if old["controller"] != new["controller"]:
                changes.append(
                    f"USB MOVED    {name} '{new['product']}' "
                    f"{old['controller']} -> {new['controller']}"
                )

    old_nodes = before.get("nodes", {})
    new_nodes = after.get("nodes", {})
    for by_path in sorted(set(old_nodes) | set(new_nodes)):
        old_node = old_nodes.get(by_path)
        new_node = new_nodes.get(by_path)
        if old_node != new_node:
            changes.append(f"V4L NODE     {by_path}: {old_node} -> {new_node}")

    old_status = before.get("cameras", {})
    new_status = after.get("cameras", {})
    for role in sorted(set(old_status) | set(new_status)):
        old_value = old_status.get(role)
        new_value = new_status.get(role)
        if old_value != new_value:
            changes.append(f"CAMERA       {role}: {old_value} -> {new_value}")

    return changes


def buildState() -> dict[str, Any]:
    return {
        "usb": usbDevices(),
        "nodes": videoNodesByPath(),
        "cameras": cameraStatuses(),
    }


def summarize(state: dict[str, Any]) -> str:
    speeds = " ".join(
        f"{info['product'].strip()}@{info['speed']}M"
        for info in state["usb"].values()
        if "Hub" in info["product"] or "am" in info["product"]
    )
    statuses = " ".join(f"{role}={value}" for role, value in state["cameras"].items())
    return f"{speeds} | {statuses}"


class Log:
    def __init__(self, path: str) -> None:
        self._path = path
        self._handle = open(path, "a", buffering=1)

    def write(self, line: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self._handle.write(f"{stamp} {line}\n")
        self._rotateIfLarge()

    def writeBlock(self, lines: list[str]) -> None:
        for line in lines:
            self._handle.write(f"{line}\n")
        self._handle.write("\n")
        self._rotateIfLarge()

    def _rotateIfLarge(self) -> None:
        try:
            if self._handle.tell() < MAX_LOG_BYTES:
                return
            self._handle.close()
            os.replace(self._path, f"{self._path}.1")
            self._handle = open(self._path, "a", buffering=1)
        except OSError:
            pass


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recover",
        action="store_true",
        help="re-initialize the host controllers when the camera path degrades",
    )
    parser.add_argument(
        "--recover-now",
        action="store_true",
        help="run one recovery immediately and exit (for testing the lever)",
    )
    args = parser.parse_args()

    log = Log(LOG_PATH)
    state = buildState()

    # Controllers are remembered while things are healthy, because the ones we
    # need to reset are exactly the ones whose devices have disappeared by the
    # time we want to reset them.
    controllers = sorted(
        {info["controller"] for info in state["usb"].values() if isCameraGear(info)}
    )
    superspeed_seen = {
        info["id"] for info in state["usb"].values() if info["speed"] == "5000"
    }

    if args.recover_now:
        log.write(f"manual recovery requested for {controllers}")
        rebindControllers(controllers, log)
        time.sleep(8.0)
        log.write(f"manual recovery done | {summarize(buildState())}")
        return

    log.write(
        f"watch started (recover={'on' if args.recover else 'off'}) | "
        f"{summarize(state)}"
    )
    log.writeBlock(
        ["  --- baseline ---"]
        + negotiatedFormats(state["nodes"])
        + machineContext()
    )

    last_heartbeat = time.monotonic()
    degraded_since: float | None = None
    last_recovery = 0.0
    recoveries: list[float] = []
    role_ports = rolesByPhysicalPort(state["nodes"])
    log.write(f"roles pinned to physical ports: {role_ports}")

    while True:
        time.sleep(POLL_INTERVAL_S)
        try:
            new_state = buildState()
        except Exception as exc:
            log.write(f"watch error: {exc}")
            continue

        healthy = [
            info["controller"]
            for info in new_state["usb"].values()
            if isCameraGear(info)
        ]
        changes = describeChanges(state, new_state)
        if changes:
            for change in changes:
                log.write(change)
            # The detail is worth its cost only here, at the moment it changed.
            log.writeBlock(
                ["  --- detail ---"]
                + negotiatedFormats(new_state["nodes"])
                + machineContext()
                + ["  --- kernel ---"]
                + kernelUsbTail()
            )
            last_heartbeat = time.monotonic()
        elif time.monotonic() - last_heartbeat >= HEARTBEAT_INTERVAL_S:
            log.write(f"steady | {summarize(new_state)}")
            last_heartbeat = time.monotonic()

        reason = degradedReason(new_state, superspeed_seen)
        now = time.monotonic()
        if reason is None:
            if degraded_since is not None:
                log.write("degraded state cleared")
                restoreRoles(role_ports, new_state["nodes"], log)
            degraded_since = None
            controllers = sorted(set(healthy)) or controllers
            if new_state["nodes"] != state["nodes"]:
                # Nodes were renumbered while healthy, so the roles have moved
                # onto the wrong cameras even though nothing looks wrong.
                restoreRoles(role_ports, new_state["nodes"], log)
            elif all(value == "online" for value in new_state["cameras"].values()):
                learned = rolesByPhysicalPort(new_state["nodes"])
                if learned:
                    role_ports = learned
            superspeed_seen |= {
                info["id"] for info in new_state["usb"].values() if info["speed"] == "5000"
            }
        else:
            if degraded_since is None:
                degraded_since = now
                log.write(f"DEGRADED: {reason}")
            elif (
                args.recover
                and now - degraded_since >= DEGRADED_CONFIRM_S
                and now - last_recovery >= RECOVERY_COOLDOWN_S
            ):
                recoveries = [t for t in recoveries if now - t < 3600.0]
                if len(recoveries) >= MAX_RECOVERIES_PER_HOUR:
                    log.write(
                        "still degraded, but recovery cap for this hour is spent — "
                        "leaving it alone so the log stays readable"
                    )
                    last_recovery = now
                else:
                    log.write(f"recovering: {reason}")
                    rebindControllers(controllers, log)
                    recoveries.append(now)
                    last_recovery = now
                    degraded_since = None

        state = new_state


if __name__ == "__main__":
    main()
