import json
import struct
import threading
from dataclasses import dataclass
from typing import Optional
from zlib import crc32

import serial
import serial.tools.list_ports


CMD_INIT = 0x00
CMD_PING = 0x01
CMD_STEPPER_MOVE_STEPS = 0x10
CMD_STEPPER_MOVE_AT_SPEED = 0x11
CMD_STEPPER_SET_SPEED_LIMITS = 0x12
CMD_STEPPER_SET_ACCELERATION = 0x13
CMD_STEPPER_IS_STOPPED = 0x14
CMD_STEPPER_GET_POSITION = 0x15
CMD_STEPPER_SET_POSITION = 0x16
CMD_STEPPER_HOME = 0x17
CMD_STEPPER_DRV_SET_ENABLED = 0x20
CMD_STEPPER_DRV_SET_MICROSTEPS = 0x21
CMD_STEPPER_DRV_SET_CURRENT = 0x22
CMD_SERVO_MOVE_TO = 0x40
CMD_SERVO_SET_SPEED_LIMITS = 0x41
CMD_SERVO_SET_ACCELERATION = 0x42
CMD_SERVO_GET_POSITION = 0x43
CMD_SERVO_IS_STOPPED = 0x44
CMD_SERVO_STOP = 0x45
CMD_SERVO_SET_ENABLED = 0x46
CMD_SERVO_SET_DUTY_LIMITS = 0x47
CMD_SERVO_MOVE_TO_AND_RELEASE = 0x48

PICO_VID = 0x2E8A
PICO_PID = 0x000A
DEFAULT_BAUDRATE = 576000


def cobs_encode(message: bytes) -> bytearray:
    outbuf = bytearray(b"\x01")
    counter_idx = 0
    for mb in message:
        if mb == 0:
            counter_idx = len(outbuf)
        outbuf.append(mb)
        outbuf[counter_idx] += 1
    return outbuf


def cobs_decode(buff: bytes) -> bytearray:
    msgbuf = bytearray()
    data = bytearray(buff)
    s = data.pop(0)
    while data:
        c = data.pop(0)
        if c == 0:
            raise ValueError("COBS packet contains zeroes")
        if s == 1:
            msgbuf.append(0)
            s = c
        else:
            msgbuf.append(c)
            s -= 1
    if s > 1:
        raise ValueError("COBS corrupted count")
    return msgbuf


@dataclass
class Response:
    address: int
    command: int
    channel: int
    payload: bytes


class BusError(Exception):
    pass


def enumerate_pico_ports() -> list[str]:
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports if p.vid == PICO_VID and p.pid == PICO_PID]


class SorterBus:
    def __init__(self, port: str, baudrate: int = DEFAULT_BAUDRATE, timeout: float = 0.2):
        self._serial = serial.Serial(port, baudrate=baudrate, timeout=timeout)
        self._lock = threading.Lock()
        self.port = port

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:
            pass

    def _send(self, address: int, command: int, channel: int, payload: bytes) -> Response:
        header = struct.pack("<BBBB", address, command, channel, len(payload))
        frame = header + payload
        frame += struct.pack("<I", crc32(frame))
        wire = bytes(cobs_encode(frame)) + b"\x00"

        with self._lock:
            self._serial.reset_input_buffer()
            self._serial.write(wire)
            resp = bytearray(self._serial.read_until(b"\x00", 254))

        if not resp:
            raise BusError("Timeout waiting for response")
        if resp[-1] != 0:
            raise BusError("Partial response (missing terminator)")

        decoded = cobs_decode(bytes(resp[:-1]))
        if crc32(decoded[:-4]) != struct.unpack("<I", decoded[-4:])[0]:
            raise BusError("CRC mismatch")

        addr, cmd, ch, plen = struct.unpack("<BBBB", decoded[:4])
        payload_bytes = bytes(decoded[4 : 4 + plen])
        if cmd & 0x80:
            raise BusError(f"Device error resp: cmd=0x{cmd:02x} payload={payload_bytes!r}")
        return Response(addr, cmd, ch, payload_bytes)

    def scan(self, max_address: int = 15) -> list[int]:
        found: list[int] = []
        for addr in range(max_address + 1):
            try:
                self._send(addr, CMD_PING, 0, b"")
                found.append(addr)
            except Exception:
                pass
        return found

    def init(self, address: int) -> dict:
        res = self._send(address, CMD_INIT, 0, b"")
        return json.loads(res.payload.decode("utf-8"))


