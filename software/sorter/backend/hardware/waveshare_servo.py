"""Waveshare SC series serial bus servo driver.

Implements the Feetech SC protocol (SC09, SC15, SC40, SC60) over half-duplex
TTL serial at 1 Mbps.  The driver provides both a low-level bus class
(`ScServoBus`) and a high-level `WaveshareServoMotor` that is a drop-in
replacement for the PCA9685-based `ServoMotor` used elsewhere in the sorter.

SC series uses **big-endian** byte order for 16-bit register values.

Auto-calibration
----------------
Setup can explicitly calibrate each servo by probing its physical min/max
positions with short, guarded moves. Runtime initialization never starts this
process implicitly; an uncalibrated servo is safer offline than moving
unexpectedly during machine startup.
"""

import logging
import struct
import threading
import time
from typing import Any, Dict, NamedTuple, Protocol

import serial

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SC Protocol constants
# ---------------------------------------------------------------------------

# Instructions
_INST_PING = 0x01
_INST_READ = 0x02
_INST_WRITE = 0x03

# Register addresses — EEPROM
_REG_MODEL_L = 3
_REG_ID = 5
_REG_MIN_ANGLE_L = 9
_REG_MAX_ANGLE_L = 11
_REG_P_COEF = 21
_REG_D_COEF = 22
_REG_I_COEF = 23
_REG_PUNCH_L = 24

# Register addresses — SRAM
_REG_TORQUE_ENABLE = 40
_REG_GOAL_POSITION_L = 42
_REG_LOCK = 48
_REG_PRESENT_POSITION_L = 56
_REG_PRESENT_LOAD_L = 60
_REG_PRESENT_VOLTAGE = 62
_REG_PRESENT_TEMPERATURE = 63
_REG_MOVING = 66
_REG_PRESENT_CURRENT_L = 69

# Bounded retries for communication failures (short read, wrong responder id,
# checksum mismatch). A nonzero status byte is NOT a comm failure.
_SEND_ATTEMPTS = 3
_SEND_RETRY_DELAY_S = 0.005


def _checksum(data: bytes) -> int:
    return (~sum(data)) & 0xFF


