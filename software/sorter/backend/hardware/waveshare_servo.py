"""Waveshare SC series serial bus servo driver.

Implements the Feetech SC protocol (SC09, SC15, SC40, SC60) over half-duplex
TTL serial at 1 Mbps.  The driver provides both a low-level bus class
(`ScServoBus`) and a high-level `WaveshareServoMotor` that is a drop-in
replacement for the PCA9685-based `ServoMotor` used elsewhere in the sorter.

SC series uses **big-endian** byte order for 16-bit register values.

Auto-calibration
----------------
On first use each servo finds its physical min/max positions by stepping
towards each limit until the servo stalls (load spike + position stops
changing).  The discovered range is stored in the servo's EEPROM so the
procedure only runs once per servo (unless limits are reset to 0-1023).
"""

import logging
import struct
import threading
import time
from typing import Any, Dict, Protocol

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
# Calibration — find the door's end stops without leaving the servo on them
# ---------------------------------------------------------------------------
#
# What the B1 doors taught us (2026-09-02, hardware/waveshare_servo probe):
#   - the mechanics have ~10 counts of stiction: a 3- or 10-count command
#     leaves the horn where it is while the duty climbs to 500, then it jumps.
#     Small probes therefore look like a stop, and "duty at rest" says nothing
#     about being free — the P-controller holds 100-250 duty against friction
#     anywhere in the travel. Probes must be bigger than the stiction band and
#     a stop means NO progress twice in a row, not a high duty reading.
#   - a limit on the pressed stop made every open/close drive the horn into
#     it at full duty (limit 69, resting at 64, 74 °C). The limits therefore
#     keep a margin from the pressed position, and the runtime releases torque
#     after each move (WaveshareServoMotor._release_after_move).
# Procedure: probe outward in 30-count moves until two consecutive probes make
# no progress, take the pressed position as the raw stop, keep a margin of at
# least 10 counts (4 % of the span), verify both ends with full swings (a small
# retreat command does not break the stiction at a stop, a full swing does), save.
# Every EEPROM write is read back. Any failure restores the previous limits and
# releases torque. Nothing calibrates implicitly: initialize() refuses an
# uncalibrated servo instead of moving a door at machine start.

# Door open/close move time. 300 ms tripped the overload protection (status
# 0x20) of the stickier B1 door mid-swing at full duty; at 400-500 ms the same
# door passes. The calibration verifies with the same timing the runtime uses.
DOOR_MOVE_TIME_MS = 500

_CAL_PROBE_STEP = 30  # counts per outward probe (~9°), well above the stiction band
_CAL_PROBE_TIME_MS = 400
_CAL_PROBE_SETTLE_S = 0.3
_CAL_STOP_SHORT = 15  # a stalled probe ends at least this far short of its target
_CAL_MIN_PROGRESS = 10  # counts; a free probe moves ~30, a pressed door creeps < 10
_CAL_STALLED_PROBES = 2  # consecutive no-progress probes that make a stop
_CAL_SWING_TOL = 20  # counts; a full swing must end within this of its target
_CAL_MARGIN_MIN = 15  # counts; absorbs the compression seen while pressing (~5)
_CAL_MARGIN_FRACTION = 0.05
_CAL_SETTLE_MAX_S = 1.5  # keep polling until the position stops creeping
_CAL_MIN_SPAN = 40  # counts (~12°); below this the door is not usable
_CAL_MAX_PROBES = 40  # per direction; 40 × 30 covers the whole 0..1023 range
_CAL_MAX_TEMPERATURE_C = 60
_CAL_TELEMETRY_RETRIES = 3
_CAL_BOUNDARY_SLACK = 8  # a limit within this of 0/1023 = software boundary hit
_CAL_POLL_S = 0.05
_SERVO_RANGE = (0, 1023)

# Patchable in tests so the procedure runs without real delays.
_sleep = time.sleep


class CalibrationError(RuntimeError):
    """Calibration aborted. The previous EEPROM limits were restored and
    torque was released before this is raised."""