class Servo:
    def __init__(self, bus: SorterBus, address: int, channel: int):
        self._bus = bus
        self._address = address
        self._channel = channel
        self._enabled = False
        self._last_angle: Optional[float] = None

    @property
    def channel(self) -> int:
        return self._channel

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def last_angle(self) -> Optional[float]:
        return self._last_angle

    def set_enabled(self, value: bool) -> None:
        self._bus._send(self._address, CMD_SERVO_SET_ENABLED, self._channel, struct.pack("<?", value))
        self._enabled = value

    def move_to(self, angle: float) -> bool:
        if not 0 <= angle <= 180:
            raise ValueError(f"angle out of range: {angle}")
        if not self._enabled:
            self.set_enabled(True)
        payload = struct.pack("<H", int(round(angle * 10)))
        res = self._bus._send(self._address, CMD_SERVO_MOVE_TO, self._channel, payload)
        self._last_angle = angle
        return bool(res.payload[0]) if res.payload else False

    def move_to_and_release(self, angle: float) -> bool:
        if not 0 <= angle <= 180:
            raise ValueError(f"angle out of range: {angle}")
        if not self._enabled:
            self.set_enabled(True)
        payload = struct.pack("<H", int(round(angle * 10)))
        res = self._bus._send(self._address, CMD_SERVO_MOVE_TO_AND_RELEASE, self._channel, payload)
        self._last_angle = angle
        self._enabled = False
        return bool(res.payload[0]) if res.payload else False

    def stop(self) -> None:
        self._bus._send(self._address, CMD_SERVO_STOP, self._channel, b"")

    def get_position_deg(self) -> float:
        res = self._bus._send(self._address, CMD_SERVO_GET_POSITION, self._channel, b"")
        tenths = struct.unpack("<H", res.payload)[0]
        return tenths / 10.0

    def set_speed_limits(self, min_tenths_per_s: int, max_tenths_per_s: int) -> None:
        payload = struct.pack("<HH", min_tenths_per_s, max_tenths_per_s)
        self._bus._send(self._address, CMD_SERVO_SET_SPEED_LIMITS, self._channel, payload)

    def set_acceleration(self, tenths_per_s2: int) -> None:
        payload = struct.pack("<H", tenths_per_s2)
        self._bus._send(self._address, CMD_SERVO_SET_ACCELERATION, self._channel, payload)

    def set_duty_limits_us(self, min_us: int, max_us: int) -> None:
        if not (0 <= min_us < max_us <= 20000):
            raise ValueError("duty limits must satisfy 0 <= min < max <= 20000 us")
        min_counts = int((min_us / 20000.0) * 4095)
        max_counts = int((max_us / 20000.0) * 4095)
        payload = struct.pack("<HH", min_counts, max_counts)
        self._bus._send(self._address, CMD_SERVO_SET_DUTY_LIMITS, self._channel, payload)


class Stepper:
    def __init__(self, bus: SorterBus, address: int, channel: int):
        self._bus = bus
        self._address = address
        self._channel = channel
        self._enabled = False

    @property
    def channel(self) -> int:
        return self._channel

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._bus._send(self._address, CMD_STEPPER_DRV_SET_ENABLED, self._channel, struct.pack("<?", value))
        self._enabled = value

    def move_steps(self, steps: int) -> bool:
        payload = struct.pack("<i", int(steps))
        res = self._bus._send(self._address, CMD_STEPPER_MOVE_STEPS, self._channel, payload)
        return bool(res.payload[0]) if res.payload else False

    def move_at_speed(self, speed: int) -> bool:
        payload = struct.pack("<i", int(speed))
        res = self._bus._send(self._address, CMD_STEPPER_MOVE_AT_SPEED, self._channel, payload)
        return bool(res.payload[0]) if res.payload else False

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        payload = struct.pack("<II", int(min_speed), int(max_speed))
        self._bus._send(self._address, CMD_STEPPER_SET_SPEED_LIMITS, self._channel, payload)

    def set_acceleration(self, acceleration: int) -> None:
        payload = struct.pack("<I", int(acceleration))
        self._bus._send(self._address, CMD_STEPPER_SET_ACCELERATION, self._channel, payload)

    def is_stopped(self) -> bool:
        res = self._bus._send(self._address, CMD_STEPPER_IS_STOPPED, self._channel, b"")
        return bool(res.payload[0])

    def get_position(self) -> int:
        res = self._bus._send(self._address, CMD_STEPPER_GET_POSITION, self._channel, b"")
        return struct.unpack("<i", res.payload)[0]

    def set_position(self, position: int) -> None:
        payload = struct.pack("<i", int(position))
        self._bus._send(self._address, CMD_STEPPER_SET_POSITION, self._channel, payload)

    def set_microsteps(self, microsteps: int) -> None:
        if microsteps not in (1, 2, 4, 8, 16, 32, 64, 128, 256):
            raise ValueError(f"Invalid microsteps: {microsteps}")
        payload = struct.pack("<H", int(microsteps))
        self._bus._send(self._address, CMD_STEPPER_DRV_SET_MICROSTEPS, self._channel, payload)

    def set_current(self, irun: int, ihold: int, ihold_delay: int) -> None:
        payload = struct.pack("<BBB", int(irun), int(ihold), int(ihold_delay))
        self._bus._send(self._address, CMD_STEPPER_DRV_SET_CURRENT, self._channel, payload)
