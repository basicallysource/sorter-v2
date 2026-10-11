"""Keep-alive to every enabled Hive target.

Every HEARTBEAT_INTERVAL_S each enabled target gets a heartbeat: where to find
the machine on its networks, now and then a machine-specs snapshot, and in
reply the limits that target sets for this machine (stored by hive_limits).
Reachability per target is kept for the Hive settings page.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import hive_limits
from hive_telemetry import HiveTelemetryClient
from local_state import get_hive_config
from machine_network import buildNetworkBlock

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 30.0
# How often the heartbeat also carries a full machine-specs snapshot. The first
# heartbeat after start always sends one (so every restart lands a fresh
# timestamped report), then only every half hour to keep the history table from
# growing on each keep-alive. The server hash-dedupes anyway. When the snapshot
# is still incomplete because hardware hasn't finished coming up (no controller
# boards discovered yet), retry on the shorter interval until it fills in.
SPECS_INTERVAL_S = 1800.0
SPECS_RETRY_INTERVAL_S = 60.0


def _collectNetwork() -> dict[str, Any] | None:
    try:
        return buildNetworkBlock()
    except Exception as exc:
        log.debug("Network block collection failed: %s", exc)
        return None


def _collectMachineSpecs() -> dict[str, Any] | None:
    try:
        from machine_specs import buildMachineSpecs

        return buildMachineSpecs()
    except Exception as exc:
        log.debug("Machine specs collection failed: %s", exc)
        return None


class HiveHeartbeat:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._targets: dict[str, dict[str, Any]] = {}
        self._specs_next_at = 0.0  # 0 => send specs on the first heartbeat
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.reload()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="hive-heartbeat")
            self._thread.start()

    def reload(self) -> None:
        """Re-read the targets (after one is added, removed or enabled) and beat now."""
        config = get_hive_config()
        targets = config.get("targets") if isinstance(config, dict) else None
        fresh: dict[str, dict[str, Any]] = {}
        with self._lock:
            for raw in targets if isinstance(targets, list) else []:
                if not isinstance(raw, dict) or not raw.get("enabled"):
                    continue
                target_id, url, token = raw.get("id"), raw.get("url"), raw.get("api_token")
                if not (isinstance(target_id, str) and isinstance(url, str) and isinstance(token, str) and target_id and url and token):
                    continue
                previous = self._targets.get(target_id, {})
                fresh[target_id] = {
                    "name": raw.get("name") if isinstance(raw.get("name"), str) else url,
                    "client": HiveTelemetryClient(url, token, target_id),
                    "server_reachable": previous.get("server_reachable"),
                    "last_beat_at": previous.get("last_beat_at"),
                }
            self._targets = fresh
        self._wake.set()

    def status(self, target_id: str) -> dict[str, Any]:
        with self._lock:
            target = self._targets.get(target_id)
            return {
                "server_reachable": target.get("server_reachable") if target else None,
                "last_beat_at": target.get("last_beat_at") if target else None,
            }

    def _loop(self) -> None:
        while True:
            self._beat()
            self._wake.wait(HEARTBEAT_INTERVAL_S)
            self._wake.clear()

    def _beat(self) -> None:
        with self._lock:
            targets = [(target_id, t["name"], t["client"]) for target_id, t in self._targets.items()]
        if not targets:
            return
        # Build the network block and the specs snapshot at most once per beat
        # (identical across targets); the client drops each per target if its
        # field is off.
        network = _collectNetwork()
        machine_specs = None
        if time.time() >= self._specs_next_at:
            machine_specs = _collectMachineSpecs()
            complete = bool(machine_specs and machine_specs.get("controller_boards"))
            self._specs_next_at = time.time() + (SPECS_INTERVAL_S if complete else SPECS_RETRY_INTERVAL_S)
        for target_id, name, client in targets:
            try:
                reachable, reply = client.heartbeat(network=network, machine_specs=machine_specs)
            except Exception:
                reachable, reply = False, None
            if reply is not None:
                try:
                    hive_limits.setTargetLimits(target_id, reply.get("limits"))
                except Exception as exc:
                    log.warning("Hive limits from %s not stored: %s", name, exc)
            with self._lock:
                target = self._targets.get(target_id)
                if target is None:
                    continue
                was = target.get("server_reachable")
                target["server_reachable"] = reachable
                if reachable:
                    target["last_beat_at"] = time.time()
            if reachable and was is False:
                log.info("Hive server is back online: %s", name)
            elif not reachable and was is not False:
                log.warning("Hive server is unreachable: %s", name)
