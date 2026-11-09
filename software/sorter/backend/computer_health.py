"""The health of the computer the backend runs on.

One daemon thread takes a reading every SAMPLE_S from the kernel's own files:
every thermal zone's temperature against its trip points, whether the kernel is
slowing the chip down to cool it (its thermal cooling devices), each CPU
cluster's speed against its top speed and its current cap, load and per-core
use, memory and swap, the data volume's free space, whether it went read-only
and its file system's error count, the storage medium's own wear figure where it
has one, supply voltage alarms where a sensor has them, fans, uptime, whether
the clock is synchronized, and this process's memory and CPU. Every figure is a
small file in /proc or /sys, plus one adjtimex() call for the clock; nothing
starts a subprocess. Trip points and the list of sensors are read once. A
sensor the computer does not have is absent from the reading, never an error,
so the same code runs on an Orange Pi, a Raspberry Pi, a PC or a Mac.

What it does with the readings:

- keeps one point a minute for the last HISTORY_H hours, which the Computer
  settings page draws (GET /api/system/computer, server/routers/computer.py);
- writes those minutes as a `computer_health` telemetry window every WINDOW_S
  and at shutdown (telemetry_store), so the history outlives a restart, and is
  read back at start;
- logs a one-line summary every LOG_EVERY_S, and a line as soon as something
  changes: the kernel starts or stops slowing the chip, a warning starts or
  ends, the file system records a new error;
- while something is seriously wrong, raises a warning on the dashboard
  through incidents.report (kinds that warn without holding the machine):
  too hot or slowed down most of the time, storage nearly full, storage
  read-only, memory nearly exhausted, supply voltage low. Each is an Episode
  with hysteresis, so it is raised once and clears only when the condition has
  really ended.

Every threshold is in LIMITS. Temperatures come from the hardware's own trip
points where the kernel publishes them (on an RK3588 the chip starts slowing
at 75 C, holds itself at 85 C and shuts down at 115 C).
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

SAMPLE_S = 5.0
MINUTE_S = 60.0
HISTORY_H = 24
LOG_EVERY_S = 600.0
WINDOW_S = 3600.0
KIND = "computer_health"
SCHEMA = 1
ERROR_LOG_INTERVAL_S = 300.0
GIB = 1024 ** 3


@dataclass(frozen=True)
class Limits:
    # A zone is too hot at its highest passive trip point, where the kernel
    # holds the temperature by slowing the chip; a zone without one at hot_c,
    # or critical_margin_c under its critical (shutdown) trip if that is lower.
    hot_c: float = 85.0
    critical_margin_c: float = 15.0
    # ...and has cooled once every zone is this far under its limit.
    hot_clear_margin_c: float = 5.0
    # Slowed down in at least this share of the readings over the last
    # throttle_window_s is too hot as well; under throttled_clear_share is fine.
    throttle_window_s: float = 120.0
    throttled_share: float = 0.5
    throttled_clear_share: float = 0.1
    # Too hot (or slowed) for this long before the warning shows, and cool
    # for this long before it goes.
    hot_start_after_s: float = 10.0
    hot_end_after_s: float = 60.0
    # Storage is nearly full under either figure, and fine again over both.
    disk_free_min_bytes: int = 2 * GIB
    disk_free_min_pct: float = 5.0
    disk_free_clear_bytes: int = 3 * GIB
    disk_free_clear_pct: float = 7.0
    # Memory is nearly exhausted with less than this share available, for
    # memory_after_s; fine again over memory_available_clear_pct.
    memory_available_min_pct: float = 5.0
    memory_available_clear_pct: float = 10.0
    memory_after_s: float = 30.0
    # A supply voltage alarm clears after this long without one.
    power_end_after_s: float = 300.0
    # The kernel counts as no longer slowing the chip after this long at full
    # speed (for the log lines; it switches often while it holds a temperature).
    slowing_end_after_s: float = 30.0


LIMITS = Limits()


# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------


def _read(root: Path, rel: str) -> str | None:
    try:
        with open(root / rel, "r") as handle:
            return handle.read().replace("\x00", "").strip()
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _readInt(root: Path, rel: str) -> int | None:
    text = _read(root, rel)
    if not text:
        return None
    try:
        return int(text.split()[0])
    except ValueError:
        return None


def _numbered(root: Path, rel: str, prefix: str) -> list[str]:
    """The entries of a directory named prefix<N>, in N order."""
    try:
        names = [p.name for p in (root / rel).iterdir() if p.name.startswith(prefix)]
    except OSError:
        return []
    suffix = lambda name: name[len(prefix):]
    return sorted((n for n in names if suffix(n).isdigit()), key=lambda n: int(suffix(n)))


def cpuRange(cpus: list[int]) -> str:
    """[0, 1, 2, 3, 6] -> "0-3, 6"."""
    parts: list[str] = []
    for cpu in sorted(set(cpus)):
        if parts and "-" in parts[-1] and int(parts[-1].split("-")[1]) == cpu - 1:
            parts[-1] = f"{parts[-1].split('-')[0]}-{cpu}"
        elif parts and "-" not in parts[-1] and int(parts[-1]) == cpu - 1:
            parts[-1] = f"{parts[-1]}-{cpu}"
        else:
            parts.append(str(cpu))
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Temperatures
# ---------------------------------------------------------------------------

# Thermal zone types (without -thermal / _thermal) as a person would say them.
_ZONE_LABELS = {
    "soc": "Chip",
    "cpu": "Processor",
    "x86_pkg_temp": "Processor",
    "bigcore0": "Fast cores, first pair",
    "bigcore1": "Fast cores, second pair",
    "littlecore": "Efficient cores",
    "center": "Chip center",
    "gpu": "Graphics",
    "npu": "AI accelerator",
    "acpitz": "Board",
}


def _zoneName(zone_type: str) -> str:
    return re.sub(r"[-_]thermal$", "", zone_type)


def zoneLabel(zone_type: str) -> str:
    name = _zoneName(zone_type)
    label = _ZONE_LABELS.get(name)
    if label:
        return label
    words = name.replace("_", " ").replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else zone_type


@dataclass(frozen=True)
class Zone:
    rel: str
    type: str
    label: str
    # Where the kernel starts slowing the chip (its lowest passive trip).
    slows_c: float | None
    # Too hot from here (see Limits.hot_c).
    hot_c: float
    # Where the kernel shuts the computer down.
    critical_c: float | None


def listZones(root: Path, limits: Limits = LIMITS) -> list[Zone]:
    zones: list[Zone] = []
    labels: dict[str, int] = {}
    for name in _numbered(root, "sys/class/thermal", "thermal_zone"):
        rel = f"sys/class/thermal/{name}"
        zone_type = _read(root, f"{rel}/type") or name
        trips: list[tuple[str, float]] = []
        for i in range(64):
            temp = _readInt(root, f"{rel}/trip_point_{i}_temp")
            if temp is None:
                break
            trips.append((_read(root, f"{rel}/trip_point_{i}_type") or "", temp / 1000.0))
        passive = [c for kind, c in trips if kind == "passive" and c > 0]
        critical = [c for kind, c in trips if kind == "critical" and c > 0]
        critical_c = min(critical) if critical else None
        if passive:
            hot_c = max(passive)
        elif critical_c is not None:
            hot_c = min(limits.hot_c, critical_c - limits.critical_margin_c)
        else:
            hot_c = limits.hot_c
        label = zoneLabel(zone_type)
        labels[label] = labels.get(label, 0) + 1
        if labels[label] > 1:
            label = f"{label} {labels[label]}"
        zones.append(Zone(rel, zone_type, label, min(passive) if passive else None, hot_c, critical_c))
    return zones


def readTemperature(root: Path, zone: Zone) -> float | None:
    millidegrees = _readInt(root, f"{zone.rel}/temp")
    if millidegrees is None:
        return None
    celsius = millidegrees / 1000.0
    # A sensor that is off or broken reads far outside what a chip can be.
    return round(celsius, 1) if -40.0 < celsius < 150.0 else None


def mainZone(zones: list[Zone]) -> Zone | None:
    """The zone that speaks for the whole chip: the SoC's or the processor's,
    else the first."""
    for name in ("soc", "cpu", "x86_pkg_temp"):
        for zone in zones:
            if _zoneName(zone.type) == name:
                return zone
    return zones[0] if zones else None


# ---------------------------------------------------------------------------
# Slowing down: thermal cooling devices and CPU speeds
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cluster:
    rel: str
    cpus: list[int]
    max_khz: int | None


def listClusters(root: Path) -> list[Cluster]:
    clusters: list[Cluster] = []
    for name in _numbered(root, "sys/devices/system/cpu/cpufreq", "policy"):
        rel = f"sys/devices/system/cpu/cpufreq/{name}"
        text = _read(root, f"{rel}/related_cpus") or _read(root, f"{rel}/affected_cpus") or ""
        cpus = [int(c) for c in text.split() if c.isdigit()] or [int(name[len("policy"):])]
        clusters.append(Cluster(rel, cpus, _readInt(root, f"{rel}/cpuinfo_max_freq")))
    return clusters


def readCluster(root: Path, cluster: Cluster) -> dict[str, Any]:
    # cpuinfo_cur_freq is the clock the hardware runs at (root only);
    # scaling_cur_freq is what the governor last asked for.
    current = _readInt(root, f"{cluster.rel}/cpuinfo_cur_freq") or _readInt(root, f"{cluster.rel}/scaling_cur_freq")
    limit = _readInt(root, f"{cluster.rel}/scaling_max_freq")
    mhz = lambda khz: round(khz / 1000) if isinstance(khz, int) and khz > 0 else None
    return {
        "cpus": cpuRange(cluster.cpus),
        "mhz": mhz(current),
        "max_mhz": mhz(cluster.max_khz),
        "limit_mhz": mhz(limit),
    }


@dataclass(frozen=True)
class CoolingDevice:
    rel: str
    type: str
    label: str
    # "slows": it cools by slowing a processor, the memory or the graphics
    # down; "fan": it cools with air.
    role: str
    max_state: int


def _coolingLabel(device_type: str, clusters: list[Cluster]) -> tuple[str, str]:
    lowered = device_type.lower()
    if "fan" in lowered:
        return "Fan", "fan"
    if "cpufreq" in lowered:
        match = re.search(r"(\d+)$", device_type)
        first = int(match.group(1)) if match else None
        for cluster in clusters:
            if first is not None and first in cluster.cpus:
                return f"Cores {cpuRange(cluster.cpus)}", "slows"
        return "Processor", "slows"
    if "devfreq" in lowered:
        if "dmc" in lowered:
            return "Memory", "slows"
        if "gpu" in lowered:
            return "Graphics", "slows"
        if "npu" in lowered:
            return "AI accelerator", "slows"
        return device_type, "slows"
    return device_type, "other"


def listCoolingDevices(root: Path, clusters: list[Cluster]) -> list[CoolingDevice]:
    devices: list[CoolingDevice] = []
    for name in _numbered(root, "sys/class/thermal", "cooling_device"):
        rel = f"sys/class/thermal/{name}"
        device_type = _read(root, f"{rel}/type") or name
        max_state = _readInt(root, f"{rel}/max_state")
        if max_state is None or max_state <= 0:
            continue
        label, role = _coolingLabel(device_type, clusters)
        devices.append(CoolingDevice(rel, device_type, label, role, max_state))
    return devices


# ---------------------------------------------------------------------------
# /proc: CPU use, load, memory, uptime, mounts
# ---------------------------------------------------------------------------


def parseCpuTimes(text: str) -> dict[str, tuple[int, int]]:
    """/proc/stat's cpu lines as {name: (busy jiffies, total jiffies)}; idle
    and waiting for the disk count as not busy, guest time is inside user."""
    times: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        fields = line.split()
        try:
            values = [int(v) for v in fields[1:9]]
        except ValueError:
            continue
        if len(values) < 4:
            continue
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        times[fields[0]] = (total - idle, total)
    return times


def cpuUse(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> tuple[float | None, list[float]]:
    """(all cores' use in %, each core's in %) between two /proc/stat readings."""

    def pct(name: str) -> float | None:
        if name not in before or name not in after:
            return None
        busy = after[name][0] - before[name][0]
        total = after[name][1] - before[name][1]
        return round(max(0.0, min(100.0, 100.0 * busy / total)), 1) if total > 0 else None

    cores = sorted((n for n in after if n != "cpu" and n[3:].isdigit()), key=lambda n: int(n[3:]))
    return pct("cpu"), [p for p in (pct(n) for n in cores) if p is not None]


def parseMeminfo(text: str) -> dict[str, int]:
    """/proc/meminfo as {field: bytes}."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[name.strip()] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    return values


