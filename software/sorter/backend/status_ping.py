"""Machine status report — the periodic "here's this machine" sent to Hive.

Sent shortly after start and then hourly to a hardcoded default endpoint, so a
machine reports its version, hardware, config, and usage whether or not a Hive
account is configured. It carries a per-install id
(local_state.get_or_create_telemetry_install); a registered machine also
attaches its account machine id(s) so the report lines up with the machine in
the account.

Everything here is best-effort and must never touch the sorting path: a failed
report, an unreachable server, or a missing /proc file degrades to a smaller
payload or a skipped report, never an error the machine notices.

What CAN leave the machine via this channel is exactly the payload built in
buildPayload() below, and it is documented field-for-field on the docs site
("What leaves the machine"). If you add a field here, add it there too.

Turning it off: set SORTER_BASE_REPORTING_OFF=1 in the machine environment. The
sender thread then never starts.
"""

from __future__ import annotations

import os
import random
import shutil
import threading
import time
from typing import Any, Optional

import requests

DEFAULT_ENDPOINT = "https://hive.basically.website"
PING_PATH = "/api/installs/ping"

# First ping fires after a jittered delay so a boot storm (a lab on one power
# strip coming back after an outage) doesn't hit the server in lockstep, and so
# the network / Tailscale has time to settle after boot. Then hourly, with a
# little jitter for the same anti-thundering-herd reason.
INITIAL_DELAY_MIN_S = 120.0
INITIAL_DELAY_MAX_S = 300.0
INTERVAL_S = 3600.0
INTERVAL_JITTER_S = 300.0
REQUEST_TIMEOUT_S = 15.0

_OFF_VALUES = {"1", "true", "yes", "on"}

_PROCESS_STARTED_AT = time.time()


def reportingEnabled() -> bool:
    raw = os.getenv("SORTER_BASE_REPORTING_OFF")
    if raw is not None and raw.strip().lower() in _OFF_VALUES:
        return False
    return True


def _endpoint() -> str:
    override = os.getenv("SORTER_BASE_REPORTING_URL")
    base = override.strip() if isinstance(override, str) and override.strip() else DEFAULT_ENDPOINT
    return base.rstrip("/") + PING_PATH


def _readFirstLine(path: str) -> Optional[str]:
    try:
        with open(path, "r") as handle:
            return handle.readline().strip().strip("\x00")
    except Exception:
        return None


def _osInfo() -> dict[str, Any]:
    info: dict[str, Any] = {"name": None, "sorter_os_version": None}
    try:
        with open("/etc/os-release", "r") as handle:
            for line in handle:
                if line.startswith("PRETTY_NAME="):
                    info["name"] = line.split("=", 1)[1].strip().strip('"')
                    break
    except Exception:
        pass
    # SorterOS image stamp, if the image writes one. Best-effort; absent on a
    # plain Linux install or the Mac dev box.
    for candidate in ("/etc/sorter-os-release", "/etc/sorter-version"):
        value = _readFirstLine(candidate)
        if value:
            info["sorter_os_version"] = value
            break
    return info


def _hardwareInfo() -> dict[str, Any]:
    info: dict[str, Any] = {
        "model": None,
        "ram_bytes": None,
        "cpu_temp_c": None,
        "disk_free_bytes": None,
        "disk_total_bytes": None,
    }
    model = _readFirstLine("/proc/device-tree/model") or _readFirstLine("/sys/firmware/devicetree/base/model")
    if model:
        info["model"] = model
    try:
        with open("/proc/meminfo", "r") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    info["ram_bytes"] = int(line.split()[1]) * 1024
                    break
    except Exception:
        pass
    raw_temp = _readFirstLine("/sys/class/thermal/thermal_zone0/temp")
    if raw_temp:
        try:
            info["cpu_temp_c"] = round(int(raw_temp) / 1000.0, 1)
        except Exception:
            pass
    try:
        usage = shutil.disk_usage("/")
        info["disk_free_bytes"] = int(usage.free)
        info["disk_total_bytes"] = int(usage.total)
    except Exception:
        pass
    return info


def _systemUptimeS() -> Optional[float]:
    raw = _readFirstLine("/proc/uptime")
    if not raw:
        return None
    try:
        return round(float(raw.split()[0]), 1)
    except Exception:
        return None


def _softwareInfo() -> dict[str, Any]:
    info: dict[str, Any] = {"version": None, "channel": None, "commit": None}
    try:
        from server.routers.versions import _currentInfo

        current = _currentInfo()
        describe = current.get("describe")
        info["version"] = describe
        info["commit"] = current.get("sha")
        if isinstance(describe, str):
            if describe.startswith("sorter/stable/"):
                info["channel"] = "stable"
            elif describe.startswith("sorter/canary/"):
                info["channel"] = "canary"
    except Exception:
        pass
    return info


