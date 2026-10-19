"""Keep-alive to every enabled Hive target.

Every HEARTBEAT_INTERVAL_S each enabled target gets a heartbeat: where to find
the machine on its networks, and in reply the limits that target sets for this
machine (stored by hive_limits) and the version of its defaults block, which
the primary Hive's reply fetches when it changed (hive_defaults). Reachability
per target is kept for the Hive settings page.

The machine specs are a telemetry record (fleet_telemetry) that the sync worker
sends. A Hive that does not take telemetry records yet still gets them here,
now and then, as before.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import hive_defaults
import hive_limits
from hive_uploads import HiveUploads
from local_state import get_hive_config
from machine_network import buildNetworkBlock

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 30.0
# How often the heartbeat carries a machine-specs snapshot to a Hive that does
# not take telemetry records. The first such heartbeat after start always sends
# one, then every half hour; the server hash-dedupes anyway. While the snapshot
# is incomplete because hardware hasn't come up (no controller boards yet), the
# shorter interval until it fills in.
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
    def __init__(self, sync_worker: Any = None) -> None:
        self._sync = sync_worker
        self._lock = threading.Lock()
        self._primary_id: str | None = None
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
        primary = config.get("primary_target_id") if isinstance(config, dict) else None
        fresh: dict[str, dict[str, Any]] = {}
        with self._lock:
            self._primary_id = primary if isinstance(primary, str) else None
            for raw in targets if isinstance(targets, list) else []:
                if not isinstance(raw, dict) or not raw.get("enabled"):
                    continue
                target_id, url, token = raw.get("id"), raw.get("url"), raw.get("api_token")
                if not (isinstance(target_id, str) and isinstance(url, str) and isinstance(token, str) and target_id and url and token):
                    continue
                previous = self._targets.get(target_id, {})
                fresh[target_id] = {
                    "name": raw.get("name") if isinstance(raw.get("name"), str) else url,
                    "client": HiveUploads(url, token, target_id),
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

    def _takesTelemetry(self, target_id: str) -> bool:
        try:
            return self._sync is None or bool(self._sync.takesTelemetry(target_id))
        except Exception:
            return True

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
        # stream is off.
        network = _collectNetwork()
        machine_specs = None
        legacy = [target_id for target_id, _name, _client in targets if not self._takesTelemetry(target_id)]
        if legacy and time.time() >= self._specs_next_at:
            machine_specs = _collectMachineSpecs()
            complete = bool(machine_specs and machine_specs.get("controller_boards"))
            self._specs_next_at = time.time() + (SPECS_INTERVAL_S if complete else SPECS_RETRY_INTERVAL_S)
        for target_id, name, client in targets:
            try:
                reachable, reply = client.heartbeat(
                    network=network,
                    machine_specs=machine_specs if target_id in legacy else None,
                )
            except Exception:
                reachable, reply = False, None
            if reply is not None:
                try:
                    hive_limits.setTargetLimits(target_id, reply.get("limits"))
                except Exception as exc:
                    log.warning("Hive limits from %s not stored: %s", name, exc)
                if target_id == self._primary_id:
                    # The defaults come from the primary Hive alone.
                    hive_defaults.noteVersion(target_id, reply.get("defaults_version"), client.getDefaults)
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