def memory(meminfo: dict[str, int]) -> dict[str, Any] | None:
    total = meminfo.get("MemTotal")
    available = meminfo.get("MemAvailable")
    if not total or available is None:
        return None
    swap_total = meminfo.get("SwapTotal", 0)
    swap_free = meminfo.get("SwapFree", 0)
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_pct": round(100.0 * (total - available) / total, 1),
        "swap_total_bytes": swap_total,
        "swap_used_bytes": max(0, swap_total - swap_free),
    }


def memTotalBytes(root: Path = Path("/")) -> int | None:
    return parseMeminfo(_read(root, "proc/meminfo") or "").get("MemTotal")


def parseLoadavg(text: str) -> list[float] | None:
    try:
        return [float(v) for v in text.split()[:3]]
    except (ValueError, AttributeError):
        return None


def parseMounts(text: str) -> list[tuple[str, str, str, set[str]]]:
    """(device, mount point, file system, options) per line of /proc/mounts."""
    mounts = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 4:
            # Spaces in a mount point are written as \040.
            mounts.append((fields[0], fields[1].replace("\\040", " "), fields[2], set(fields[3].split(","))))
    return mounts


def mountOf(mounts: list[tuple[str, str, str, set[str]]], path: str) -> tuple[str, str, str, set[str]] | None:
    """The mount a path is on: the one with the longest mount point above it
    (the last such line wins, as the kernel stacks them)."""
    best, best_len = None, -1
    for mount in mounts:
        point = mount[1].rstrip("/")
        if (path == point or path.startswith(point + "/")) and len(point) >= best_len:
            best, best_len = mount, len(point)
    return best


