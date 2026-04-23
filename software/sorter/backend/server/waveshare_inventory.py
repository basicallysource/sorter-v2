from __future__ import annotations

import threading
import time
from typing import Any

import serial.tools.list_ports

from hardware.waveshare_bus_service import get_waveshare_bus_service
from server import shared_state
from server.config_helpers import read_machine_params_config, write_machine_params_config

_MCU_VIDS = {0x2E8A}  # Raspberry Pi Pico
_DEFAULT_SCAN_INTERVAL_S = 10.0
_SCAN_START_ID = 1
_SCAN_END_ID = 32


def _normalize_port(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _active_waveshare_service() -> Any | None:
    active_irl = shared_state.getActiveIRL()
    if active_irl is None:
        return None
    servo_controller = getattr(active_irl, "servo_controller", None)
    return getattr(servo_controller, "bus_service", None)


def _configured_waveshare_port() -> str | None:
    _, config = read_machine_params_config()
    servo = config.get("servo", {})
    if not isinstance(servo, dict):
        return None
    return _normalize_port(servo.get("port"))


def _active_mcu_ports() -> set[str]:
    active_irl = shared_state.getActiveIRL()
    if active_irl is None:
        return set()
    interfaces = getattr(active_irl, "interfaces", {})
    if not isinstance(interfaces, dict):
        return set()

    ports: set[str] = set()
    for interface in interfaces.values():
        port = getattr(interface, "port", None)
        normalized = _normalize_port(port)
        if normalized is not None:
            ports.add(normalized)
    return ports


class WaveshareInventoryManager:
    def __init__(self, *, scan_interval_s: float = _DEFAULT_SCAN_INTERVAL_S) -> None:
        self._scan_interval_s = scan_interval_s
        self._lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: dict[str, Any] = {
            "ports": [],
            "servos_by_port": {},
            "all_servo_ids": [],
            "highest_seen_id": self._read_highest_seen_servo_id(),
            "last_scan_started_at": None,
            "last_scan_at": None,
            "last_error": None,
            "scanning": False,
        }

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="waveshare-inventory", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
        self._stop_event.set()
        self._wake_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def trigger_refresh(self) -> None:
        self._wake_event.set()

    def refresh(self, *, port: str | None = None) -> dict[str, Any]:
        requested_port = _normalize_port(port)
        with self._scan_lock:
            started_at = time.time()
            with self._lock:
                self._snapshot["scanning"] = True
                self._snapshot["last_scan_started_at"] = started_at
                self._snapshot["last_error"] = None
            try:
                next_snapshot = self._scan_inventory(port=requested_port)
            except Exception as exc:
                with self._lock:
                    self._snapshot["scanning"] = False
                    self._snapshot["last_error"] = str(exc)
                    self._snapshot["last_scan_at"] = time.time()
                self._log_warning(f"Waveshare inventory refresh failed: {exc}")
            else:
                with self._lock:
                    self._snapshot.update(next_snapshot)
                    self._snapshot["scanning"] = False
                    self._snapshot["last_error"] = None
                    self._snapshot["last_scan_at"] = time.time()
        return self.get_status(port=requested_port)

    def get_status(self, *, port: str | None = None) -> dict[str, Any]:
        requested_port = _normalize_port(port)
        with self._lock:
            snapshot = {
                "ports": [dict(entry) for entry in self._snapshot.get("ports", [])],
                "servos_by_port": {
                    device: [dict(servo) for servo in servos]
                    for device, servos in self._snapshot.get("servos_by_port", {}).items()
                    if isinstance(device, str) and isinstance(servos, list)
                },
                "all_servo_ids": list(self._snapshot.get("all_servo_ids", [])),
                "highest_seen_id": int(self._snapshot.get("highest_seen_id", 0) or 0),
                "last_scan_started_at": self._snapshot.get("last_scan_started_at"),
                "last_scan_at": self._snapshot.get("last_scan_at"),
                "last_error": self._snapshot.get("last_error"),
                "scanning": bool(self._snapshot.get("scanning")),
            }

        current_port = self._select_current_port(
            requested_port=requested_port,
            ports=snapshot["ports"],
            servos_by_port=snapshot["servos_by_port"],
        )
        servos = snapshot["servos_by_port"].get(current_port, []) if current_port is not None else []
        return {
            "ok": True,
            "current_port": current_port,
            "ports": snapshot["ports"],
            "servos": servos,
            "all_servo_ids": snapshot["all_servo_ids"],
            "highest_seen_id": snapshot["highest_seen_id"],
            "suggested_next_id": self._suggested_next_id(
                servos=servos,
                highest_seen_id=snapshot["highest_seen_id"],
            ),
            "scanning": snapshot["scanning"],
            "last_scan_started_at": snapshot["last_scan_started_at"],
            "last_scan_at": snapshot["last_scan_at"],
            "last_error": snapshot["last_error"],
        }

    def get_known_servo_ids(self, *, port: str | None = None) -> list[int]:
        status = self.get_status(port=port)
        all_ids = status.get("all_servo_ids", [])
        return sorted(
            {
                int(servo_id)
                for servo_id in all_ids
                if isinstance(servo_id, int) and not isinstance(servo_id, bool) and servo_id > 0
            }
        )

    def _run_loop(self) -> None:
        self.refresh()
        while not self._stop_event.is_set():
            woke_early = self._wake_event.wait(self._scan_interval_s)
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            if woke_early or self._scan_interval_s > 0:
                self.refresh()

    def _scan_inventory(self, *, port: str | None = None) -> dict[str, Any]:
        with self._lock:
            previous_last_error = self._snapshot.get("last_error")
            previous_servos_by_port = {
                device: [dict(servo) for servo in servos]
                for device, servos in self._snapshot.get("servos_by_port", {}).items()
                if isinstance(device, str) and isinstance(servos, list)
            }

        configured_port = _configured_waveshare_port()
        active_service = _active_waveshare_service()
        live_port = _normalize_port(getattr(active_service, "port", None))
        mcu_ports = _active_mcu_ports()
        is_homing = shared_state.hardware_state == "homing"

        port_meta: dict[str, dict[str, Any]] = {}
        discovered_devices: list[str] = []
        for candidate in serial.tools.list_ports.comports():
            if candidate.vid is None:
                continue
            if candidate.vid in _MCU_VIDS:
                continue
            device = _normalize_port(candidate.device)
            if device is None or device in mcu_ports:
                continue
            discovered_devices.append(device)
            port_meta[device] = {
                "device": device,
                "product": getattr(candidate, "product", None) or "Serial Device",
                "serial": getattr(candidate, "serial_number", None),
            }

        ordered_devices: list[str] = []
        seen_devices: set[str] = set()

        def _add_device(device: str | None) -> None:
            if device is None or device in seen_devices:
                return
            seen_devices.add(device)
            ordered_devices.append(device)

        _add_device(live_port)
        _add_device(configured_port)
        _add_device(port)
        for device in discovered_devices:
            _add_device(device)

        servos_by_port: dict[str, list[dict[str, Any]]] = {}
        all_found_ids: set[int] = set()
        ports: list[dict[str, Any]] = []

        for device in ordered_devices:
            meta = dict(port_meta.get(device, {}))
            if "device" not in meta:
                meta["device"] = device
            if "product" not in meta:
                if device == live_port:
                    meta["product"] = "Active Waveshare bus"
                elif device == configured_port:
                    meta["product"] = "Configured Waveshare port"
                else:
                    meta["product"] = "Serial Device"
            if "serial" not in meta:
                meta["serial"] = None

            previous_servos = [dict(servo) for servo in previous_servos_by_port.get(device, [])]
            servos = previous_servos if is_homing else []
            scan_error: str | None = None
            if not is_homing:
                try:
                    if active_service is not None and device == live_port:
                        _, servos = active_service.list_servo_infos(_SCAN_START_ID, _SCAN_END_ID)
                    else:
                        service = get_waveshare_bus_service(device, timeout=0.02)
                        _, servos = service.list_servo_infos(_SCAN_START_ID, _SCAN_END_ID)
                except Exception as exc:
                    scan_error = str(exc)
                    servos = previous_servos

            normalized_servos = self._normalize_servo_list(servos)
            if normalized_servos:
                servos_by_port[device] = normalized_servos
                for servo in normalized_servos:
                    servo_id = servo.get("id")
                    if isinstance(servo_id, int) and not isinstance(servo_id, bool) and servo_id > 0:
                        all_found_ids.add(servo_id)

            servo_count = len(normalized_servos)
            confirmed = servo_count > 0 or (device == live_port and active_service is not None)
            entry = {
                "device": device,
                "product": meta["product"],
                "serial": meta["serial"],
                "servo_count": servo_count,
                "confirmed": confirmed,
            }
            if scan_error is not None:
                entry["error"] = scan_error
            ports.append(entry)

        highest_seen_id = self._update_highest_seen_servo_id(sorted(all_found_ids))
        return {
            "ports": ports,
            "servos_by_port": servos_by_port,
            "all_servo_ids": sorted(all_found_ids),
            "highest_seen_id": highest_seen_id,
            "last_error": previous_last_error,
        }

    def _select_current_port(
        self,
        *,
        requested_port: str | None,
        ports: list[dict[str, Any]],
        servos_by_port: dict[str, list[dict[str, Any]]],
    ) -> str | None:
        available_devices = {
            entry.get("device")
            for entry in ports
            if isinstance(entry, dict) and isinstance(entry.get("device"), str)
        }
        configured_port = _configured_waveshare_port()
        live_port = _normalize_port(getattr(_active_waveshare_service(), "port", None))

        for candidate in (requested_port, live_port, configured_port):
            if candidate is not None and (candidate in available_devices or candidate in servos_by_port):
                return candidate

        for entry in ports:
            if entry.get("servo_count", 0) > 0 and isinstance(entry.get("device"), str):
                return entry["device"]

        for entry in ports:
            if isinstance(entry.get("device"), str):
                return entry["device"]
        return None

    def _suggested_next_id(self, *, servos: list[dict[str, Any]], highest_seen_id: int) -> int | None:
        used_ids = {
            servo_id
            for servo_id in (
                servo.get("id")
                for servo in servos
                if isinstance(servo, dict)
            )
            if isinstance(servo_id, int) and not isinstance(servo_id, bool) and 1 <= servo_id <= 253
        }
        next_id = max(highest_seen_id, 1) + 1
        while next_id in used_ids and next_id <= 253:
            next_id += 1
        return next_id if next_id <= 253 else None

    def _normalize_servo_list(self, servos: list[dict[str, Any]] | Any) -> list[dict[str, Any]]:
        if not isinstance(servos, list):
            return []
        normalized: list[dict[str, Any]] = []
        for servo in servos:
            if not isinstance(servo, dict):
                continue
            servo_id = servo.get("id")
            if not isinstance(servo_id, int) or isinstance(servo_id, bool) or servo_id <= 0:
                continue
            normalized.append(dict(servo))
        normalized.sort(key=lambda entry: int(entry["id"]))
        return normalized

    def _read_highest_seen_servo_id(self) -> int:
        _, config = read_machine_params_config()
        servo = config.get("servo", {})
        if isinstance(servo, dict):
            value = servo.get("highest_seen_id")
            if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
                return value
        return 0

    def _update_highest_seen_servo_id(self, found_ids: list[int]) -> int:
        if not found_ids:
            return self._read_highest_seen_servo_id()

        max_found = max((servo_id for servo_id in found_ids if servo_id > 1), default=0)
        current_highest = self._read_highest_seen_servo_id()
        next_highest = max(current_highest, max_found)
        if next_highest <= current_highest:
            return current_highest

        params_path, config = read_machine_params_config()
        servo = config.get("servo", {})
        if not isinstance(servo, dict):
            servo = {}
        servo["highest_seen_id"] = next_highest
        config["servo"] = servo
        try:
            write_machine_params_config(params_path, config)
        except Exception as exc:
            self._log_warning(f"Failed to persist Waveshare highest_seen_id={next_highest}: {exc}")
        return next_highest

    def _log_warning(self, message: str) -> None:
        logger = getattr(shared_state.gc_ref, "logger", None)
        if logger is not None and hasattr(logger, "warning"):
            logger.warning(message)


_inventory_manager: WaveshareInventoryManager | None = None
_inventory_lock = threading.Lock()


def get_waveshare_inventory_manager() -> WaveshareInventoryManager:
    global _inventory_manager
    with _inventory_lock:
        if _inventory_manager is None:
            _inventory_manager = WaveshareInventoryManager()
        return _inventory_manager
