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
from typing import Any, Dict

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


def _checksum(data: bytes) -> int:
    return (~sum(data)) & 0xFF


class ScServoBus:
    """Low-level half-duplex serial bus for SC servos."""

    def __init__(self, port: str, baudrate: int = 1_000_000, timeout: float = 0.05):
        self._serial = serial.Serial(port, baudrate=baudrate, timeout=timeout)
        self._lock = threading.Lock()

    def close(self):
        self._serial.close()

    # -- packet I/O ---------------------------------------------------------

    def _send(self, servo_id: int, instruction: int, params: bytes = b"") -> bytes | None:
        with self._lock:
            length = len(params) + 2
            pkt = bytes([0xFF, 0xFF, servo_id, length, instruction]) + params
            pkt += bytes([_checksum(pkt[2:])])

            self._serial.reset_input_buffer()
            self._serial.write(pkt)
            self._serial.flush()
            time.sleep(0.0005)

            header = self._serial.read(5)
            if len(header) < 5 or header[0] != 0xFF or header[1] != 0xFF:
                return None
            resp_length = header[3]
            if resp_length < 2:
                return None
            data = self._serial.read(resp_length - 1)
            if len(data) < resp_length - 1:
                return None
            return data  # first byte is error/status, rest is payload

    # -- helpers ------------------------------------------------------------

    def ping(self, servo_id: int) -> bool:
        return self._send(servo_id, _INST_PING) is not None

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
            if self.ping(sid):
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

        return {
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


# ---------------------------------------------------------------------------
# Auto-calibration
# ---------------------------------------------------------------------------

_CAL_STEP_SIZE = 30
_CAL_STEP_TIME_MS = 500
_CAL_SETTLE_MS = 600
_CAL_LOAD_THRESHOLD = 300
_CAL_STALL_CHECKS = 3
_CAL_MARGIN = 5


def calibrate_servo(bus: ScServoBus, servo_id: int) -> tuple[int, int]:
    """Find the physical min/max of a servo by stepping until stall.

    Returns (safe_min, safe_max) with a small safety margin applied.
    Raises RuntimeError if calibration fails.
    """
    logger.info(f"Calibrating servo {servo_id}...")

    # Temporarily open full range
    bus.set_angle_limits(servo_id, 0, 1023)
    time.sleep(0.02)
    bus.set_torque(servo_id, True)
    time.sleep(0.02)

    current = bus.read_position(servo_id)
    if current is None:
        raise RuntimeError(f"Cannot read position of servo {servo_id}")

    def find_limit(start_pos: int, direction: int) -> int:
        """Step in `direction` (-1 for min, +1 for max) until stall."""
        best = start_pos
        target = start_pos
        last_pos = None
        stall_count = 0

        while True:
            next_target = target + direction * _CAL_STEP_SIZE
            next_target = max(0, min(1023, next_target))
            if next_target == target:
                # Hit 0 or 1023 boundary
                return best
            target = next_target

            bus.move_to(servo_id, target, _CAL_STEP_TIME_MS)
            time.sleep(_CAL_SETTLE_MS / 1000.0)

            # Poll for stall
            for _ in range(5):
                time.sleep(0.1)
                pos = bus.read_position(servo_id)
                load = bus.read_load(servo_id)
                if pos is None or load is None:
                    continue

                if (direction < 0 and pos < best) or (direction > 0 and pos > best):
                    best = pos

                near_target = abs(pos - target) < 10
                if near_target:
                    break  # reached target, issue next step

                if last_pos is not None and abs(pos - last_pos) < 2:
                    stall_count += 1
                else:
                    stall_count = 0
                last_pos = pos

                if stall_count >= _CAL_STALL_CHECKS or (abs(load) > _CAL_LOAD_THRESHOLD and stall_count >= 2):
                    logger.info(f"  Servo {servo_id}: limit found at {best} (stall, load={load})")
                    return best
            else:
                last_pos = pos

        return best  # unreachable but keeps linter happy

    cal_min = find_limit(current, -1)
    logger.info(f"  Servo {servo_id}: min = {cal_min}")

    cal_max = find_limit(cal_min, +1)
    logger.info(f"  Servo {servo_id}: max = {cal_max}")

    span = cal_max - cal_min
    if span < 20:
        raise RuntimeError(
            f"Servo {servo_id} calibration failed: range too small ({cal_min}-{cal_max}, span={span})"
        )

    margin = min(_CAL_MARGIN, span // 4)
    safe_min = cal_min + margin
    safe_max = cal_max - margin

    # Save to EEPROM so we don't need to recalibrate next time
    bus.set_angle_limits(servo_id, safe_min, safe_max)
    logger.info(f"  Servo {servo_id}: calibrated range {safe_min}-{safe_max} (saved to EEPROM)")

    # Move to center
    center = (safe_min + safe_max) // 2
    bus.move_to(servo_id, center, 500)
    time.sleep(0.5)
    bus.set_torque(servo_id, False)

    return safe_min, safe_max


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

    def __init__(self, bus: ScServoBus, servo_id: int, invert: bool = False):
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

    def initialize(self) -> None:
        """Read or auto-calibrate limits and apply good PID settings."""
        # Set PID to avoid undershooting (factory default I=0 causes issues)
        self._bus.set_pid(self._servo_id, 32, 32, 20)

        limits = self._bus.read_angle_limits(self._servo_id)
        if limits is None:
            raise RuntimeError(f"Cannot communicate with servo {self._servo_id}")

        min_lim, max_lim = limits
        needs_calibration = (min_lim == 0 and max_lim == 1023) or (max_lim - min_lim < 20)

        if needs_calibration:
            logger.info(f"Servo {self._servo_id}: limits are {min_lim}-{max_lim}, running auto-calibration")
            min_lim, max_lim = calibrate_servo(self._bus, self._servo_id)
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
        min_lim, max_lim = calibrate_servo(self._bus, self._servo_id)
        self._min_limit = min_lim
        self._max_limit = max_lim
        self.set_invert(self._invert)
        pos = self._bus.read_position(self._servo_id)
        if pos is not None:
            self._current_position = pos
        else:
            self._current_position = (min_lim + max_lim) // 2

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
        if not self._enabled:
            self.enabled = True
        position = self._angle_to_position(angle)
        self._move_duration = 0.3
        self._move_started_at = time.monotonic()
        self._current_position = position
        return self._bus.move_to(self._servo_id, position, 300)

    def move_to_and_release(self, angle: int) -> bool:
        """Move to angle then disable torque."""
        result = self.move_to(angle)
        self._enabled = False  # will release after move
        return result

    @property
    def position(self) -> int:
        pos = self._bus.read_position(self._servo_id)
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

    def open(self, open_angle: int | None = None) -> None:
        if not self._enabled:
            self.enabled = True
        self._move_duration = 0.3
        self._move_started_at = time.monotonic()
        self._current_position = self._open_position
        self._bus.move_to(self._servo_id, self._open_position, 300)
        self._enabled = False  # release after move

    def close(self, closed_angle: int | None = None) -> None:
        if not self._enabled:
            self.enabled = True
        self._move_duration = 0.3
        self._move_started_at = time.monotonic()
        self._current_position = self._closed_position
        self._bus.move_to(self._servo_id, self._closed_position, 300)
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