class ScServoBus:
    """Low-level half-duplex serial bus for SC servos."""

    def __init__(self, port: str, baudrate: int = 1_000_000, timeout: float = 0.05):
        # exclusive=True prevents two processes from interleaving packets on
        # the half-duplex bus; write_timeout bounds a wedged USB dongle.
        self._serial = serial.Serial(
            port, baudrate=baudrate, timeout=timeout, write_timeout=0.1, exclusive=True
        )
        self._lock = threading.Lock()
        self._last_status: dict[int, int] = {}

    def close(self):
        self._serial.close()

    # -- packet I/O ---------------------------------------------------------

    def _read_packet(self) -> bytes | None:
        first = self._serial.read(1)
        if len(first) < 1:
            return None

        while True:
            if first == b"\xFF":
                second = self._serial.read(1)
                if len(second) < 1:
                    return None
                if second == b"\xFF":
                    break
                first = second
                continue

            first = self._serial.read(1)
            if len(first) < 1:
                return None

        meta = self._serial.read(3)
        if len(meta) < 3:
            return None

        resp_length = meta[1]
        if resp_length < 2:
            return None

        tail = self._serial.read(resp_length - 1)
        if len(tail) < resp_length - 1:
            return None

        return b"\xFF\xFF" + meta + tail

    def _send(
        self,
        servo_id: int,
        instruction: int,
        params: bytes = b"",
        *,
        attempts: int = _SEND_ATTEMPTS,
    ) -> bytes | None:
        with self._lock:
            length = len(params) + 2
            pkt = bytes([0xFF, 0xFF, servo_id, length, instruction]) + params
            pkt += bytes([_checksum(pkt[2:])])

            for attempt in range(attempts):
                if attempt > 0:
                    time.sleep(_SEND_RETRY_DELAY_S)
                payload = self._transact(servo_id, pkt)
                if payload is not None:
                    return payload
            return None

    def _transact(self, servo_id: int, pkt: bytes) -> bytes | None:
        """One write + response cycle. Returns the payload, or None on a
        communication failure (short read, wrong responder id, bad checksum).
        """
        self._serial.reset_input_buffer()
        self._serial.write(pkt)
        self._serial.flush()

        packet = self._read_packet()
        if packet == pkt:  # half-duplex adapters echo the request
            packet = self._read_packet()
        if packet is None or len(packet) < 6:
            return None

        if packet[2] != servo_id or packet[3] < 2:
            return None
        if packet[-1] != _checksum(packet[2:-1]):
            return None

        # packet[4] carries the servo's hardware status flags (overload,
        # overheat, voltage, angle-limit). The servo answered, so the
        # transaction succeeded — record the flags, don't fail the call.
        self._record_status(servo_id, packet[4])
        return packet[5:-1]

    def _record_status(self, servo_id: int, status: int) -> None:
        if self._last_status.get(servo_id, 0) == status:
            return
        self._last_status[servo_id] = status
        if status:
            logger.warning(f"Servo {servo_id}: hardware status flags 0x{status:02X}")
        else:
            logger.info(f"Servo {servo_id}: hardware status flags cleared")

    def last_status_flags(self, servo_id: int) -> int:
        return self._last_status.get(servo_id, 0)

    # -- helpers ------------------------------------------------------------

    def ping(self, servo_id: int, *, attempts: int = _SEND_ATTEMPTS) -> bool:
        return self._send(servo_id, _INST_PING, attempts=attempts) is not None

    def read_bytes(self, servo_id: int, address: int, count: int) -> bytes | None:
        resp = self._send(servo_id, _INST_READ, bytes([address, count]))
        if resp is None or len(resp) < count:
            return None
        return resp[:count]

    def write_bytes(self, servo_id: int, address: int, data: bytes) -> bool:
        return self._send(servo_id, _INST_WRITE, bytes([address]) + data) is not None

    def read_word(self, servo_id: int, address: int) -> int | None:
        data = self.read_bytes(servo_id, address, 2)
        if data is None:
            return None
        return struct.unpack(">H", data)[0]  # big-endian

    def write_word(self, servo_id: int, address: int, value: int) -> bool:
        return self.write_bytes(servo_id, address, struct.pack(">H", value))

    def write_byte(self, servo_id: int, address: int, value: int) -> bool:
        return self.write_bytes(servo_id, address, bytes([value]))

    # -- high-level servo commands ------------------------------------------

    def scan(self, start: int = 1, end: int = 20) -> list[int]:
        found = []
        for sid in range(start, end + 1):
            # Absent IDs are expected during a sweep; retrying their timeouts
            # would triple the scan's bus-lock hold time for nothing.
            if self.ping(sid, attempts=1):
                found.append(sid)
            time.sleep(0.002)
        return found

    def set_torque(self, servo_id: int, enable: bool) -> bool:
        return self.write_byte(servo_id, _REG_TORQUE_ENABLE, 1 if enable else 0)

    def move_to(self, servo_id: int, position: int, time_ms: int = 500) -> bool:
        position = max(0, min(1023, position))
        pos_bytes = struct.pack(">H", position)
        time_bytes = struct.pack(">H", time_ms)
        speed_bytes = struct.pack(">H", 0)
        return self.write_bytes(
            servo_id, _REG_GOAL_POSITION_L,
            pos_bytes + time_bytes + speed_bytes,
        )

    def read_position(self, servo_id: int) -> int | None:
        val = self.read_word(servo_id, _REG_PRESENT_POSITION_L)
        if val is None:
            return None
        return val & 0x03FF

    def read_load(self, servo_id: int) -> int | None:
        val = self.read_word(servo_id, _REG_PRESENT_LOAD_L)
        if val is None:
            return None
        raw = val & 0x3FF
        if val & 0x400:
            return -raw
        return raw

    def is_moving(self, servo_id: int) -> bool:
        data = self.read_bytes(servo_id, _REG_MOVING, 1)
        if data is None:
            return False
        return data[0] != 0

    def read_angle_limits(self, servo_id: int) -> tuple[int, int] | None:
        data = self.read_bytes(servo_id, _REG_MIN_ANGLE_L, 4)
        if data is None or len(data) < 4:
            return None
        min_angle = struct.unpack(">H", data[0:2])[0]
        max_angle = struct.unpack(">H", data[2:4])[0]
        return min_angle, max_angle

    def set_angle_limits(self, servo_id: int, min_val: int, max_val: int) -> bool:
        self.write_byte(servo_id, _REG_LOCK, 0)  # unlock EEPROM
        time.sleep(0.01)
        data = struct.pack(">H", min_val) + struct.pack(">H", max_val)
        result = self.write_bytes(servo_id, _REG_MIN_ANGLE_L, data)
        time.sleep(0.01)
        self.write_byte(servo_id, _REG_LOCK, 1)  # lock EEPROM
        return result

    def set_pid(self, servo_id: int, p: int, d: int, i: int) -> bool:
        self.write_byte(servo_id, _REG_LOCK, 0)
        time.sleep(0.01)
        result = self.write_bytes(servo_id, _REG_P_COEF, bytes([p, d, i]))
        time.sleep(0.01)
        self.write_byte(servo_id, _REG_LOCK, 1)
        return result

    def set_punch(self, servo_id: int, punch: int) -> bool:
        punch = max(0, min(1023, int(punch)))
        self.write_byte(servo_id, _REG_LOCK, 0)
        time.sleep(0.01)
        result = self.write_word(servo_id, _REG_PUNCH_L, punch)
        time.sleep(0.01)
        self.write_byte(servo_id, _REG_LOCK, 1)
        return result

    def set_id(self, old_id: int, new_id: int) -> bool:
        """Change a servo's ID.  Requires EEPROM unlock."""
        if new_id < 1 or new_id > 253:
            return False
        self.write_byte(old_id, _REG_LOCK, 0)
        time.sleep(0.01)
        result = self.write_byte(old_id, _REG_ID, new_id)
        time.sleep(0.01)
        self.write_byte(new_id, _REG_LOCK, 1)
        return result

    def read_servo_info(self, servo_id: int) -> dict | None:
        """Read identification and live telemetry from a servo."""
        if not self.ping(servo_id):
            return None

        model = self.read_word(servo_id, _REG_MODEL_L)
        position = self.read_position(servo_id)
        load = self.read_load(servo_id)
        limits = self.read_angle_limits(servo_id)

        temp_data = self.read_bytes(servo_id, _REG_PRESENT_VOLTAGE, 2)
        voltage: int | None = None
        temperature: int | None = None
        if temp_data is not None and len(temp_data) >= 2:
            voltage = temp_data[0]
            temperature = temp_data[1]

        current = self.read_word(servo_id, _REG_PRESENT_CURRENT_L)

        pid_data = self.read_bytes(servo_id, _REG_P_COEF, 3)
        pid = None
        if pid_data is not None and len(pid_data) >= 3:
            pid = {"p": pid_data[0], "d": pid_data[1], "i": pid_data[2]}

        model_name = None
        if model is not None:
            # Model detection based on observed firmware values (see sc_servo.rs)
            if model in (4, 9, 0x0400, 0x0504, 0x0405, 0x0900):
                model_name = "SC09"
            elif model in (15, 0x0F00, 0x050F, 0x0F05):
                model_name = "SC15"
            elif model in (40, 0x2800):
                model_name = "SC40"
            elif model in (60, 0x3C00):
                model_name = "SC60"

        info = {
            "id": servo_id,
            "model": model,
            "model_name": model_name,
            "position": position,
            "load": load,
            "min_limit": limits[0] if limits else None,
            "max_limit": limits[1] if limits else None,
            "voltage": round(voltage / 10.0, 1) if voltage is not None else None,
            "temperature": temperature,
            "current": current,
            "pid": pid,
        }
        status_flags = self.last_status_flags(servo_id)
        if status_flags:
            info["status_flags"] = status_flags
        return info


