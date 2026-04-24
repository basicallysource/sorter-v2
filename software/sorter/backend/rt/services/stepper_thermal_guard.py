"""Background guard for TMC2209 overtemperature flags."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from hardware.tmc2209_status import (
    TMC_REG_DRV_STATUS,
    active_temperature_flags,
    overtemperature_fault_flags,
    parse_drv_status,
)


@dataclass(frozen=True)
class StepperThermalFault:
    stepper_name: str
    raw_status: int
    status: dict[str, Any]
    fault_flags: tuple[str, ...]
    temperature_flags: tuple[str, ...]

    @property
    def message(self) -> str:
        flags = ", ".join(self.fault_flags)
        temps = ", ".join(self.temperature_flags) or "none"
        return (
            f"Stepper thermal fault on {self.stepper_name}: {flags} "
            f"(temperature flags: {temps}, DRV_STATUS=0x{self.raw_status:08X})"
        )


class StepperThermalGuard:
    """Poll TMC2209 DRV_STATUS and hard-stop motors on thermal warnings."""

    def __init__(
        self,
        *,
        steppers: Mapping[str, Any],
        on_fault: Callable[[StepperThermalFault], None],
        logger: Any,
        interval_s: float = 2.0,
        stop_on_prewarn: bool = True,
    ) -> None:
        self._steppers = dict(steppers)
        self._on_fault = on_fault
        self._logger = logger
        self._interval_s = max(0.2, float(interval_s))
        self._stop_on_prewarn = bool(stop_on_prewarn)
        self._stop = threading.Event()
        self._fault_latched = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="stepper-thermal-guard",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 1.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout_s)))
        self._thread = None

    def check_once(self) -> StepperThermalFault | None:
        for name, stepper in self._steppers.items():
            reader = getattr(stepper, "read_driver_register", None)
            if not callable(reader):
                continue
            raw = int(reader(TMC_REG_DRV_STATUS))
            status = parse_drv_status(raw)
            fault_flags = tuple(
                overtemperature_fault_flags(
                    status,
                    include_prewarn=self._stop_on_prewarn,
                )
            )
            if not fault_flags:
                continue
            return StepperThermalFault(
                stepper_name=name,
                raw_status=raw,
                status=status,
                fault_flags=fault_flags,
                temperature_flags=tuple(active_temperature_flags(status)),
            )
        return None

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            if self._fault_latched.is_set():
                continue
            try:
                fault = self.check_once()
            except Exception as exc:
                self._logger.warning(f"Stepper thermal guard poll failed: {exc}")
                continue
            if fault is None:
                continue
            self._fault_latched.set()
            self._logger.error(fault.message)
            self._halt_all()
            try:
                self._on_fault(fault)
            except Exception as exc:
                self._logger.warning(f"Stepper thermal guard fault callback failed: {exc}")

    def _halt_all(self) -> None:
        for name, stepper in self._steppers.items():
            errors: list[str] = []
            if hasattr(stepper, "move_at_speed"):
                try:
                    stepper.move_at_speed(0)
                except Exception as exc:
                    errors.append(f"move_at_speed(0): {exc}")
            if hasattr(stepper, "stop"):
                try:
                    stepper.stop()
                except Exception as exc:
                    errors.append(f"stop(): {exc}")
            if hasattr(stepper, "enabled"):
                try:
                    stepper.enabled = False
                except Exception as exc:
                    errors.append(f"disable: {exc}")
            if errors:
                self._logger.warning(
                    f"Stepper thermal guard could not fully halt {name}: {'; '.join(errors)}"
                )
