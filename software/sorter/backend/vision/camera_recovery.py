"""Soft recovery for USB cameras that come back wrong without disconnecting.

The failure this exists for: the powered USB hub the C-channel cameras hang off
occasionally fails its high-speed handshake on the EHCI controller
(``device descriptor read/64, error -71`` → ``unable to enumerate USB device``)
and the kernel hands the port to the OHCI companion, where the whole tree
re-enumerates at FULL speed (``not running at top speed; connect to a high
speed hub``). Nothing disconnects — /dev/videoN still opens and still yields
frames — but at 12 Mbit/s these UVC cameras only advertise 640x480@5,
640x360@5, 352x288@20, 320x240@20, 160x120@30. A request for 1280x720@30
silently lands on 640x480@5, which is why the feed shows up squished (4:3
pixels stretched into a 16:9 layout), washed out (auto-exposure is free to use
a 200 ms integration time at 5 fps) and smeared (5 fps of motion blur).

Only a real electrical disconnect makes ehci-hcd reclaim port ownership from
its companion, which is why replugging the cable is the only thing that has
worked so far. The ladder below walks from the cheapest reset to the ones that
actually produce that disconnect, and every rung is verified by re-reading the
negotiated format rather than assumed to have worked.
"""

from __future__ import annotations

import fcntl
import logging
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)

# _IO('U', 20) — the ioctl behind the `usbreset` utility.
USBDEVFS_RESET = 0x5514

HIGH_SPEED_MBPS = 480

SYSFS_VIDEO_ROOT = "/sys/class/video4linux"
SYSFS_USB_DEVICES = "/sys/bus/usb/devices"

_PLATFORM_USB_DRIVERS = ("ehci-platform", "ohci-platform", "xhci-hcd", "dwc3")


@dataclass
class CameraUsbDevice:
    sysfs_path: str
    # `devpath` is the hub port chain ("1.1"), the only identifier that survives
    # the controller move — bus number, device number, /dev/videoN and the
    # by-path symlink all change when the tree lands on the companion.
    devpath: str
    busnum: int
    devnum: int
    speed_mbps: float | None
    parent_sysfs_path: str | None
    port_sysfs_path: str | None
    parent_port_sysfs_path: str | None
    controller_name: str | None
    controller_driver: str | None


def _readSysfsText(path: str) -> str | None:
    try:
        with open(path, "r") as handle:
            return handle.read().strip()
    except Exception:
        return None


def _writeSysfsText(path: str, value: str) -> bool:
    try:
        with open(path, "w") as handle:
            handle.write(value)
        return True
    except Exception as exc:
        log.warning("camera recovery: write %s=%s failed: %s", path, value, exc)
        return False


def _readSysfsInt(path: str) -> int | None:
    raw = _readSysfsText(path)
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _usbDeviceDirForInterface(interface_dir: str) -> str | None:
    # /sys/.../usb5/5-1/5-1.1/5-1.1:1.0 → /sys/.../5-1.1. The USB device dir is
    # the first ancestor carrying idVendor; the UVC interface dir does not.
    current = interface_dir
    for _ in range(8):
        if os.path.exists(os.path.join(current, "idVendor")):
            return current
        parent = os.path.dirname(current)
        if parent == current or parent == "/":
            return None
        current = parent
    return None


def _controllerForUsbDevice(sysfs_path: str) -> tuple[str | None, str | None]:
    # Walk up past usbN to the platform/PCI device that owns the bus, then find
    # which driver currently has it bound so a rebind can target it.
    current = sysfs_path
    for _ in range(12):
        parent = os.path.dirname(current)
        if parent == current or parent == "/":
            return None, None
        base = os.path.basename(current)
        if base.startswith("usb") and base[3:].isdigit():
            controller_dir = parent
            controller_name = os.path.basename(controller_dir)
            driver_link = os.path.join(controller_dir, "driver")
            driver = None
            try:
                driver = os.path.basename(os.path.realpath(driver_link))
            except Exception:
                driver = None
            if driver not in _PLATFORM_USB_DRIVERS:
                driver = None
            return controller_name, driver
        current = parent
    return None, None