class ServoBus(Protocol):
    """Servo bus operations needed by the motor and calibration.

    Satisfied by both `ScServoBus` and `WaveshareBusService` (the production
    path — servo_controller hands the motor the shared bus service).
    """

    def set_torque(self, servo_id: int, enable: bool) -> bool: ...
    def move_to(self, servo_id: int, position: int, time_ms: int = 500) -> bool: ...
    def read_position(self, servo_id: int) -> int | None: ...
    def read_load(self, servo_id: int) -> int | None: ...
    def read_angle_limits(self, servo_id: int) -> tuple[int, int] | None: ...
    def set_angle_limits(self, servo_id: int, min_val: int, max_val: int) -> bool: ...
    def set_pid(self, servo_id: int, p: int, d: int, i: int) -> bool: ...


# ---------------------------------------------------------------------------
# Auto-calibration
# ---------------------------------------------------------------------------

_CAL_INITIAL_STEP_SIZE = 8
_CAL_CONFIRM_STEP_SIZE = 4
_CAL_DEADBAND_ESCAPE_STEP_SIZE = 24
_CAL_MAX_STEP_SIZE = 32
_CAL_BASE_MOVE_TIME_MS = 120
_CAL_MOVE_MS_PER_COUNT = 2.0
_CAL_MAX_MOVE_TIME_MS = 700
_CAL_SETTLE_MS = 120
_CAL_LOAD_THRESHOLD = 220
_CAL_MARGIN = 5
_CAL_MIN_POSITION = 0
_CAL_MAX_POSITION = 1023
_CAL_SERVO_RANGE_DEGREES = 300
_CAL_MIN_USABLE_DEGREES = 70
_CAL_MIN_USABLE_SPAN = (
    _CAL_MAX_POSITION * _CAL_MIN_USABLE_DEGREES + _CAL_SERVO_RANGE_DEGREES - 1
) // _CAL_SERVO_RANGE_DEGREES
_CAL_NEAR_TARGET_TOLERANCE = 10
_CAL_MIN_PROGRESS = 3
_CAL_POLL_COUNT = 3
_CAL_POLL_INTERVAL_S = 0.05
_CAL_MAX_ENVELOPE_PROBES = 80
_CAL_MAX_TEMPERATURE_C = 55
_CAL_STATUS_FAULT_MASK = 0x3F
_CAL_MAX_TRUSTED_EXISTING_SPAN_FOR_SHRINK_GUARD = 512
_CAL_CENTER_TOLERANCE = 20
_SERVO_TUNING_P = 40
_SERVO_TUNING_D = 32
_SERVO_TUNING_I = 20
_SERVO_TUNING_PUNCH = 80


class _ProbeResult(NamedTuple):
    target: int
    start_position: int
    position: int
    load: int
    reached_target: bool
    high_load: bool


def _limits_look_uncalibrated(min_lim: int, max_lim: int) -> bool:
    span = max_lim - min_lim
    if span < _CAL_MIN_USABLE_SPAN:
        return True
    # 0-1023 is the factory/software range. A previous calibration run that
    # only trimmed the safety margin is still effectively uncalibrated.
    return min_lim <= _CAL_MARGIN and max_lim >= _CAL_MAX_POSITION - _CAL_MARGIN - 1


def _read_angle_limits_with_retry(bus: ServoBus, servo_id: int) -> tuple[int, int] | None:
    limits: tuple[int, int] | None = None
    for attempt in range(3):
        if attempt > 0:
            time.sleep(0.02)
        limits = bus.read_angle_limits(servo_id)
        if limits is not None:
            return limits
    return limits