def diskOf(partition: str) -> str:
    """mmcblk1p1 -> mmcblk1, nvme0n1p2 -> nvme0n1, sda1 -> sda."""
    match = re.match(r"^(mmcblk\d+|nvme\d+n\d+)p\d+$", partition) or re.match(r"^((?:sd|vd|hd)[a-z]+)\d+$", partition)
    return match.group(1) if match else partition


def readMedium(root: Path, device: str) -> dict[str, Any] | None:
    """What the storage is, and its own wear figures where it keeps them
    (eMMC's life_time and pre_eol_info; an SD card has neither)."""
    if not device.startswith("/dev/"):
        return None
    disk = diskOf(device[len("/dev/"):])
    rel = f"sys/block/{disk}/device"
    media_type = _read(root, f"{rel}/type")
    if disk.startswith("nvme"):
        kind = "NVMe drive"
    elif media_type == "SD":
        kind = "SD card"
    elif media_type == "MMC":
        kind = "eMMC"
    elif disk.startswith(("sd", "vd", "hd")):
        kind = "Drive"
    else:
        return None
    medium: dict[str, Any] = {"kind": kind, "name": _read(root, f"{rel}/name") or _read(root, f"{rel}/model")}
    life = _read(root, f"{rel}/life_time")
    if life:
        # Two estimates (type A and B cells), each 0x01 for 0-10% used up to
        # 0x0A for 90-100%, 0x0B past its rated life.
        try:
            steps = [int(v, 16) for v in life.split()]
            medium["wear_pct"] = min(110, max(steps) * 10) if steps and max(steps) > 0 else None
        except ValueError:
            pass
    pre_eol = _read(root, f"{rel}/pre_eol_info")
    if pre_eol:
        medium["reserve"] = {"0x01": "normal", "0x02": "low", "0x03": "nearly used up"}.get(pre_eol.lower())
    return medium