def limits_look_uncalibrated(min_lim: int, max_lim: int) -> bool:
    """Factory range, a too-small span, or a limit sitting on the software
    boundary (what a stall search that never found a stop would produce)."""
    if max_lim - min_lim < _CAL_MIN_SPAN:
        return True
    return min_lim <= _CAL_BOUNDARY_SLACK or max_lim >= _SERVO_RANGE[1] - _CAL_BOUNDARY_SLACK


def _clamp(position: int) -> int:
    return max(_SERVO_RANGE[0], min(_SERVO_RANGE[1], position))


def _require(ok: object, what: str, servo_id: int) -> None:
    if not ok:
        raise CalibrationError(f"Servo {servo_id}: {what} was not acknowledged")


def _read_pos_load(bus: ServoBus, servo_id: int) -> tuple[int, int]:
    for attempt in range(_CAL_TELEMETRY_RETRIES):
        if attempt:
            _sleep(_CAL_POLL_S)
        pos = bus.read_position(servo_id)
        load = bus.read_load(servo_id)
        if pos is not None and load is not None:
            return pos, load
    raise CalibrationError(f"Servo {servo_id}: telemetry lost during calibration")


def _check_temperature(bus: ServoBus, servo_id: int, stage: str) -> None:
    reader = getattr(bus, "read_servo_info", None)
    if not callable(reader):
        return
    try:
        info = reader(servo_id)
    except Exception:
        return
    temperature = info.get("temperature") if isinstance(info, dict) else None
    if isinstance(temperature, (int, float)) and temperature >= _CAL_MAX_TEMPERATURE_C:
        raise CalibrationError(
            f"Servo {servo_id}: {temperature} °C during {stage} — let it cool before calibrating"
        )


def _move_and_settle(bus: ServoBus, servo_id: int, target: int, time_ms: int) -> tuple[int, int]:
    """Command a move, then read position/load once the horn has stopped
    creeping (a pressed or sticky door keeps moving well after ``time_ms``)."""
    _require(bus.move_to(servo_id, target, time_ms), f"move to {target}", servo_id)
    _sleep(time_ms / 1000.0 + _CAL_PROBE_SETTLE_S)
    pos, load = _read_pos_load(bus, servo_id)
    deadline = time.monotonic() + _CAL_SETTLE_MAX_S
    while time.monotonic() < deadline:
        _sleep(0.1)
        new_pos, load = _read_pos_load(bus, servo_id)
        if abs(new_pos - pos) <= 2:
            return new_pos, load
        pos = new_pos
    return pos, load


def _write_limits_verified(bus: ServoBus, servo_id: int, lo: int, hi: int) -> None:
    _require(bus.set_angle_limits(servo_id, lo, hi), f"writing limits {lo}-{hi}", servo_id)
    _sleep(0.02)
    back = bus.read_angle_limits(servo_id)
    if back is None or tuple(back) != (lo, hi):
        raise CalibrationError(f"Servo {servo_id}: limits read back as {back}, expected {(lo, hi)}")


def _find_stop(bus: ServoBus, servo_id: int, direction: int) -> int:
    """direction -1 = toward min, +1 = toward max. Returns the pressed stop
    position. Torque stays on; the caller releases it."""
    _require(bus.set_torque(servo_id, True), "torque enable", servo_id)
    _sleep(0.02)
    pos, _ = _read_pos_load(bus, servo_id)
    target = pos
    extreme = pos
    stalled = 0
    short = 0
    for probe in range(_CAL_MAX_PROBES):
        next_target = _clamp(target + direction * _CAL_PROBE_STEP)
        if next_target == target:
            if short >= _CAL_STOP_SHORT:
                # Pressed against something right at the software boundary.
                return extreme
            raise CalibrationError(
                f"Servo {servo_id}: reached the software boundary at {target} without "
                f"finding a stop — is the horn free-spinning?"
            )
        target = next_target
        last_pos = pos
        pos, load = _move_and_settle(bus, servo_id, target, _CAL_PROBE_TIME_MS)
        if (pos - extreme) * direction > 0:
            extreme = pos
        progressed = (pos - last_pos) * direction
        short = (target - pos) * direction
        stalled = stalled + 1 if (progressed < _CAL_MIN_PROGRESS and short >= _CAL_STOP_SHORT) else 0
        if stalled >= _CAL_STALLED_PROBES:
            logger.info(
                f"  Servo {servo_id}: stop at {extreme} going {'down' if direction < 0 else 'up'} "
                f"(load={load})"
            )
            return extreme
        if probe % 10 == 9:
            _check_temperature(bus, servo_id, "probing")
    raise CalibrationError(f"Servo {servo_id}: no stop found within {_CAL_MAX_PROBES} probes")