def _read_calibration_info(bus: ServoBus, servo_id: int) -> dict[str, Any]:
    reader = getattr(bus, "read_servo_info", None)
    if not callable(reader):
        load = bus.read_load(servo_id)
        return {"load": load}
    try:
        info = reader(servo_id)
    except Exception as exc:
        raise RuntimeError(f"Cannot read safety telemetry of servo {servo_id}: {exc}") from exc
    if not isinstance(info, dict):
        raise RuntimeError(f"Cannot read safety telemetry of servo {servo_id}")
    return info


def _assert_calibration_safe(bus: ServoBus, servo_id: int, stage: str) -> dict[str, Any]:
    info = _read_calibration_info(bus, servo_id)
    flags = int(info.get("status_flags") or 0)
    if flags & _CAL_STATUS_FAULT_MASK:
        raise RuntimeError(
            f"Servo {servo_id} reported hardware status 0x{flags:02X} during {stage}; "
            "calibration aborted"
        )

    temperature = info.get("temperature")
    if isinstance(temperature, (int, float)) and temperature >= _CAL_MAX_TEMPERATURE_C:
        raise RuntimeError(
            f"Servo {servo_id} temperature is {temperature}C during {stage}; "
            "calibration aborted"
        )

    return info


def _apply_servo_drive_tuning(bus: ServoBus, servo_id: int, *, stage: str) -> None:
    if not bus.set_pid(servo_id, _SERVO_TUNING_P, _SERVO_TUNING_D, _SERVO_TUNING_I):
        logger.warning(f"Servo {servo_id}: could not update PID during {stage}")

    set_punch = getattr(bus, "set_punch", None)
    if callable(set_punch):
        try:
            if not set_punch(servo_id, _SERVO_TUNING_PUNCH):
                logger.warning(f"Servo {servo_id}: could not update punch during {stage}")
        except Exception as exc:
            logger.warning(f"Servo {servo_id}: could not update punch during {stage}: {exc}")