def diskSpace(path: str) -> dict[str, int] | None:
    try:
        stats = os.statvfs(path)
    except OSError:
        return None
    total = stats.f_blocks * stats.f_frsize
    free = stats.f_bavail * stats.f_frsize
    used = (stats.f_blocks - stats.f_bfree) * stats.f_frsize
    if total <= 0:
        return None
    return {"total_bytes": total, "free_bytes": free, "used_bytes": used}


# ---------------------------------------------------------------------------
# Supply, fans, clock
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hwmon:
    rel: str
    name: str
    alarms: list[str]
    pwm: bool
    rpm: bool


def listHwmon(root: Path) -> list[Hwmon]:
    found: list[Hwmon] = []
    for name in _numbered(root, "sys/class/hwmon", "hwmon"):
        rel = f"sys/class/hwmon/{name}"
        try:
            files = {p.name for p in (root / rel).iterdir()}
        except OSError:
            continue
        # A voltage under its low limit (Raspberry Pi: rpi_volt's in0_lcrit_alarm).
        alarms = sorted(f for f in files if re.match(r"^in\d+_(lcrit|min)_alarm$", f))
        hwmon_name = _read(root, f"{rel}/name") or name
        fan = "fan" in hwmon_name.lower()
        found.append(Hwmon(rel, hwmon_name, alarms, fan and "pwm1" in files, "fan1_input" in files))
    return [h for h in found if h.alarms or h.pwm or h.rpm]


_libc: Any = None


def clockSynchronized() -> bool | None:
    """Whether the kernel's clock is synchronized (what timedatectl calls NTP
    synchronized), from adjtimex(): TIME_ERROR means it is not."""
    global _libc
    if not sys.platform.startswith("linux"):
        return None
    try:
        if _libc is None:
            _libc = ctypes.CDLL(None, use_errno=True)
        # struct timex with modes 0 only reads; 512 bytes holds it on every ABI.
        state = _libc.adjtimex(ctypes.create_string_buffer(512))
    except (OSError, AttributeError):
        return None
    if state < 0:
        return None
    return state != 5


# ---------------------------------------------------------------------------
# Warnings with hysteresis
# ---------------------------------------------------------------------------


class Episode:
    """One condition with hysteresis. It starts once it has been bad for
    start_after_s, and ends once it has been good for end_after_s. A reading
    that is neither (between the two thresholds, or unknown) restarts both
    counts, so a condition hovering at its threshold changes nothing."""

    def __init__(self, start_after_s: float = 0.0, end_after_s: float = 0.0) -> None:
        self.start_after_s = start_after_s
        self.end_after_s = end_after_s
        self.active = False
        self.since: float | None = None
        self._bad_since: float | None = None
        self._good_since: float | None = None

    def update(self, now: float, bad: bool, good: bool) -> str | None:
        """"started", "ended" or None."""
        self._bad_since = (self._bad_since if self._bad_since is not None else now) if bad else None
        self._good_since = (self._good_since if self._good_since is not None else now) if good and not bad else None
        if not self.active and self._bad_since is not None and now - self._bad_since >= self.start_after_s:
            self.active, self.since = True, now
            return "started"
        if self.active and self._good_since is not None and now - self._good_since >= self.end_after_s:
            self.active, self.since = False, None
            return "ended"
        return None


def _medium(storage: dict[str, Any]) -> str:
    kind = (storage.get("medium") or {}).get("kind")
    return kind if kind in ("SD card", "eMMC", "NVMe drive") else "drive"


def _gb(value: int | None) -> str:
    return f"{value / 1e9:.1f} GB" if isinstance(value, int) else "an unknown amount"


def assess(reading: dict[str, Any], throttled_share: float | None, limits: Limits = LIMITS) -> dict[str, tuple[bool, bool, dict[str, Any]]]:
    """For each warning kind, (bad, good, the fields its card shows) from one
    reading. Bad and good are both False when the reading cannot tell."""
    result: dict[str, tuple[bool, bool, dict[str, Any]]] = {}

    temps = [t for t in reading.get("temperatures", []) if isinstance(t.get("temp_c"), (int, float))]
    hottest = max(temps, key=lambda t: t["temp_c"] - t["hot_c"], default=None)
    over = any(t["temp_c"] >= t["hot_c"] for t in temps)
    cool = bool(temps) and all(t["temp_c"] <= t["hot_c"] - limits.hot_clear_margin_c for t in temps)
    slowed = throttled_share is not None and throttled_share >= limits.throttled_share
    calm = throttled_share is None or throttled_share <= limits.throttled_clear_share
    if hottest is not None:
        if slowed:
            detail = f"The computer is at {hottest['temp_c']:.0f} °C and is slowing itself down to cool off."
        else:
            detail = f"The computer is at {hottest['temp_c']:.0f} °C, at or past the {hottest['hot_c']:.0f} °C it should stay under."
        result["computer_hot"] = (
            over or slowed,
            cool and calm,
            {"detail": detail, "temp_c": hottest["temp_c"], "zone": hottest["label"], "throttled_share": throttled_share},
        )

    storage = reading.get("storage") or {}
    free, total = storage.get("free_bytes"), storage.get("total_bytes")
    if isinstance(free, int) and isinstance(total, int) and total > 0:
        free_pct = 100.0 * free / total
        medium = _medium(storage)
        result["computer_disk_full"] = (
            free < limits.disk_free_min_bytes or free_pct < limits.disk_free_min_pct,
            free >= limits.disk_free_clear_bytes and free_pct >= limits.disk_free_clear_pct,
            {"detail": f"Only {_gb(free)} of {_gb(total)} is free on the {medium}.", "free_bytes": free, "total_bytes": total},
        )
    if isinstance(storage.get("read_only"), bool):
        medium = _medium(storage)
        result["computer_read_only"] = (
            storage["read_only"],
            not storage["read_only"],
            {"detail": f"The {medium} that holds the machine's data was switched to read-only, so nothing new is saved."},
        )

    mem = reading.get("memory")
    if isinstance(mem, dict):
        available_pct = 100.0 * mem["available_bytes"] / mem["total_bytes"]
        result["computer_memory_low"] = (
            available_pct < limits.memory_available_min_pct,
            available_pct >= limits.memory_available_clear_pct,
            {"detail": f"Only {_gb(mem['available_bytes'])} of {_gb(mem['total_bytes'])} of memory is free.", "available_bytes": mem["available_bytes"]},
        )

    low = (reading.get("power") or {}).get("low")
    if isinstance(low, bool):
        result["computer_power_low"] = (low, not low, {"detail": "The computer's supply voltage is too low."})
    return result


