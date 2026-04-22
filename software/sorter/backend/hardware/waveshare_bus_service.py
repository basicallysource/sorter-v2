from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, TypeVar

from hardware.waveshare_servo import ScServoBus, calibrate_servo as calibrate_servo_impl

T = TypeVar("T")

# After this many consecutive failed bus operations the service attempts a
# soft recovery — close the serial port, wait briefly, reopen, ping. Most
# Feetech / SCServo bus hiccups (framing errors, collision lockups, a
# half-cycled Waveshare dongle) come back after a clean close+reopen.
_SOFT_RECOVERY_FAILURE_THRESHOLD = 3
_SOFT_RECOVERY_REOPEN_DELAY_S = 0.4


class WaveshareBusService:
    def __init__(self, port: str, *, baudrate: int = 1_000_000, timeout: float = 0.05):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._lock = threading.RLock()
        self._bus: ScServoBus | None = None
        self._persistent_users = 0
        self._consecutive_failures = 0
        self._recovery_attempts = 0
        self._logger = logging.getLogger("waveshare_bus")

    @property
    def port(self) -> str:
        return self._port

    def attach_persistent(self) -> None:
        with self._lock:
            self._ensure_open_locked()
            self._persistent_users += 1

    def detach_persistent(self) -> None:
        with self._lock:
            if self._persistent_users > 0:
                self._persistent_users -= 1
            if self._persistent_users == 0:
                self._close_locked()

    def close(self) -> None:
        with self._lock:
            self._persistent_users = 0
            self._close_locked()

    def scan(self, start: int = 1, end: int = 20) -> list[int]:
        return self._execute(lambda bus: bus.scan(start, end))

    def probe_servo_count(self, start: int = 1, end: int = 10) -> int:
        return len(self.scan(start, end))

    def ping(self, servo_id: int) -> bool:
        return self._execute(lambda bus: bus.ping(servo_id))

    def read_servo_info(self, servo_id: int) -> dict[str, Any] | None:
        return self._execute(lambda bus: bus.read_servo_info(servo_id))

    def list_servo_infos(self, start: int = 1, end: int = 32) -> tuple[list[int], list[dict[str, Any]]]:
        def _op(bus: ScServoBus) -> tuple[list[int], list[dict[str, Any]]]:
            found_ids = bus.scan(start, end)
            servos: list[dict[str, Any]] = []
            for servo_id in found_ids:
                info = bus.read_servo_info(servo_id)
                servos.append(info if info is not None else {"id": servo_id, "error": "Could not read servo info"})
            return found_ids, servos

        return self._execute(_op)

    def read_angle_limits(self, servo_id: int) -> tuple[int, int] | None:
        return self._execute(lambda bus: bus.read_angle_limits(servo_id))

    def set_angle_limits(self, servo_id: int, min_val: int, max_val: int) -> bool:
        return self._execute(lambda bus: bus.set_angle_limits(servo_id, min_val, max_val))

    def set_pid(self, servo_id: int, p: int, d: int, i: int) -> bool:
        return self._execute(lambda bus: bus.set_pid(servo_id, p, d, i))

    def set_torque(self, servo_id: int, enable: bool) -> bool:
        return self._execute(lambda bus: bus.set_torque(servo_id, enable))

    def move_to(self, servo_id: int, position: int, time_ms: int = 500) -> bool:
        return self._execute(lambda bus: bus.move_to(servo_id, position, time_ms))

    def read_position(self, servo_id: int) -> int | None:
        return self._execute(lambda bus: bus.read_position(servo_id))

    def read_load(self, servo_id: int) -> int | None:
        return self._execute(lambda bus: bus.read_load(servo_id))

    def set_id(self, old_id: int, new_id: int) -> bool:
        return self._execute(lambda bus: bus.set_id(old_id, new_id))

    def calibrate_servo(self, servo_id: int) -> tuple[int, int]:
        return self._execute(lambda bus: calibrate_servo_impl(bus, servo_id))

    def soft_reset(self) -> bool:
        """Force a close + reopen of the underlying serial port and ping a
        known servo (id=1) to verify the bus is alive. Returns ``True``
        when the bus responds after reopening.
        """
        with self._lock:
            return self._soft_recover_locked("explicit")

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def recovery_attempts(self) -> int:
        return self._recovery_attempts

    def _execute(self, operation: Callable[[ScServoBus], T]) -> T:
        with self._lock:
            bus = self._ensure_open_locked()
            try:
                result = operation(bus)
            except Exception as exc:
                self._consecutive_failures += 1
                self._logger.warning(
                    "waveshare bus op failed on %s (consecutive=%d): %s",
                    self._port,
                    self._consecutive_failures,
                    exc,
                )
                if self._consecutive_failures >= _SOFT_RECOVERY_FAILURE_THRESHOLD:
                    self._soft_recover_locked(reason=f"{self._consecutive_failures} failures")
                raise
            else:
                # Success — reset the failure counter so a single fluke
                # doesn't accumulate toward a recovery trigger.
                self._consecutive_failures = 0
                return result
            finally:
                if self._persistent_users == 0:
                    self._close_locked()

    def _ensure_open_locked(self) -> ScServoBus:
        if self._bus is None:
            self._bus = ScServoBus(self._port, baudrate=self._baudrate, timeout=self._timeout)
        return self._bus

    def _close_locked(self) -> None:
        if self._bus is None:
            return
        try:
            self._bus.close()
        finally:
            self._bus = None

    def _soft_recover_locked(self, reason: str) -> bool:
        """Close the port, pause briefly, reopen, and verify we can still
        talk to the bus. Caller must hold ``self._lock``.
        """
        self._recovery_attempts += 1
        self._logger.warning(
            "waveshare bus soft-recovery on %s (attempt=%d, reason=%s)",
            self._port,
            self._recovery_attempts,
            reason,
        )
        self._close_locked()
        try:
            time.sleep(_SOFT_RECOVERY_REOPEN_DELAY_S)
        except Exception:
            pass
        try:
            bus = self._ensure_open_locked()
        except Exception as exc:
            self._logger.error("waveshare bus reopen on %s failed: %s", self._port, exc)
            return False
        try:
            alive = False
            # Try a small range; the first responding id is proof the bus works.
            for servo_id in (1, 2, 3, 4, 5):
                try:
                    if bus.ping(servo_id):
                        alive = True
                        break
                except Exception:
                    continue
            if alive:
                self._consecutive_failures = 0
                self._logger.info(
                    "waveshare bus soft-recovery on %s succeeded", self._port
                )
            else:
                self._logger.error(
                    "waveshare bus soft-recovery on %s did not get a ping response",
                    self._port,
                )
            return alive
        except Exception as exc:
            self._logger.error("waveshare bus ping after recovery failed: %s", exc)
            return False


class WaveshareBusRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._services: dict[str, WaveshareBusService] = {}

    def get_service(self, port: str, *, baudrate: int = 1_000_000, timeout: float = 0.05) -> WaveshareBusService:
        normalized = port.strip()
        if not normalized:
            raise ValueError("Waveshare service requires a non-empty port.")
        with self._lock:
            service = self._services.get(normalized)
            if service is None:
                service = WaveshareBusService(normalized, baudrate=baudrate, timeout=timeout)
                self._services[normalized] = service
            return service

    def close_service(self, port: str) -> None:
        normalized = port.strip()
        if not normalized:
            return
        with self._lock:
            service = self._services.pop(normalized, None)
        if service is not None:
            service.close()

    def close_all(self) -> None:
        with self._lock:
            services = list(self._services.values())
            self._services.clear()
        for service in services:
            service.close()


_REGISTRY = WaveshareBusRegistry()


def get_waveshare_bus_service(port: str, *, baudrate: int = 1_000_000, timeout: float = 0.05) -> WaveshareBusService:
    return _REGISTRY.get_service(port, baudrate=baudrate, timeout=timeout)


def close_waveshare_bus_service(port: str) -> None:
    _REGISTRY.close_service(port)


def close_all_waveshare_bus_services() -> None:
    _REGISTRY.close_all()