def calibrate_servo(bus: ServoBus, servo_id: int, *, force: bool = False) -> tuple[int, int]:
    """Find the physical min/max of a servo with guarded envelope probes.

    Returns (safe_min, safe_max) with a small safety margin applied.
    Raises RuntimeError if calibration fails.
    """
    logger.info(f"Calibrating servo {servo_id}...")

    original_limits = _read_angle_limits_with_retry(bus, servo_id)
    if original_limits is None:
        raise RuntimeError(f"Cannot read stored angle limits of servo {servo_id}")
    original_span = original_limits[1] - original_limits[0]
    original_limits_are_factory_range = (
        original_limits[0] <= _CAL_MARGIN
        and original_limits[1] >= _CAL_MAX_POSITION - _CAL_MARGIN - 1
    )
    original_limits_are_trusted = (
        not _limits_look_uncalibrated(original_limits[0], original_limits[1])
        and original_span <= _CAL_MAX_TRUSTED_EXISTING_SPAN_FOR_SHRINK_GUARD
    )
    original_limits_are_centerable = (
        original_span >= _CAL_CENTER_TOLERANCE * 2
        and original_span <= _CAL_MAX_TRUSTED_EXISTING_SPAN_FOR_SHRINK_GUARD
        and not original_limits_are_factory_range
    )
    if not force and not _limits_look_uncalibrated(original_limits[0], original_limits[1]):
        _assert_calibration_safe(bus, servo_id, "stored-range check")
        logger.info(
            f"Servo {servo_id}: stored limits {original_limits[0]}-{original_limits[1]} "
            "already look calibrated; skipping envelope search"
        )
        return original_limits

    def move_time_ms(start_pos: int, target: int) -> int:
        travel = abs(target - start_pos)
        return min(
            _CAL_MAX_MOVE_TIME_MS,
            max(_CAL_BASE_MOVE_TIME_MS, int(_CAL_BASE_MOVE_TIME_MS + travel * _CAL_MOVE_MS_PER_COUNT)),
        )

    def execute_probe(target: int, direction: int) -> _ProbeResult:
        label = "minimum" if direction < 0 else "maximum"
        _assert_calibration_safe(bus, servo_id, f"{label} probe")

        start_sample = bus.read_position(servo_id)
        if start_sample is None:
            raise RuntimeError(f"Cannot read position of servo {servo_id} before calibration probe")

        duration_ms = move_time_ms(start_sample, target)
        try:
            if not bus.set_torque(servo_id, True):
                raise RuntimeError(f"Cannot enable torque on servo {servo_id}")
            time.sleep(0.01)
            if not bus.move_to(servo_id, target, duration_ms):
                raise RuntimeError(
                    f"Servo {servo_id} move command failed while probing {label} limit"
                )
            time.sleep(duration_ms / 1000.0 + _CAL_SETTLE_MS / 1000.0)

            last_pos: int | None = None
            last_load: int | None = None
            reached_target = False
            valid_samples = 0

            for _ in range(_CAL_POLL_COUNT):
                time.sleep(_CAL_POLL_INTERVAL_S)
                pos = bus.read_position(servo_id)
                load = bus.read_load(servo_id)
                if pos is None or load is None:
                    continue

                valid_samples += 1
                last_pos = pos
                last_load = load
                reached_target = reached_target or abs(pos - target) < _CAL_NEAR_TARGET_TOLERANCE

            if valid_samples == 0 or last_pos is None or last_load is None:
                raise RuntimeError(f"Servo {servo_id} telemetry disappeared while probing {label} limit")

            high_load = (
                abs(last_load) >= _CAL_LOAD_THRESHOLD
                and abs(last_pos - target) >= _CAL_NEAR_TARGET_TOLERANCE
            )
            return _ProbeResult(
                target=target,
                start_position=start_sample,
                position=last_pos,
                load=last_load,
                reached_target=reached_target,
                high_load=high_load,
            )
        finally:
            bus.set_torque(servo_id, False)

    def grow_step(step: int) -> int:
        return min(_CAL_MAX_STEP_SIZE, max(step + 2, int(round(step * 1.45))))

    def find_envelope(start_pos: int) -> tuple[int, int]:
        states: dict[int, dict[str, Any]] = {
            -1: {
                "best": start_pos,
                "step": _CAL_INITIAL_STEP_SIZE,
                "active": True,
                "found": False,
                "confirming": False,
                "successes": 0,
            },
            1: {
                "best": start_pos,
                "step": _CAL_INITIAL_STEP_SIZE,
                "active": True,
                "found": False,
                "confirming": False,
                "successes": 0,
            },
        }

        for _ in range(_CAL_MAX_ENVELOPE_PROBES):
            any_active = False
            for direction in (-1, 1):
                state = states[direction]
                if not state["active"]:
                    continue
                any_active = True

                label = "minimum" if direction < 0 else "maximum"
                base = int(state["best"])
                step = _CAL_CONFIRM_STEP_SIZE if state["confirming"] else int(state["step"])
                target = max(_CAL_MIN_POSITION, min(_CAL_MAX_POSITION, base + direction * step))
                if target == base:
                    state["active"] = False
                    state["found"] = False
                    logger.info(
                        f"  Servo {servo_id}: reached software {label} boundary before a mechanical stop"
                    )
                    continue

                result = execute_probe(target, direction)
                progress = (base - result.position) if direction < 0 else (result.position - base)

                if result.high_load and not result.reached_target:
                    if progress >= _CAL_MIN_PROGRESS:
                        state["best"] = result.position
                    state["active"] = False
                    state["found"] = True
                    logger.info(
                        f"  Servo {servo_id}: {label} limit found near {state['best']} "
                        f"(target={target}, pos={result.position}, load={result.load})"
                    )
                    continue

                if progress >= _CAL_MIN_PROGRESS:
                    state["best"] = result.position
                    state["step"] = grow_step(int(state["step"]))
                    state["confirming"] = False
                    state["successes"] = int(state["successes"]) + 1
                    logger.info(
                        f"  Servo {servo_id}: {label} envelope extended to {result.position} "
                        f"(step={state['step']})"
                    )
                    continue

                if int(state["successes"]) == 0 and int(state["step"]) < _CAL_DEADBAND_ESCAPE_STEP_SIZE:
                    state["step"] = min(_CAL_DEADBAND_ESCAPE_STEP_SIZE, grow_step(int(state["step"])))
                    state["confirming"] = False
                    logger.info(
                        f"  Servo {servo_id}: {label} probe made no progress "
                        f"(target={target}, pos={result.position}); increasing first probe "
                        f"to {state['step']}"
                    )
                    continue

                if not state["confirming"]:
                    state["confirming"] = True
                    state["step"] = _CAL_CONFIRM_STEP_SIZE
                    logger.info(
                        f"  Servo {servo_id}: {label} probe made no progress "
                        f"(target={target}, pos={result.position}); confirming once"
                    )
                    continue

                state["active"] = False
                state["found"] = True
                logger.info(
                    f"  Servo {servo_id}: {label} limit confirmed near {base} "
                    f"(target={target}, pos={result.position}, load={result.load})"
                )

            if not any_active:
                break

        min_state = states[-1]
        max_state = states[1]
        if min_state["active"] or max_state["active"]:
            raise RuntimeError(f"Servo {servo_id} calibration exceeded safe envelope probe limit")
        if not min_state["found"]:
            raise RuntimeError(
                f"Servo {servo_id} calibration failed: no minimum mechanical stop "
                "detected before the software range boundary"
            )
        if not max_state["found"]:
            raise RuntimeError(
                f"Servo {servo_id} calibration failed: no maximum mechanical stop "
                "detected before the software range boundary"
            )
        return int(min_state["best"]), int(max_state["best"])

    def move_to_center(min_lim: int, max_lim: int, *, require: bool = False) -> int | None:
        center = (min_lim + max_lim) // 2
        actual: int | None = None
        try:
            if not bus.set_torque(servo_id, True):
                if require:
                    raise RuntimeError(f"Cannot enable torque on servo {servo_id}")
                return None
            time.sleep(0.01)
            if not bus.move_to(servo_id, center, 500):
                message = f"Servo {servo_id}: could not move to center after calibration"
                if require:
                    raise RuntimeError(message)
                logger.warning(message)
                return None
            time.sleep(0.5)
            actual = bus.read_position(servo_id)
            if require and (actual is None or abs(actual - center) > _CAL_CENTER_TOLERANCE):
                raise RuntimeError(
                    f"Servo {servo_id} could not move to the center of its existing range "
                    f"before recalibration (target={center}, actual={actual})"
                )
        finally:
            bus.set_torque(servo_id, False)
        return actual

    calibration_saved = False
    full_range_opened = False
    failure_restore_limits: tuple[int, int] | None = None

    def keep_existing_limits(reason: str) -> tuple[int, int]:
        nonlocal calibration_saved
        logger.warning(f"Servo {servo_id}: {reason}; keeping existing limits")
        if not bus.set_angle_limits(servo_id, original_limits[0], original_limits[1]):
            raise RuntimeError(f"Cannot restore existing calibrated limits for servo {servo_id}")
        restored_limits = _read_angle_limits_with_retry(bus, servo_id)
        if restored_limits != original_limits:
            raise RuntimeError(
                f"Servo {servo_id} restored limits read back as {restored_limits}, "
                f"expected {original_limits}"
            )
        calibration_saved = True
        move_to_center(original_limits[0], original_limits[1])
        return original_limits

    def prefer_detected_failed_limits(min_lim: int, max_lim: int) -> None:
        """Use the measured short range as an uncalibrated safety limit.

        This does not turn a failed calibration into a success. It only avoids
        restoring old limits that already failed the 70 degree plausibility
        check and may now drive into a hard stop.
        """
        nonlocal failure_restore_limits
        if original_limits_are_trusted:
            return
        span = max_lim - min_lim
        if span < _CAL_CENTER_TOLERANCE:
            return
        margin = min(_CAL_MARGIN, span // 4)
        safe_min = max(_CAL_MIN_POSITION, min_lim + margin)
        safe_max = min(_CAL_MAX_POSITION, max_lim - margin)
        if safe_max - safe_min < _CAL_CENTER_TOLERANCE:
            return
        failure_restore_limits = (safe_min, safe_max)

    try:
        bus.set_torque(servo_id, False)
        time.sleep(0.02)
        _assert_calibration_safe(bus, servo_id, "preflight")
        _apply_servo_drive_tuning(bus, servo_id, stage="calibration")

        if force and original_limits_are_trusted:
            move_to_center(original_limits[0], original_limits[1], require=True)
            time.sleep(0.02)
        elif original_limits_are_centerable:
            move_to_center(original_limits[0], original_limits[1])
            time.sleep(0.02)

        if not bus.set_angle_limits(servo_id, _CAL_MIN_POSITION, _CAL_MAX_POSITION):
            raise RuntimeError(f"Cannot open full angle range of servo {servo_id}")
        time.sleep(0.02)
        opened_limits = _read_angle_limits_with_retry(bus, servo_id)
        if opened_limits != (_CAL_MIN_POSITION, _CAL_MAX_POSITION):
            raise RuntimeError(
                f"Servo {servo_id} did not accept temporary full range "
                f"(read back {opened_limits})"
            )
        full_range_opened = True

        current = bus.read_position(servo_id)
        if current is None:
            raise RuntimeError(f"Cannot read position of servo {servo_id}")

        cal_min, cal_max = find_envelope(current)
        logger.info(f"  Servo {servo_id}: min = {cal_min}")
        logger.info(f"  Servo {servo_id}: max = {cal_max}")

        span = cal_max - cal_min
        if span < _CAL_MIN_USABLE_SPAN:
            if force and original_limits_are_trusted:
                return keep_existing_limits(
                    f"detected raw range {cal_min}-{cal_max} spans {span} counts, "
                    f"below {_CAL_MIN_USABLE_DEGREES}° (~{_CAL_MIN_USABLE_SPAN} counts)"
                )
            prefer_detected_failed_limits(cal_min, cal_max)
            raise RuntimeError(
                f"Servo {servo_id} calibration failed: range too small "
                f"({cal_min}-{cal_max}, span={span}). Servo moved less than "
                f"{_CAL_MIN_USABLE_DEGREES}° (~{_CAL_MIN_USABLE_SPAN} raw counts) "
                "while probing; check for "
                "mechanical binding, a horn/linkage mounted against a hard stop, "
                "or a gate that cannot move freely."
            )

        margin = min(_CAL_MARGIN, span // 4)
        safe_min = cal_min + margin
        safe_max = cal_max - margin
        safe_span = safe_max - safe_min
        if force and original_limits_are_trusted:
            min_coverage_slack = _CAL_MARGIN * 3
            shrank_too_much = safe_span < int(original_span * 0.85)
            missed_existing_edge = (
                safe_min > original_limits[0] + min_coverage_slack
                or safe_max < original_limits[1] - min_coverage_slack
            )
            if shrank_too_much or missed_existing_edge:
                return keep_existing_limits(
                    f"detected range {safe_min}-{safe_max} is narrower than existing "
                    f"calibrated range {original_limits[0]}-{original_limits[1]}"
                )
        if safe_span < _CAL_MIN_USABLE_SPAN:
            if force and original_limits_are_trusted:
                return keep_existing_limits(
                    f"detected safe range {safe_min}-{safe_max} spans {safe_span} counts, "
                    f"below {_CAL_MIN_USABLE_DEGREES}° (~{_CAL_MIN_USABLE_SPAN} counts)"
                )
            prefer_detected_failed_limits(cal_min, cal_max)
            raise RuntimeError(
                f"Servo {servo_id} calibration failed: range too small "
                f"({safe_min}-{safe_max}, span={safe_span}). Servo moved less than "
                f"{_CAL_MIN_USABLE_DEGREES}° (~{_CAL_MIN_USABLE_SPAN} safe raw counts) "
                "while probing; check for "
                "mechanical binding, a horn/linkage mounted against a hard stop, "
                "or a gate that cannot move freely."
            )
        if _limits_look_uncalibrated(safe_min, safe_max):
            raise RuntimeError(
                f"Servo {servo_id} calibration failed: detected range "
                f"{safe_min}-{safe_max} still looks like the full software range"
            )

        # Save to EEPROM so we don't need to recalibrate next time.
        if not bus.set_angle_limits(servo_id, safe_min, safe_max):
            raise RuntimeError(f"Cannot save calibrated limits for servo {servo_id}")
        saved_limits = _read_angle_limits_with_retry(bus, servo_id)
        if saved_limits != (safe_min, safe_max):
            raise RuntimeError(
                f"Servo {servo_id} saved limits read back as {saved_limits}, "
                f"expected {(safe_min, safe_max)}"
            )
        calibration_saved = True
        logger.info(f"  Servo {servo_id}: calibrated range {safe_min}-{safe_max} (saved to EEPROM)")

        move_to_center(safe_min, safe_max)

        return safe_min, safe_max
    except Exception as exc:
        restored_failure_limits: tuple[int, int] | None = None
        if not calibration_saved and full_range_opened:
            restore_limits = failure_restore_limits or original_limits
            try:
                bus.set_torque(servo_id, False)
                bus.set_angle_limits(servo_id, restore_limits[0], restore_limits[1])
                if failure_restore_limits is not None:
                    restored_failure_limits = restore_limits
                    logger.warning(
                        f"Servo {servo_id}: calibration failed below "
                        f"{_CAL_MIN_USABLE_DEGREES}°; stored detected safety limits "
                        f"{restore_limits[0]}-{restore_limits[1]} instead of restoring "
                        f"untrusted previous limits {original_limits[0]}-{original_limits[1]}"
                    )
            except Exception as restore_exc:
                logger.warning(
                    f"Servo {servo_id}: failed to restore limits "
                    f"{restore_limits}: {restore_exc}"
                )
        if restored_failure_limits is not None:
            raise RuntimeError(
                f"{exc} Stored detected safety limits "
                f"{restored_failure_limits[0]}-{restored_failure_limits[1]} as an "
                "uncalibrated guard range; servo remains below "
                f"{_CAL_MIN_USABLE_DEGREES}°."
            ) from exc
        raise
    finally:
        bus.set_torque(servo_id, False)


# ---------------------------------------------------------------------------
# WaveshareServoMotor — drop-in replacement for ServoMotor
# ---------------------------------------------------------------------------

class WaveshareServoMotor:
    """A servo motor controlled via the Waveshare SC serial bus.

    Presents the same interface as `hardware.sorter_interface.ServoMotor`
    so it can be used as a drop-in replacement in the distribution system.

    open/close positions are mapped to the EEPROM angle limits:
    - open  = min limit  (gate opens, piece falls through)
    - close = max limit  (gate blocks)
    If `invert` is True these are swapped.
    """

    # Consecutive failed bus operations before `available` flips to False.
    # Hysteresis: single flukes must not toggle layer usability.
    _OFFLINE_THRESHOLD = 3

    def __init__(self, bus: ServoBus, servo_id: int, invert: bool = False):
        self._bus = bus
        self._servo_id = servo_id
        self._invert = invert
        self._name = f"waveshare_servo_{servo_id}"
        self._enabled = False
        self._current_position: int = 0  # raw SC position 0-1023
        self._min_limit: int = 0
        self._max_limit: int = 1023
        self._open_position: int = 0
        self._closed_position: int = 1023
        self._move_started_at: float = 0.0
        self._move_duration: float = 0.0
        self._consecutive_failures = 0

    def initialize(self) -> None:
        """Read stored limits and apply good PID settings."""
        _apply_servo_drive_tuning(self._bus, self._servo_id, stage="runtime initialization")

        limits = self._bus.read_angle_limits(self._servo_id)
        if limits is None:
            raise RuntimeError(f"Cannot communicate with servo {self._servo_id}")

        min_lim, max_lim = limits
        needs_calibration = _limits_look_uncalibrated(min_lim, max_lim)

        if needs_calibration:
            raise RuntimeError(
                f"Servo {self._servo_id}: limits are {min_lim}-{max_lim}; "
                "run Waveshare setup calibration before enabling this layer"
            )
        else:
            logger.info(f"Servo {self._servo_id}: using stored limits {min_lim}-{max_lim}")

        self._min_limit = min_lim
        self._max_limit = max_lim

        if self._invert:
            self._open_position = max_lim
            self._closed_position = min_lim
        else:
            self._open_position = min_lim
            self._closed_position = max_lim

        # Read current position
        pos = self._bus.read_position(self._servo_id)
        if pos is not None:
            self._current_position = pos

    def set_invert(self, invert: bool) -> None:
        self._invert = invert
        if self._invert:
            self._open_position = self._max_limit
            self._closed_position = self._min_limit
        else:
            self._open_position = self._min_limit
            self._closed_position = self._max_limit

    def recalibrate(self) -> tuple[int, int]:
        min_lim, max_lim = calibrate_servo(self._bus, self._servo_id, force=True)
        self._min_limit = min_lim
        self._max_limit = max_lim
        self.set_invert(self._invert)
        pos = self._bus.read_position(self._servo_id)
        if pos is not None:
            self._current_position = pos
        else:
            self._current_position = (min_lim + max_lim) // 2
        return min_lim, max_lim

    # -- ServoMotor-compatible interface ------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = bool(value)
        self._bus.set_torque(self._servo_id, self._enabled)

    def move_to(self, angle: int) -> bool:
        """Move to angle (0-180). Maps linearly to calibrated range."""
        return self._command_move(self._angle_to_position(angle), f"move_to({angle})")

    def move_to_and_release(self, angle: int) -> bool:
        """Move to angle then disable torque."""
        result = self.move_to(angle)
        self._enabled = False  # will release after move
        return result

    @property
    def position(self) -> int:
        pos = self._bus.read_position(self._servo_id)
        self._record_result(pos is not None)
        return pos if pos is not None else self._current_position

    def stop(self):
        self._bus.set_torque(self._servo_id, False)
        self._enabled = False

    @property
    def stopped(self) -> bool:
        # Use time-based estimate since polling is_moving is slow on the bus
        if self._move_started_at == 0:
            return True
        elapsed = time.monotonic() - self._move_started_at
        if elapsed >= self._move_duration + 0.1:
            # Auto-release torque if move_to_and_release was used
            if not self._enabled:
                self._bus.set_torque(self._servo_id, False)
            self._move_started_at = 0
            return True
        return False

    @property
    def available(self) -> bool:
        return self._consecutive_failures < self._OFFLINE_THRESHOLD

    def open(self, open_angle: int | None = None) -> None:
        self._command_move(self._open_position, "open")
        self._enabled = False  # release after move

    def close(self, closed_angle: int | None = None) -> None:
        self._command_move(self._closed_position, "close")
        self._enabled = False  # release after move

    def toggle(self) -> None:
        if self.isOpen():
            self.close()
        else:
            self.open()

    def isOpen(self) -> bool:
        return abs(self._current_position - self._open_position) < abs(self._current_position - self._closed_position)

    def isClosed(self) -> bool:
        return not self.isOpen()

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        pass  # SC servos use time-based moves, speed is implicit

    def set_acceleration(self, acceleration: int) -> None:
        pass  # not applicable for SC servos

    def set_duty_limits(self, min_duty_us: int, max_duty_us: int) -> None:
        pass  # not applicable for SC servos

    def set_name(self, name: str) -> None:
        self._name = name

    def set_preset_angles(self, open_angle: int, closed_angle: int) -> None:
        # For waveshare, open/close are determined by calibration + invert,
        # so we ignore the angle values but accept the call for compatibility.
        pass

    @property
    def angle(self) -> int:
        return self._position_to_angle(self._current_position)

    @property
    def channel(self) -> int:
        return self._servo_id

    def feedback(self) -> Dict[str, Any]:
        position = self.position
        return {
            "available": self.available,
            "channel": self._servo_id,
            "position": position,
            "angle": self._position_to_angle(position),
            "open_position": self._open_position,
            "closed_position": self._closed_position,
            "min_limit": self._min_limit,
            "max_limit": self._max_limit,
            "is_open": abs(position - self._open_position) < abs(position - self._closed_position),
            "invert": self._invert,
        }

    # -- internal -----------------------------------------------------------

    def _command_move(self, position: int, label: str) -> bool:
        if not self._enabled:
            self.enabled = True
        ok = bool(self._bus.move_to(self._servo_id, position, 300))
        self._record_result(ok)
        if ok:
            self._move_duration = 0.3
            self._move_started_at = time.monotonic()
            self._current_position = position
        else:
            logger.warning(
                f"Servo {self._servo_id}: {label} command failed "
                f"(consecutive failures: {self._consecutive_failures})"
            )
            # No move was started, so the `stopped` poll that normally
            # releases torque after a move never will — release it here,
            # best-effort, instead of leaving the coil energized.
            self._bus.set_torque(self._servo_id, False)
        return ok

    def _record_result(self, success: bool) -> None:
        if success:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1

    def _angle_to_position(self, angle: int) -> int:
        """Map 0-180 degrees to calibrated min-max range."""
        angle = max(0, min(180, angle))
        span = self._max_limit - self._min_limit
        return self._min_limit + int(round(angle / 180.0 * span))

    def _position_to_angle(self, position: int) -> int:
        """Map calibrated position back to 0-180 degrees."""
        span = self._max_limit - self._min_limit
        if span == 0:
            return 0
        return int(round((position - self._min_limit) / span * 180.0))