# ---------------------------------------------------------------------------
# The sampler
# ---------------------------------------------------------------------------


class _Minute:
    """One minute's readings, folded into one history point."""

    __slots__ = ("t", "temp_max", "throttled", "throttled_known", "cpu_sum", "cpu_n", "mem_max")

    def __init__(self, t: int) -> None:
        self.t = t
        self.temp_max: float | None = None
        self.throttled = 0
        self.throttled_known = 0
        self.cpu_sum = 0.0
        self.cpu_n = 0
        self.mem_max: float | None = None

    def add(self, hottest: float | None, throttled: bool | None, cpu: float | None, mem: float | None) -> None:
        if hottest is not None:
            self.temp_max = hottest if self.temp_max is None else max(self.temp_max, hottest)
        if throttled is not None:
            self.throttled_known += 1
            self.throttled += int(throttled)
        if cpu is not None:
            self.cpu_sum += cpu
            self.cpu_n += 1
        if mem is not None:
            self.mem_max = mem if self.mem_max is None else max(self.mem_max, mem)

    def point(self) -> list[Any]:
        """[minute start, hottest °C, share of readings slowed down, CPU use %, memory used %]."""
        return [
            self.t,
            self.temp_max,
            round(self.throttled / self.throttled_known, 2) if self.throttled_known else None,
            round(self.cpu_sum / self.cpu_n, 1) if self.cpu_n else None,
            self.mem_max,
        ]