def _resolvePortSysfsPath(device_sysfs_path: str) -> str | None:
    # The `port` symlink points at the usbN-portM device that owns the
    # disable/enable knob for the port this device is plugged into.
    port_link = os.path.join(device_sysfs_path, "port")
    if not os.path.exists(port_link):
        return None
    try:
        resolved = os.path.realpath(port_link)
    except Exception:
        return None
    if not os.path.exists(os.path.join(resolved, "disable")):
        return None
    return resolved


def resolveCameraUsbDevice(index: int) -> CameraUsbDevice | None:
    if platform.system() != "Linux" or not isinstance(index, int) or index < 0:
        return None
    interface_link = os.path.join(SYSFS_VIDEO_ROOT, f"video{index}", "device")
    if not os.path.exists(interface_link):
        return None
    try:
        interface_dir = os.path.realpath(interface_link)
    except Exception:
        return None

    device_dir = _usbDeviceDirForInterface(interface_dir)
    if device_dir is None:
        return None

    busnum = _readSysfsInt(os.path.join(device_dir, "busnum"))
    devnum = _readSysfsInt(os.path.join(device_dir, "devnum"))
    if busnum is None or devnum is None:
        return None

    speed_raw = _readSysfsText(os.path.join(device_dir, "speed"))
    try:
        speed_mbps = float(speed_raw) if speed_raw else None
    except Exception:
        speed_mbps = None

    parent_dir = os.path.dirname(device_dir)
    if not os.path.exists(os.path.join(parent_dir, "idVendor")):
        parent_dir = None

    controller_name, controller_driver = _controllerForUsbDevice(device_dir)

    return CameraUsbDevice(
        sysfs_path=device_dir,
        devpath=_readSysfsText(os.path.join(device_dir, "devpath")) or "",
        busnum=busnum,
        devnum=devnum,
        speed_mbps=speed_mbps,
        parent_sysfs_path=parent_dir,
        port_sysfs_path=_resolvePortSysfsPath(device_dir),
        parent_port_sysfs_path=(
            _resolvePortSysfsPath(parent_dir) if parent_dir is not None else None
        ),
        controller_name=controller_name,
        controller_driver=controller_driver,
    )


def isLinkSpeedDegraded(device: CameraUsbDevice | None) -> bool:
    if device is None or device.speed_mbps is None:
        return False
    return device.speed_mbps < HIGH_SPEED_MBPS


# Measured on kitbash 2026-08-12, in the degraded state, with the full ladder
# plus an EHCI-companion rebind (unbind OHCI -> cycle EHCI -> rebind OHCI):
# ehci-platform re-probed and retried the high-speed handshake three times and
# failed every time —
#     usb 4-1: device descriptor read/64, error -71
#     usb usb4-port1: Cannot enable. Maybe the USB cable is bad?
#     usb 4-1: device not accepting address 5, error -71
#     usb usb4-port1: unable to enumerate USB device
# — before the kernel handed the port back to the OHCI companion at 12 Mbit/s.
#
# So a sub-high-speed link here is NOT recoverable in software: the fallback is
# the kernel correctly reporting that 480 Mbit/s signalling does not survive the
# current cable/connector, and 12 Mbit/s is simply tolerant enough to enumerate.
# Re-seating the cable fixes it because it changes the physical contact, not
# because it resets any state. The ladder is still worth running (it does fix a
# camera that merely mis-set its format at a healthy link speed), but once it is
# exhausted with the link still slow, the honest answer is to send someone to
# the hardware rather than keep resetting a bus that is doing its best.
def isLikelyPhysicalLinkFault(device: CameraUsbDevice | None) -> bool:
    return isLinkSpeedDegraded(device)