def _configInfo() -> dict[str, Any]:
    info: dict[str, Any] = {
        "machine_setup": None,
        "feeder_mode": None,
        "classification_channel_mode": None,
    }
    try:
        from machine_setup import DEFAULT_MACHINE_SETUP

        info["machine_setup"] = (
            DEFAULT_MACHINE_SETUP
            if isinstance(DEFAULT_MACHINE_SETUP, str)
            else getattr(DEFAULT_MACHINE_SETUP, "key", None)
        )
    except Exception:
        pass
    # Feeder / classification-channel modes default to the hardcoded rev04 values
    # unless machine.toml overrides them; report whichever is actually in force.
    try:
        from irl.config import ClassificationChannelMode, FeederMode

        info["feeder_mode"] = FeederMode.PULSE_PERCEPTION_REV01.value
        info["classification_channel_mode"] = ClassificationChannelMode.TWO_PIECE_STATE_MACHINE_REV01.value
    except Exception:
        pass
    try:
        from toml_config import loadTomlFile

        params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
        if params_path and os.path.exists(params_path):
            raw = loadTomlFile(params_path)
            if isinstance(raw, dict):
                info["machine_setup"] = raw.get("machine_setup", info["machine_setup"])
                feeder = raw.get("feeder")
                if isinstance(feeder, dict) and feeder.get("mode"):
                    info["feeder_mode"] = feeder.get("mode")
                cc = raw.get("classification_channel")
                if isinstance(cc, dict) and cc.get("mode"):
                    info["classification_channel_mode"] = cc.get("mode")
    except Exception:
        pass
    return info


def _usageInfo() -> dict[str, Any]:
    try:
        from lifetime_stats import getOverview

        overview = getOverview(daily_days=1)
    except Exception:
        return {}
    return {
        "pieces_seen": int(overview.get("pieces_seen") or 0),
        "pieces_classified": int(overview.get("pieces_classified") or 0),
        "pieces_distributed": int(overview.get("pieces_distributed") or 0),
        "seconds_powered": float(overview.get("seconds_powered") or 0.0),
        "seconds_sorted": float(overview.get("seconds_sorted") or 0.0),
        "best_hour_ppm": float(overview.get("best_hour_ppm") or 0.0),
        "overall_ppm": float(overview.get("overall_ppm") or 0.0),
        "active_days": int(overview.get("active_days") or 0),
        "first_activity_at": overview.get("first_hour"),
        "last_activity_at": overview.get("last_hour"),
    }


def _isRegistered() -> bool:
    try:
        from hive_metadata import getPrimaryHiveTarget

        return getPrimaryHiveTarget() is not None
    except Exception:
        return False


def _accountIdentities() -> dict[str, Any]:
    # Once the operator has voluntarily created a Hive account and registered
    # this machine, we stop being anonymous WITH THEIR CONSENT: we attach the
    # local machine id plus every account's Hive-assigned machine id, so the
    # anonymous install row can be joined to their registered machine(s). Only
    # identifiers the operator already gave to Hive are sent — never tokens.
    # An unregistered machine sends neither field.
    identity: dict[str, Any] = {}
    try:
        from local_state import get_machine_id

        machine_id = get_machine_id()
        if machine_id:
            identity["machine_id"] = machine_id
    except Exception:
        pass
    try:
        from local_state import get_hive_config

        config = get_hive_config()
        targets = config.get("targets", []) if isinstance(config, dict) else []
        accounts = []
        for target in targets:
            if not isinstance(target, dict):
                continue
            target_machine_id = target.get("machine_id")
            if not (isinstance(target_machine_id, str) and target_machine_id.strip()):
                continue
            accounts.append({
                "url": target.get("url"),
                "name": target.get("name"),
                "machine_id": target_machine_id,
            })
        if accounts:
            identity["accounts"] = accounts
    except Exception:
        pass
    return identity


def buildPayload(reason: str) -> dict[str, Any]:
    install = _get_install()
    payload = {
        "install_id": install["install_id"],
        "created_at": install.get("created_at"),
        "reason": reason,
        "software": _softwareInfo(),
        "os": _osInfo(),
        "hardware": _hardwareInfo(),
        "config": _configInfo(),
        "usage": _usageInfo(),
        "uptime": {
            "process_s": round(time.time() - _PROCESS_STARTED_AT, 1),
            "system_s": _systemUptimeS(),
        },
        "registered": _isRegistered(),
    }
    # Account identity — present only for a registered machine (see
    # _accountIdentities): local machine_id and every account's machine_id.
    payload.update(_accountIdentities())
    return payload


def _get_install() -> dict[str, Any]:
    from local_state import get_or_create_telemetry_install

    return get_or_create_telemetry_install()


class StatusPinger:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not reportingEnabled():
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="status-ping", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _sleep(self, seconds: float) -> None:
        # Interruptible sleep so a shutdown doesn't wait out a full hour.
        self._stop.wait(timeout=max(0.0, seconds))

    def _loop(self) -> None:
        self._sleep(random.uniform(INITIAL_DELAY_MIN_S, INITIAL_DELAY_MAX_S))
        reason = "boot"
        while not self._stop.is_set():
            self._pingOnce(reason)
            reason = "periodic"
            self._sleep(INTERVAL_S + random.uniform(0.0, INTERVAL_JITTER_S))

    def _pingOnce(self, reason: str) -> None:
        if not reportingEnabled():
            return
        try:
            payload = buildPayload(reason)
            requests.post(_endpoint(), json=payload, timeout=REQUEST_TIMEOUT_S)
        except Exception:
            # Silent by design — an offline machine skips this ping and the next
            # one (carrying the same cumulative counters) loses nothing.
            pass


_pinger: Optional[StatusPinger] = None
_pinger_lock = threading.Lock()


def getStatusPinger() -> StatusPinger:
    global _pinger
    with _pinger_lock:
        if _pinger is None:
            _pinger = StatusPinger()
        return _pinger