class ComputerHealth:
    def __init__(
        self,
        gc: Any = None,
        *,
        root: Path = Path("/"),
        data_path: str | None = None,
        limits: Limits = LIMITS,
        clock: Callable[[], bool | None] = clockSynchronized,
        store: Any = None,
        persist: bool = True,
    ) -> None:
        self._gc = gc
        self._root = root
        self._data_path = data_path
        self._limits = limits
        self._clock = clock
        self._store = store
        self._persist = persist
        self._lock = threading.Lock()
        self.zones = listZones(root, limits)
        self.clusters = listClusters(root)
        self.cooling = listCoolingDevices(root, self.clusters)
        self.hwmon = listHwmon(root)
        model = _read(root, "proc/device-tree/model") or _read(root, "sys/firmware/devicetree/base/model")
        self.model = model or None
        self._prev_cpu: dict[str, tuple[int, int]] | None = None
        self._prev_process: tuple[float, float] | None = None
        self._process_cpu_pct: float | None = None
        self._ext4_errors: int | None = None
        self._latest: dict[str, Any] | None = None
        self._minutes: deque[list[Any]] = deque(maxlen=int(HISTORY_H * 3600 / MINUTE_S))
        self._minute: _Minute | None = None
        self._window: list[list[Any]] = []
        self._window_started_at: float | None = None
        self._throttled_recent: deque[bool] = deque(maxlen=max(1, int(limits.throttle_window_s / SAMPLE_S)))
        self._episodes = {
            "computer_hot": Episode(limits.hot_start_after_s, limits.hot_end_after_s),
            "computer_disk_full": Episode(),
            "computer_read_only": Episode(),
            "computer_memory_low": Episode(limits.memory_after_s, limits.memory_after_s),
            "computer_power_low": Episode(0.0, limits.power_end_after_s),
        }
        self._slowing = Episode(0.0, limits.slowing_end_after_s)
        self._slowed_samples = 0
        self._slowing_samples = 0
        self._reported_at: dict[str, float] = {}
        self._last_log_at: float | None = None
        self._log_temps: list[float] = []
        self._log_throttled = [0, 0]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error_log = 0.0

    # -- one reading -------------------------------------------------------

    def read(self, now: float) -> dict[str, Any]:
        root = self._root
        temperatures = []
        for zone in self.zones:
            temperatures.append({
                "key": zone.rel.rsplit("/", 1)[-1],
                "type": zone.type,
                "label": zone.label,
                "temp_c": readTemperature(root, zone),
                "slows_c": zone.slows_c,
                "hot_c": zone.hot_c,
                "critical_c": zone.critical_c,
            })

        slowing = []
        fans = []
        for device in self.cooling:
            state = _readInt(root, f"{device.rel}/cur_state")
            if state is None:
                continue
            if device.role == "slows":
                slowing.append({"label": device.label, "state": state, "max_state": device.max_state})
            elif device.role == "fan":
                fans.append({"label": device.label, "pct": round(100.0 * state / device.max_state), "rpm": None})
        throttled = any(d["state"] > 0 for d in slowing) if slowing else None

        supply_low: bool | None = None
        for hw in self.hwmon:
            for alarm in hw.alarms:
                value = _readInt(root, f"{hw.rel}/{alarm}")
                if value is not None:
                    supply_low = bool(supply_low) or value > 0
            if hw.pwm or hw.rpm:
                pwm = _readInt(root, f"{hw.rel}/pwm1") if hw.pwm else None
                fans.append({
                    "label": "Fan",
                    "pct": round(100.0 * pwm / 255) if pwm is not None else None,
                    "rpm": _readInt(root, f"{hw.rel}/fan1_input") if hw.rpm else None,
                })

        cpu_times = parseCpuTimes(_read(root, "proc/stat") or "")
        use, cores = cpuUse(self._prev_cpu, cpu_times) if self._prev_cpu else (None, [])
        self._prev_cpu = cpu_times or None
        load = parseLoadavg(_read(root, "proc/loadavg") or "")
        if load is None and root == Path("/") and hasattr(os, "getloadavg"):
            try:
                load = [round(v, 2) for v in os.getloadavg()]
            except OSError:
                load = None

        uptime = _read(root, "proc/uptime")
        try:
            uptime_s = round(float(uptime.split()[0])) if uptime else None
        except ValueError:
            uptime_s = None

        return {
            "captured_at": now,
            "model": self.model,
            "temperatures": temperatures,
            "slowing": {"active": throttled, "by": slowing},
            "clusters": [readCluster(root, c) for c in self.clusters],
            "cpu": {"use_pct": use, "cores_pct": cores, "load": load, "count": os.cpu_count()},
            "memory": memory(parseMeminfo(_read(root, "proc/meminfo") or "")),
            "storage": self._storage(),
            "power": {"low": supply_low},
            "fans": fans,
            "uptime_s": uptime_s,
            "clock_synced": self._clock(),
        }

    def _storage(self) -> dict[str, Any] | None:
        path = self._data_path
        if not path:
            return None
        space = diskSpace(path)
        storage: dict[str, Any] = {"path": path, **(space or {})}
        if space:
            storage["used_pct"] = round(100.0 * space["used_bytes"] / max(1, space["used_bytes"] + space["free_bytes"]), 1)
        mount = mountOf(parseMounts(_read(self._root, "proc/mounts") or ""), os.path.realpath(path) if self._root == Path("/") else path)
        if mount is not None:
            device, _point, fs, options = mount
            storage["read_only"] = "ro" in options
            storage["file_system"] = fs
            if device.startswith("/dev/"):
                storage["errors"] = _readInt(self._root, f"sys/fs/{fs}/{device[len('/dev/'):]}/errors_count")
            storage["medium"] = readMedium(self._root, device)
        return storage

    def process(self) -> dict[str, Any]:
        """This backend process: memory, CPU, how often it was started, and how
        late its loops run (from the figures runtime_stats already keeps)."""
        # VmRSS is in kB, Threads a plain count; parseMeminfo reads both.
        status = parseMeminfo(_read(Path("/"), "proc/self/status") or "")
        with self._lock:
            cpu_pct = self._process_cpu_pct
        info: dict[str, Any] = {
            "rss_bytes": status.get("VmRSS"),
            "threads": status.get("Threads") or threading.active_count(),
            # Share of one core since the last reading.
            "cpu_pct": cpu_pct,
            "uptime_s": round(time.time() - PROCESS_STARTED_AT),
            "starts": _envInt("SORTER_BACKEND_STARTS"),
            "unexpected_exits": _envInt("SORTER_BACKEND_UNEXPECTED_EXITS"),
            "loop_lag_ms": None,
            "control_wait_ms": None,
        }
        stats = getattr(self._gc, "runtime_stats", None)
        summary = getattr(stats, "perfMsSummary", None)
        if callable(summary):
            for key, metric in (("loop_lag_ms", "socket.loop_lag_ms"), ("control_wait_ms", "coordinator.step.gil_stall_ms")):
                values = summary(metric)
                if values.get("n"):
                    info[key] = {"p90": round(values["p90_ms"], 1), "max": round(values["max_ms"], 1)}
        return info

    def _sampleProcessCpu(self, now: float) -> None:
        times = os.times()
        used = times.user + times.system
        if self._prev_process is not None and now > self._prev_process[1]:
            share = 100.0 * (used - self._prev_process[0]) / (now - self._prev_process[1])
            with self._lock:
                self._process_cpu_pct = round(max(0.0, share), 1)
        self._prev_process = (used, now)

    # -- the loop ----------------------------------------------------------

    def tick(self, now: float) -> dict[str, Any]:
        reading = self.read(now)
        self._sampleProcessCpu(now)
        hottest = max((t["temp_c"] for t in reading["temperatures"] if t["temp_c"] is not None), default=None)
        throttled = reading["slowing"]["active"]
        if throttled is not None:
            self._throttled_recent.append(throttled)
        window_full = len(self._throttled_recent) >= max(1, self._throttled_recent.maxlen // 2)
        share = sum(self._throttled_recent) / len(self._throttled_recent) if self._throttled_recent and window_full else None
        reading["slowing"]["recent_share"] = round(share, 2) if share is not None else None

        minute_t = int(now // MINUTE_S * MINUTE_S)
        with self._lock:
            if self._minute is not None and self._minute.t != minute_t:
                point = self._minute.point()
                self._minutes.append(point)
                self._window.append(point)
                self._minute = None
            if self._minute is None:
                self._minute = _Minute(minute_t)
            mem = reading["memory"]["used_pct"] if reading["memory"] else None
            self._minute.add(hottest, throttled, reading["cpu"]["use_pct"], mem)
            self._latest = reading
        if self._window_started_at is None:
            self._window_started_at = now

        self._logChanges(now, reading, hottest, throttled)
        self._raiseWarnings(now, reading, share)
        self._periodicLog(now, reading, hottest, throttled)
        if now - self._window_started_at >= WINDOW_S:
            self.writeWindow(now)
        return reading

    def _logChanges(self, now: float, reading: dict[str, Any], hottest: float | None, throttled: bool | None) -> None:
        if throttled is not None:
            self._slowing_samples += 1
            self._slowed_samples += int(throttled)
        change = self._slowing.update(now, bool(throttled), throttled is False)
        devices = ", ".join(f"{d['label'].lower()} {d['state']}/{d['max_state']}" for d in reading["slowing"]["by"] if d["state"] > 0)
        if change == "started":
            self._slowed_samples, self._slowing_samples = int(bool(throttled)), 1
            self._log("warning", f"computer health: the kernel started slowing the chip down to cool it ({_hot(hottest)}; {devices})")
        elif change == "ended":
            share = self._slowed_samples / max(1, self._slowing_samples)
            self._log("info", f"computer health: the kernel stopped slowing the chip down ({_hot(hottest)}; slowed in {share:.0%} of the readings since it started)")
        errors = (reading.get("storage") or {}).get("errors")
        if isinstance(errors, int):
            if self._ext4_errors is not None and errors > self._ext4_errors:
                self._log("warning", f"computer health: the data volume's file system recorded {errors - self._ext4_errors} new error(s) ({errors} in all)")
            self._ext4_errors = errors

    def _raiseWarnings(self, now: float, reading: dict[str, Any], share: float | None) -> None:
        import incidents

        for kind, (bad, good, fields) in assess(reading, share, self._limits).items():
            episode = self._episodes[kind]
            change = episode.update(now, bad, good)
            title = incidents.KINDS[kind].title
            if change == "started":
                self._log("warning", f"computer health: {title.lower()}: {fields['detail']}")
            elif change == "ended":
                self._log("info", f"computer health: {title.lower()} ended")
            if self._gc is None:
                continue
            if change == "ended":
                incidents.clear(self._gc, kind, subject="")
                self._reported_at.pop(kind, None)
            elif episode.active and (change == "started" or now - self._reported_at.get(kind, 0.0) >= MINUTE_S):
                # Raised once; its numbers refreshed once a minute while it lasts.
                incidents.report(self._gc, kind, subject="", **fields)
                self._reported_at[kind] = now

    def _periodicLog(self, now: float, reading: dict[str, Any], hottest: float | None, throttled: bool | None) -> None:
        if hottest is not None:
            self._log_temps.append(hottest)
        if throttled is not None:
            self._log_throttled[0] += int(throttled)
            self._log_throttled[1] += 1
        if self._last_log_at is None:
            self._last_log_at = now
        if now - self._last_log_at < LOG_EVERY_S:
            return
        self._last_log_at = now
        self._log("info", "computer health: " + summaryLine(reading, self._log_temps, self._log_throttled))
        self._log_temps = []
        self._log_throttled = [0, 0]

    def _log(self, level: str, message: str) -> None:
        logger = getattr(self._gc, "logger", None)
        if logger is not None:
            getattr(logger, level)(message)
        else:
            getattr(log, level)(message)

    # -- history -----------------------------------------------------------

    def seed(self, now: float) -> None:
        """The minutes earlier runs wrote (telemetry windows), so a restart
        keeps the chart."""
        store = self._telemetryStore()
        if store is None:
            return
        since = now - HISTORY_H * 3600
        try:
            records = store.listKind(KIND, since)
        except Exception as exc:
            log.warning("computer health: earlier history not read: %s", exc)
            return
        points = [p for r in records for p in (r.get("data") or {}).get("minutes", []) if isinstance(p, list) and p and p[0] >= since]
        with self._lock:
            for point in sorted(points, key=lambda p: p[0]):
                self._minutes.append(point)

    def writeWindow(self, now: float) -> int | None:
        """Write the minutes since the last window as one telemetry window."""
        with self._lock:
            minutes, self._window = self._window, []
            started_at, self._window_started_at = self._window_started_at, now
        store = self._telemetryStore()
        if not minutes or started_at is None or store is None:
            return None
        temps = [p[1] for p in minutes if p[1] is not None]
        shares = [p[2] for p in minutes if p[2] is not None]
        data = {
            "sample_interval_s": SAMPLE_S,
            "model": self.model,
            "zones": {z.type: {"slows_c": z.slows_c, "hot_c": z.hot_c, "critical_c": z.critical_c} for z in self.zones},
            "temp_max_c": max(temps) if temps else None,
            "slowed_minutes": round(sum(shares), 2) if shares else None,
            "warnings": sorted(kind for kind, episode in self._episodes.items() if episode.active),
            # [minute start, hottest °C, share slowed, CPU %, memory %]
            "minutes": minutes,
        }
        try:
            return store.write(KIND, store.FORM_WINDOW, data, started_at=started_at, ended_at=now, schema=SCHEMA)
        except Exception as exc:
            log.warning("computer health: window not written: %s", exc)
            return None

    def _telemetryStore(self) -> Any:
        if not self._persist:
            return None
        if self._store is not None:
            return self._store
        try:
            import telemetry_store

            return telemetry_store
        except Exception:
            return None

    def history(self, hours: float) -> list[dict[str, Any]]:
        since = time.time() - hours * 3600
        with self._lock:
            points = list(self._minutes)
            if self._minute is not None:
                points.append(self._minute.point())
        return [
            {"t": p[0], "temp_c": p[1], "slowed": p[2], "cpu_pct": p[3], "mem_pct": p[4]}
            for p in points
            if p[0] >= since
        ]

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return self._latest

    def warnings(self) -> list[str]:
        return [kind for kind, episode in self._episodes.items() if episode.active]

    # -- thread ------------------------------------------------------------

    def start(self) -> None:
        self.seed(time.time())
        self._thread = threading.Thread(target=self._loop, daemon=True, name="computer-health")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick(time.time())
            except Exception as exc:
                if time.monotonic() - self._last_error_log >= ERROR_LOG_INTERVAL_S:
                    self._last_error_log = time.monotonic()
                    log.warning("computer health: %s", exc)
            self._stop.wait(SAMPLE_S)

    def shutdown(self, now: float | None = None) -> None:
        """Stop, keeping the minutes since the last window."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        with self._lock:
            if self._minute is not None:
                self._window.append(self._minute.point())
                self._minute = None
        self.writeWindow(time.time() if now is None else now)


PROCESS_STARTED_AT = time.time()


def _envInt(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value and value.isdigit() else None


def _hot(hottest: float | None) -> str:
    return f"hottest {hottest:.1f} °C" if hottest is not None else "no temperature"


def summaryLine(reading: dict[str, Any], temps: list[float], throttled: list[int]) -> str:
    """One line for the log: the stretch since the last line, then now."""
    parts = []
    if temps:
        parts.append(f"hottest {max(temps):.1f} °C (now {temps[-1]:.1f} °C)")
    if throttled[1]:
        parts.append(f"slowed {throttled[0] / throttled[1]:.0%}")
    clusters = [c for c in reading.get("clusters", []) if c.get("mhz")]
    if clusters:
        parts.append("speed " + " ".join(f"{c['mhz']}/{c['limit_mhz'] or c['max_mhz']}MHz" for c in clusters))
    cpu = reading.get("cpu") or {}
    if cpu.get("use_pct") is not None:
        parts.append(f"cpu {cpu['use_pct']:.0f}%")
    if cpu.get("load"):
        parts.append(f"load {cpu['load'][0]:.2f}")
    mem = reading.get("memory")
    if mem:
        swap = f", swap {mem['swap_used_bytes'] / 1e9:.1f} GB" if mem["swap_total_bytes"] else ""
        parts.append(f"memory {mem['used_pct']:.0f}%{swap}")
    storage = reading.get("storage") or {}
    if storage.get("free_bytes") is not None:
        parts.append(f"storage {_gb(storage['free_bytes'])} free{' READ-ONLY' if storage.get('read_only') else ''}")
    if reading.get("power", {}).get("low"):
        parts.append("supply LOW")
    if reading.get("clock_synced") is False:
        parts.append("clock not synchronized")
    return ", ".join(parts) or "no readings"


_service: ComputerHealth | None = None
_on_demand: ComputerHealth | None = None
_on_demand_lock = threading.Lock()


def _dataPath() -> str:
    import db

    return str(db.local_state_db_path().parent)


def start(gc: Any) -> ComputerHealth:
    global _service
    _service = ComputerHealth(gc, data_path=_dataPath())
    _service.start()
    return _service


def service() -> ComputerHealth | None:
    return _service


def _onDemand() -> ComputerHealth:
    """Without the sampler (the API-only server used for UI work), a sampler
    that reads when the page asks: no warnings, nothing written."""
    global _on_demand
    with _on_demand_lock:
        if _on_demand is None:
            _on_demand = ComputerHealth(data_path=_dataPath(), persist=False)
        latest = _on_demand.latest()
        if latest is None or time.time() - latest["captured_at"] >= 1.0:
            _on_demand.tick(time.time())
        return _on_demand


def describe(hours: float) -> dict[str, Any]:
    """What the Computer settings page shows (GET /api/system/computer)."""
    import incidents

    sampler = _service or _onDemand()
    hours = max(1.0 / 60.0, min(float(hours), float(HISTORY_H)))
    limits = sampler._limits
    return {
        "sampling": _service is not None,
        "sample_interval_s": SAMPLE_S,
        "reading": sampler.latest(),
        "process": sampler.process(),
        "warnings": [
            {"kind": kind, "title": incidents.KINDS[kind].title, "since": sampler._episodes[kind].since}
            for kind in sampler.warnings()
        ],
        "limits": {
            "throttle_window_s": limits.throttle_window_s,
            "throttled_share": limits.throttled_share,
            "disk_free_min_bytes": limits.disk_free_min_bytes,
            "disk_free_min_pct": limits.disk_free_min_pct,
            "memory_available_min_pct": limits.memory_available_min_pct,
        },
        "history": sampler.history(hours),
    }


def shutdown() -> None:
    if _service is not None:
        _service.shutdown()


def mainTemperatureC(root: Path = Path("/")) -> float | None:
    """The chip's temperature now, for reports that carry one figure."""
    if _service is not None:
        reading = _service.latest()
        zone = mainZone(_service.zones)
        if reading and zone:
            for entry in reading["temperatures"]:
                if entry["key"] == zone.rel.rsplit("/", 1)[-1]:
                    return entry["temp_c"]
    zone = mainZone(listZones(root))
    return readTemperature(root, zone) if zone else None