def resolveIndexForDevpath(devpath: str) -> int | None:
    # After a reset the kernel re-mints /dev/videoN, and these cameras all ship
    # the same USB serial ("200901010001"), so by-id collides and by-path
    # encodes the controller that just changed. The hub port chain is what
    # actually identifies the physical camera.
    if platform.system() != "Linux" or not devpath:
        return None
    try:
        names = sorted(os.listdir(SYSFS_VIDEO_ROOT))
    except Exception:
        return None
    for name in names:
        if not name.startswith("video"):
            continue
        try:
            candidate_index = int(name[len("video") :])
        except Exception:
            continue
        device = resolveCameraUsbDevice(candidate_index)
        if device is None or device.devpath != devpath:
            continue
        # Both the capture node and its metadata sibling map to the same USB
        # device; only the capture node reports a video-capture format.
        if readNegotiatedCaptureFormat(candidate_index) is None:
            continue
        return candidate_index
    return None


def readNegotiatedCaptureFormat(index: int) -> tuple[int, int, str] | None:
    if not isinstance(index, int) or index < 0:
        return None
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{index}", "--get-fmt-video"],
            capture_output=True,
            timeout=3,
            text=True,
        )
        if result.returncode != 0:
            return None
    except Exception:
        return None

    width = height = 0
    fourcc = ""
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Width/Height"):
            _, _, raw = stripped.partition(":")
            parts = raw.strip().split("/")
            if len(parts) == 2:
                try:
                    width, height = int(parts[0]), int(parts[1])
                except Exception:
                    return None
        elif stripped.startswith("Pixel Format"):
            _, _, raw = stripped.partition(":")
            fourcc = raw.strip().split()[0].strip("'\"") if raw.strip() else ""
    if width <= 0 or height <= 0:
        return None
    return width, height, fourcc


def supportsCaptureSize(index: int, width: int, height: int) -> bool | None:
    # Returns None when the enumeration can't be read at all. A False here is
    # the definitive "the device is not currently capable of what we asked for"
    # signal — at full speed these cameras drop their high-res modes from the
    # descriptor entirely, so this distinguishes a bus-speed regression from a
    # merely mis-set format.
    if not isinstance(index, int) or index < 0 or width <= 0 or height <= 0:
        return None
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{index}", "--list-formats-ext"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        if result.returncode != 0:
            return None
    except Exception:
        return None
    needle = f"{int(width)}x{int(height)}"
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Size:") and stripped.endswith(needle):
            return True
    return False


# ---------------------------------------------------------------------------
# Ladder rungs. Each returns True if the action was actually performed; the
# caller decides whether it worked by re-reading the negotiated format.
# ---------------------------------------------------------------------------


def forceCaptureFormat(index: int, width: int, height: int, fourcc: str | None) -> bool:
    fmt_arg = f"width={int(width)},height={int(height)}"
    if isinstance(fourcc, str) and len(fourcc.strip()) >= 4:
        fmt_arg = f"pixelformat={fourcc.strip()[:4].upper()}," + fmt_arg
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{index}", f"--set-fmt-video={fmt_arg}"],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def _resetUsbDeviceAt(busnum: int, devnum: int) -> bool:
    node = f"/dev/bus/usb/{busnum:03d}/{devnum:03d}"
    try:
        fd = os.open(node, os.O_WRONLY)
    except Exception as exc:
        log.warning("camera recovery: cannot open %s for reset: %s", node, exc)
        return False
    try:
        fcntl.ioctl(fd, USBDEVFS_RESET, 0)
        return True
    except Exception as exc:
        log.warning("camera recovery: USBDEVFS_RESET on %s failed: %s", node, exc)
        return False
    finally:
        try:
            os.close(fd)
        except Exception:
            pass


def resetUsbDevice(device: CameraUsbDevice) -> bool:
    return _resetUsbDeviceAt(device.busnum, device.devnum)


def resetParentHub(device: CameraUsbDevice) -> bool:
    parent = device.parent_sysfs_path
    if parent is None:
        return False
    busnum = _readSysfsInt(os.path.join(parent, "busnum"))
    devnum = _readSysfsInt(os.path.join(parent, "devnum"))
    if busnum is None or devnum is None:
        return False
    return _resetUsbDeviceAt(busnum, devnum)


def _cyclePort(port_sysfs_path: str | None, *, off_s: float) -> bool:
    if port_sysfs_path is None:
        return False
    disable_path = os.path.join(port_sysfs_path, "disable")
    if not _writeSysfsText(disable_path, "1"):
        return False
    time.sleep(off_s)
    return _writeSysfsText(disable_path, "0")