def _verify_swing(bus: ServoBus, servo_id: int, start: int, target: int) -> None:
    """A full swing, as the runtime does it, must end near the target."""
    _move_and_settle(bus, servo_id, start, DOOR_MOVE_TIME_MS)
    pos, load = _move_and_settle(bus, servo_id, target, DOOR_MOVE_TIME_MS)
    if abs(pos - target) > _CAL_SWING_TOL:
        raise CalibrationError(
            f"Servo {servo_id}: swing to {target} ended at {pos} (load {load}); "
            f"the calibrated range is not usable"
        )


def calibrate_servo(bus: ServoBus, servo_id: int) -> tuple[int, int]:
    """Measure the door's travel and store safe limits in EEPROM.

    Returns (safe_min, safe_max). Raises CalibrationError with the previous
    limits restored and torque released.
    """
    logger.info(f"Calibrating servo {servo_id}...")
    _check_temperature(bus, servo_id, "preflight")
    previous = bus.read_angle_limits(servo_id)
    saved = False
    try:
        _write_limits_verified(bus, servo_id, *_SERVO_RANGE)
        stops: dict[int, int] = {}
        for direction in (-1, +1):
            try:
                stops[direction] = _find_stop(bus, servo_id, direction)
            finally:
                bus.set_torque(servo_id, False)
            _sleep(0.1)
        raw_min, raw_max = stops[-1], stops[+1]
        span = raw_max - raw_min
        logger.info(f"  Servo {servo_id}: stops at {raw_min} and {raw_max} ({span} counts)")
        if span < _CAL_MIN_SPAN:
            raise CalibrationError(
                f"Servo {servo_id}: travel {raw_min}-{raw_max} is only {span} counts "
                f"(minimum {_CAL_MIN_SPAN})"
            )
        margin = max(_CAL_MARGIN_MIN, int(round(span * _CAL_MARGIN_FRACTION)))
        safe_min, safe_max = raw_min + margin, raw_max - margin
        if safe_max - safe_min < _CAL_MIN_SPAN:
            raise CalibrationError(f"Servo {servo_id}: a {margin}-count margin leaves no usable travel")
        _require(bus.set_torque(servo_id, True), "torque enable", servo_id)
        try:
            _verify_swing(bus, servo_id, safe_min, safe_max)
            _verify_swing(bus, servo_id, safe_max, safe_min)
            _write_limits_verified(bus, servo_id, safe_min, safe_max)
            saved = True
            logger.info(
                f"  Servo {servo_id}: calibrated range {safe_min}-{safe_max} "
                f"(margin {margin} from the stops, saved to EEPROM)"
            )
            _move_and_settle(bus, servo_id, (safe_min + safe_max) // 2, 400)
        finally:
            bus.set_torque(servo_id, False)
        return safe_min, safe_max
    except CalibrationError:
        raise
    except Exception as exc:
        raise CalibrationError(f"Servo {servo_id}: calibration failed: {exc}") from exc
    finally:
        if not saved:
            if previous is not None:
                try:
                    bus.set_angle_limits(servo_id, previous[0], previous[1])
                except Exception:
                    logger.warning(f"Servo {servo_id}: could not restore limits {previous}")
            try:
                bus.set_torque(servo_id, False)
            except Exception:
                pass


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
        # Pending post-move torque release (open/close/move_to_and_release).
        self._release_timer: threading.Timer | None = None

    def initialize(self) -> None:
        """Read the calibrated limits and apply good PID settings.

        Never calibrates: that moves a door at machine start, possibly loaded.
        An uncalibrated servo is refused (the layer goes offline with a clear
        message) until the operator calibrates it from the servo setup."""
        # Set PID to avoid undershooting (factory default I=0 causes issues)
        self._bus.set_pid(self._servo_id, 32, 32, 20)

        limits = self._bus.read_angle_limits(self._servo_id)
        if limits is None:
            raise RuntimeError(f"Cannot communicate with servo {self._servo_id}")

        min_lim, max_lim = limits
        if limits_look_uncalibrated(min_lim, max_lim):
            raise RuntimeError(
                f"Servo {self._servo_id} is not calibrated (limits {min_lim}-{max_lim}); "
                f"run calibration from the servo setup before use"
            )
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
        min_lim, max_lim = calibrate_servo(self._bus, self._servo_id)
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
        if self._enabled:
            # An explicit hold must survive a release scheduled by an earlier move.
            self._cancel_release()
        self._bus.set_torque(self._servo_id, self._enabled)

    def move_to(self, angle: int) -> bool:
        """Move to angle (0-180). Maps linearly to calibrated range."""
        return self._command_move(self._angle_to_position(angle), f"move_to({angle})")

    def move_to_and_release(self, angle: int) -> bool:
        """Move to angle then disable torque."""
        result = self.move_to(angle)
        self._release_after_move()
        return result

    def _release_after_move(self) -> None:
        """Drop torque once the move in flight has finished.

        The door mechanics hold the gate on their own, and a servo left
        energized against its end stop draws stall current until it overheats
        (seen at 74 °C on the B1 machine) and trips its protection — which the
        old driver then reported as "unreachable". Nothing on the distribution
        path polls ``stopped``, so the release cannot depend on it.
        """
        self._enabled = False
        self._cancel_release()
        if self._move_started_at == 0:
            return  # no move in flight: the failed command already released
        timer = threading.Timer(self._move_duration + 0.1, self._release_if_pending)
        timer.daemon = True
        self._release_timer = timer
        timer.start()

    def _release_if_pending(self) -> None:
        if self._enabled:
            return
        self._move_started_at = 0.0
        self._release_timer = None
        self._bus.set_torque(self._servo_id, False)

    def _cancel_release(self) -> None:
        timer = self._release_timer
        if timer is not None:
            timer.cancel()
            self._release_timer = None

    @property
    def position(self) -> int:
        pos = self._bus.read_position(self._servo_id)
        self._record_result(pos is not None)
        return pos if pos is not None else self._current_position

    def stop(self):
        self._cancel_release()
        self._move_started_at = 0.0
        self._bus.set_torque(self._servo_id, False)
        self._enabled = False

    @property
    def stopped(self) -> bool:
        # Use time-based estimate since polling is_moving is slow on the bus
        if self._move_started_at == 0:
            return True
        elapsed = time.monotonic() - self._move_started_at
        if elapsed >= self._move_duration + 0.1:
            # The timer normally releases; a poll that gets here first does it
            # instead (and cancels the timer so the coil isn't released twice).
            if not self._enabled:
                self._cancel_release()
                self._bus.set_torque(self._servo_id, False)
            self._move_started_at = 0
            return True
        return False

    @property
    def available(self) -> bool:
        return self._consecutive_failures < self._OFFLINE_THRESHOLD

    def open(self, open_angle: int | None = None) -> None:
        self._command_move(self._open_position, "open")
        self._release_after_move()

    def close(self, closed_angle: int | None = None) -> None:
        self._command_move(self._closed_position, "close")
        self._release_after_move()

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
        ok = bool(self._bus.move_to(self._servo_id, position, DOOR_MOVE_TIME_MS))
        self._record_result(ok)
        if ok:
            self._move_duration = DOOR_MOVE_TIME_MS / 1000.0
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
