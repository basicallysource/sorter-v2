from __future__ import annotations

import threading
import time
from typing import Any, Optional

import stepper_telemetry
from global_config import GlobalConfig

# TMC2209 register addresses we read for telemetry. Only readable registers are
# polled here; the config registers (IHOLD_IRUN, TPWMTHRS, TCOOLTHRS, SGTHRS,
# COOLCONF) are write-only over UART and cannot be read back.
REG_GCONF = 0x00
REG_GSTAT = 0x01
REG_IOIN = 0x06
REG_TSTEP = 0x12
REG_SG_RESULT = 0x41
REG_CHOPCONF = 0x6C
REG_DRV_STATUS = 0x6F
REG_PWM_SCALE = 0x71

_MRES_TO_MICROSTEPS = {0: 256, 1: 128, 2: 64, 3: 32, 4: 16, 5: 8, 6: 4, 7: 2, 8: 1}

TELEMETRY_SAMPLE_INTERVAL_S = 0.2
_FLUSH_INTERVAL_S = 2.0
_SG_RESULT_MAX = 1023


def _safeGetattr(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name, None)
    except Exception:
        return None


def safeReadRegister(stepper: Any, address: int) -> Optional[int]:
    try:
        return int(stepper.read_driver_register(address))
    except Exception:
        return None


def decodeDrvStatus(raw: int) -> dict[str, Any]:
    # Bit positions per the TMC2209 datasheet DRV_STATUS (0x6F).
    return {
        "otpw": bool(raw & (1 << 0)),
        "ot": bool(raw & (1 << 1)),
        "s2ga": bool(raw & (1 << 2)),
        "s2gb": bool(raw & (1 << 3)),
        "s2vsa": bool(raw & (1 << 4)),
        "s2vsb": bool(raw & (1 << 5)),
        "ola": bool(raw & (1 << 6)),
        "olb": bool(raw & (1 << 7)),
        "t120": bool(raw & (1 << 8)),
        "t143": bool(raw & (1 << 9)),
        "t150": bool(raw & (1 << 10)),
        "t157": bool(raw & (1 << 11)),
        "cs_actual": (raw >> 16) & 0x1F,
        "stealth": bool(raw & (1 << 30)),
        "stst": bool(raw & (1 << 31)),
    }


def decodeGconf(raw: int) -> dict[str, Any]:
    return {
        "i_scale_analog": bool(raw & (1 << 0)),
        "internal_rsense": bool(raw & (1 << 1)),
        "en_spreadcycle": bool(raw & (1 << 2)),
        "shaft": bool(raw & (1 << 3)),
        "pdn_disable": bool(raw & (1 << 6)),
        "mstep_reg_select": bool(raw & (1 << 7)),
        "multistep_filt": bool(raw & (1 << 8)),
        # StealthChop is active when SpreadCycle is NOT enabled.
        "stealthchop": not bool(raw & (1 << 2)),
    }


def decodeChopconf(raw: int) -> dict[str, Any]:
    mres = (raw >> 24) & 0x0F
    return {
        "microsteps": _MRES_TO_MICROSTEPS.get(mres, 256),
        "intpol": bool(raw & (1 << 28)),
        "vsense": bool(raw & (1 << 17)),
        "toff": raw & 0x0F,
    }


def decodePwmScale(raw: int) -> dict[str, Any]:
    pwm_scale_auto = (raw >> 16) & 0x1FF
    if pwm_scale_auto & 0x100:
        pwm_scale_auto -= 0x200
    return {
        "pwm_scale_sum": raw & 0xFF,
        "pwm_scale_auto": pwm_scale_auto,
    }


def readDriverSettingsSnapshot(stepper: Any) -> dict[str, Any]:
    # Ground-truth read-back of the readable config registers plus the backend's
    # believed-but-unreadable settings, so the UI can show configured vs effective.
    gconf = safeReadRegister(stepper, REG_GCONF)
    gstat = safeReadRegister(stepper, REG_GSTAT)
    ioin = safeReadRegister(stepper, REG_IOIN)
    chopconf = safeReadRegister(stepper, REG_CHOPCONF)
    drv_status = safeReadRegister(stepper, REG_DRV_STATUS)
    pwm_scale = safeReadRegister(stepper, REG_PWM_SCALE)

    registers = {
        "gconf": gconf,
        "gstat": gstat,
        "ioin": ioin,
        "chopconf": chopconf,
        "drv_status": drv_status,
        "pwm_scale": pwm_scale,
    }
    decoded: dict[str, Any] = {}
    if gconf is not None:
        decoded["gconf"] = decodeGconf(gconf)
    if chopconf is not None:
        decoded["chopconf"] = decodeChopconf(chopconf)
    if drv_status is not None:
        decoded["drv_status"] = decodeDrvStatus(drv_status)
    if pwm_scale is not None:
        decoded["pwm_scale"] = decodePwmScale(pwm_scale)

    configured = {
        "last_set_current": _safeGetattr(stepper, "last_set_current"),
        "microsteps": _safeGetattr(stepper, "_microsteps"),
        "stallguard_threshold": _safeGetattr(stepper, "stallguard_threshold"),
        "stallguard_tcoolthrs": _safeGetattr(stepper, "stallguard_tcoolthrs"),
    }
    return {"registers": registers, "decoded": decoded, "configured": configured}