def cycleDevicePort(device: CameraUsbDevice) -> bool:
    return _cyclePort(device.port_sysfs_path, off_s=1.0)


def cycleUpstreamPort(device: CameraUsbDevice) -> bool:
    # Disabling the port the *hub* sits on is the closest software equivalent to
    # pulling the cable: it drives a real disconnect on the root port, which is
    # the event that makes ehci-hcd take the port back from the OHCI companion
    # and retry the high-speed handshake. Everything downstream of the hub
    # (including the control-board serial port) re-enumerates with it.
    return _cyclePort(device.parent_port_sysfs_path, off_s=2.0)


def rebindHostController(device: CameraUsbDevice) -> bool:
    name = device.controller_name
    driver = device.controller_driver
    if not name or not driver:
        return False
    driver_dir = os.path.join("/sys/bus/platform/drivers", driver)
    if not os.path.isdir(driver_dir):
        return False
    if not _writeSysfsText(os.path.join(driver_dir, "unbind"), name):
        return False
    time.sleep(1.0)
    ok = _writeSysfsText(os.path.join(driver_dir, "bind"), name)
    # Rebinding only the companion cannot itself hand the port back to the
    # high-speed sibling controller — if this rung is being reached the port
    # cycle above already failed, and the remaining fix is physical.
    if not ok:
        log.error("camera recovery: failed to rebind USB host controller %s (%s)", name, driver)
    return ok


@dataclass
class RecoveryStep:
    name: str
    run: Callable[[CameraUsbDevice], bool]
    # How long to wait for re-enumeration before the format is re-read.
    settle_s: float
    # True when the rung re-enumerates the whole hub or controller rather than
    # just this camera. The control board's serial port lives on the same hub,
    # so these rungs briefly take the machine's motion control with them — the
    # caller holds them until the machine is not actively sorting.
    disrupts_shared_bus: bool = False


# Ordered cheapest → most disruptive, and within that, camera-local rungs before
# anything that touches the shared bus: an operator mid-sort should get every
# reset that cannot cost them the control board before one that can. The capture
# thread walks one rung per attempt and re-verifies after each, so a mild reset
# that happens to work never escalates into a bus-wide re-enumeration.
RECOVERY_LADDER: tuple[RecoveryStep, ...] = (
    RecoveryStep("usb_device_reset", resetUsbDevice, 3.0),
    RecoveryStep("port_power_cycle", cycleDevicePort, 5.0),
    RecoveryStep("usb_hub_reset", resetParentHub, 5.0, disrupts_shared_bus=True),
    RecoveryStep(
        "upstream_port_power_cycle", cycleUpstreamPort, 8.0, disrupts_shared_bus=True
    ),
    RecoveryStep(
        "host_controller_rebind", rebindHostController, 8.0, disrupts_shared_bus=True
    ),
)


def describeCameraUsbState(index: int) -> dict[str, object]:
    device = resolveCameraUsbDevice(index)
    negotiated = readNegotiatedCaptureFormat(index)
    state: dict[str, object] = {}
    if device is not None:
        state["usb_devpath"] = device.devpath
        state["usb_speed_mbps"] = device.speed_mbps
        state["usb_link_degraded"] = isLinkSpeedDegraded(device)
        state["usb_controller"] = device.controller_name
        state["likely_physical_fault"] = isLikelyPhysicalLinkFault(device)
        if isLikelyPhysicalLinkFault(device):
            state["operator_action"] = (
                f"This camera's USB link came up at {device.speed_mbps:.0f} Mbit/s instead of "
                f"{HIGH_SPEED_MBPS} Mbit/s, so the camera can only offer low resolutions. "
                "Software resets cannot fix this — reseat (or replace) the USB cable between "
                "the hub and the board, and check the hub's power."
            )
    if negotiated is not None:
        state["negotiated_width"] = negotiated[0]
        state["negotiated_height"] = negotiated[1]
        state["negotiated_fourcc"] = negotiated[2]
    return state