class TmcTelemetryRecorder:
    # Polls a stepper's TMC2209 telemetry registers on its own daemon thread and
    # batches the samples into stepper_telemetry. The shared MCUBus lock serializes
    # these reads against whatever motion command thread is driving the test, so
    # this is safe to run concurrently — it only adds a few ms of bus latency per
    # poll, and step generation runs on a separate firmware core regardless.
    def __init__(
        self,
        gc: GlobalConfig,
        stepper: Any,
        *,
        telemetry_run_id: str,
        stepper_name: str,
        commanded_speed: Optional[int] = None,
        stealthchop: Optional[bool] = None,
        microsteps: Optional[int] = None,
        irun: Optional[int] = None,
        interval_s: float = TELEMETRY_SAMPLE_INTERVAL_S,
    ) -> None:
        self.gc = gc
        self.logger = gc.logger
        self._stepper = stepper
        self._run_id = telemetry_run_id
        self._stepper_name = stepper_name
        self._channel = _safeGetattr(stepper, "channel")
        self._commanded_speed = commanded_speed
        self._stealthchop = stealthchop
        self._microsteps = microsteps
        self._irun = irun
        self._interval_s = max(0.05, float(interval_s))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._buffer: list[dict[str, Any]] = []
        self._buffer_lock = threading.Lock()
        self._sg_min: int | None = None
        self._sg_max: int | None = None
        self._sg_sum = 0
        self._sg_count = 0

    @property
    def run_id(self) -> str:
        return self._run_id

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="ChuteStressTelemetry", daemon=True
        )
        self._thread.start()

    def stop(
        self,
        *,
        status: str = stepper_telemetry.RUN_STATUS_COMPLETED,
        error: Optional[str] = None,
    ) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._flush()
        sg_mean = (self._sg_sum / self._sg_count) if self._sg_count else None
        try:
            stepper_telemetry.finishRun(
                self._run_id,
                status=status,
                sg_min=self._sg_min,
                sg_max=self._sg_max,
                sg_mean=sg_mean,
                error=error,
            )
        except Exception as e:
            self.logger.warning(f"Chute telemetry: finishRun failed: {e}")

    def _run(self) -> None:
        last_flush = time.monotonic()
        while not self._stop_event.is_set():
            tick = time.monotonic()
            try:
                self._sampleOnce()
            except Exception as e:
                self.logger.warning(f"Chute telemetry: sample failed: {e}")
            now = time.monotonic()
            if now - last_flush >= _FLUSH_INTERVAL_S:
                self._flush()
                last_flush = now
            sleep_for = self._interval_s - (time.monotonic() - tick)
            if sleep_for > 0:
                self._stop_event.wait(sleep_for)

    def _sampleOnce(self) -> None:
        sg = safeReadRegister(self._stepper, REG_SG_RESULT)
        drv = safeReadRegister(self._stepper, REG_DRV_STATUS)
        tstep = safeReadRegister(self._stepper, REG_TSTEP)
        pwm = safeReadRegister(self._stepper, REG_PWM_SCALE)
        ioin = safeReadRegister(self._stepper, REG_IOIN)
        cs_actual = decodeDrvStatus(drv)["cs_actual"] if drv is not None else None

        if sg is not None and 0 <= sg <= _SG_RESULT_MAX:
            self._sg_min = sg if self._sg_min is None else min(self._sg_min, sg)
            self._sg_max = sg if self._sg_max is None else max(self._sg_max, sg)
            self._sg_sum += sg
            self._sg_count += 1

        sample = {
            "recorded_at": time.time(),
            "stepper_name": self._stepper_name,
            "channel": self._channel,
            "sg_result": sg,
            "cs_actual": cs_actual,
            "tstep": tstep,
            "drv_status_raw": drv,
            "pwm_scale": pwm,
            "commanded_speed": self._commanded_speed,
            "irun": self._irun,
            "microsteps": self._microsteps,
            "stealthchop": self._stealthchop,
            "loaded": None,
            "acceleration": None,
            "ioin": ioin,
        }
        with self._buffer_lock:
            self._buffer.append(sample)

    def _flush(self) -> None:
        with self._buffer_lock:
            pending = self._buffer
            self._buffer = []
        if not pending:
            return
        try:
            stepper_telemetry.insertSamples(self._run_id, pending)
        except Exception as e:
            self.logger.warning(
                f"Chute telemetry: insertSamples failed ({len(pending)} samples dropped): {e}"
            )
