"""The board's firmware, pretending: the command tables of
`sorter_interface_firmware.cpp` for a v1.5 board in the distribution role, with
the same codes (table in the high nibble, entry in the low), payload lengths,
channel checks, replies and error texts.

It answers from the world (`world.py`): steppers, drivers, the hall input, the
outputs and the board's servo line, which it watches with the Python port of
the board's guard (`hardware/feetech/guard.py`), ticked after every millisecond
of the world as the firmware ticks it between commands.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Callable

from hardware.feetech import registers
from hardware.feetech.adapter_link import instruction_packet, parse_reply
from hardware.feetech.guard import INST_PING, INST_READ, INST_WRITE, MAX_DATA, ServoGuard
from hardware.feetech.link import (
    GarbledReply,
    GuardFull,
    GuardMove,
    GuardProbe,
    LineStuck,
    NoReply,
    ServoLinkError,
)

from .framing import MAX_PAYLOAD_SIZE, Message
from .servos import ServoBus
from .steppers import Tmc2209
from .world import DIGITAL_INPUT_COUNT, DIGITAL_OUTPUT_COUNT, STEPPER_NAMES, World

HW_ID = "basically_v1_5"
DEVICE_NAME = "DISTRIBUTION MB"
FIRMWARE_VARIANT = "distribution-v1-5"
FIRMWARE_VERSION = "firmware/v0.8.1-sim"

STEPPER_STEP_PINS = (9, 10, 12, 14, 1)
STEPPER_DIR_PINS = (8, 21, 11, 13, 0)
STEPPER_NEN_PINS = (15, 15, 15, 15, 15)
STEPPER_DIAG_PINS = (26, 22, 20, 18, 6)
TMC_UART_BUS_INDEX = (0, 0, 0, 0, 1)
TMC_UART_BUS_TX_PINS = (16, 4)
TMC_UART_BUS_RX_PINS = (17, 5)
TMC_UART0_SENDDELAY = 2
DIGITAL_INPUT_PINS = (3,)
DIGITAL_OUTPUT_PINS = (27, 28)
SERVO_BUS_PIN = 2
SERVO_COUNT = 0  # no PWM servos on v1.5

# TMC2209 bits the firmware's driver class uses (TMC2209.h).
GCONF_EN_SPREADCYCLE = 1 << 2
GCONF_PD_DISABLE = 1 << 6
GCONF_MSTEP_REG_SELECT = 1 << 7
GCONF_MULTISTEP_FILT = 1 << 8
MICROSTEP_CODES = {256: 0, 128: 1, 64: 2, 32: 3, 16: 4, 8: 5, 4: 6, 2: 7, 1: 8}


class Driver:
    """The firmware's TMC2209 class: shadow copies of GCONF and CHOPCONF, so its
    writes never read the chip back."""

    def __init__(self, chip: Tmc2209):
        self.chip = chip
        self.gconf = 0
        self.chopconf = 0

    def initialize(self) -> None:
        self.gconf = GCONF_PD_DISABLE | GCONF_MSTEP_REG_SELECT | GCONF_MULTISTEP_FILT
        self.chip.write(Tmc2209.GCONF, self.gconf)
        # toff 3, hstrt 4, hend 1, tbl 2, 1/16 microsteps, intpol
        self.chopconf = 3 | (4 << 4) | (1 << 7) | (2 << 15) | (MICROSTEP_CODES[16] << 24) | (1 << 28)
        self.chip.write(Tmc2209.CHOPCONF, self.chopconf)

    def set_current(self, run: int, hold: int, delay: int) -> None:
        self.chip.write(Tmc2209.IHOLD_IRUN, ((delay & 0x0F) << 16) | ((run & 0x1F) << 8) | (hold & 0x1F))

    def set_microsteps(self, code: int) -> None:
        self.chopconf = (self.chopconf & ~(0xF << 24)) | (code << 24)
        self.chip.write(Tmc2209.CHOPCONF, self.chopconf)

    def enable_stealthchop(self, enable: bool) -> None:
        if enable:
            self.gconf &= ~GCONF_EN_SPREADCYCLE
        else:
            self.gconf |= GCONF_EN_SPREADCYCLE
        self.chip.write(Tmc2209.GCONF, self.gconf)

    def enable_driver(self, enable: bool) -> None:
        self.chopconf = (self.chopconf & ~0xF) | (3 if enable else 0)
        self.chip.write(Tmc2209.CHOPCONF, self.chopconf)


class BoardServoWire:
    """The board's servo line as the guard and the SERVO_BUS commands use it
    (ServoBus::transact): a packet out, and the reply read as the firmware reads it."""

    def __init__(self, bus: ServoBus):
        self.bus = bus

    def transact(self, servo_id: int, instruction: int, params: bytes, data_len: int) -> tuple[int, bytes]:
        if len(params) > 1 + MAX_DATA:
            raise NoReply(f"No reply from servo {servo_id}")  # nothing was sent
        if self.bus.stuck:
            raise LineStuck(f"Servo bus line is stuck (servo {servo_id})")
        reply = self.bus.exchange(instruction_packet(servo_id, instruction, params))
        if servo_id == registers.BROADCAST_ID and instruction == INST_WRITE:
            return 0, b""
        return parse_reply(reply, servo_id, data_len)


class Refusal(Exception):
    """An error reply: the command's code with its 0x80 bit, and these words."""


@dataclass(frozen=True)
class Entry:
    name: str
    payload_length: int  # 255 for any
    channel_ok: Callable[[int], bool] | None
    handler: Callable[[Message], bytes | None]


class Firmware:
    def __init__(self, world: World, *, address: int = 0, version: str = FIRMWARE_VERSION):
        self.world = world
        self.address = address
        self.version = version
        self.device_name = DEVICE_NAME
        self.answering = True  # False: the board hears nothing and says nothing
        self.drivers = [Driver(chip) for chip in world.drivers]
        self.drv_current_on = [True] * len(STEPPER_NAMES)
        self.output_pwm_active = [False] * DIGITAL_OUTPUT_COUNT
        self.diag_pins = list(STEPPER_DIAG_PINS)
        self.wire = BoardServoWire(world.board_bus)
        self.guard = ServoGuard(self.wire)
        self.tables = self._tables()
        with world.lock:
            self.initialize_hardware()
        world.on_tick(self.guard.tick)

    # -- dispatch (message.cpp) -----------------------------------------------

    def handle(self, message: Message) -> Message | None:
        """The reply to one message, or None where the board says nothing."""
        if not self.answering or message.address != self.address:
            return None
        table = self.tables.get((message.command & 0x70) >> 4, {})
        entry = table.get(message.command & 0x0F)
        if entry is None:
            return self._refuse(message, f"Invalid command {message.command}")
        if entry.payload_length != 255 and len(message.payload) != entry.payload_length:
            return self._refuse(
                message,
                f"{entry.name}: Invalid payload length {len(message.payload)}, expected {entry.payload_length}",
            )
        if entry.channel_ok is not None and not entry.channel_ok(message.channel):
            return self._refuse(message, f"{entry.name}: Invalid channel {message.channel}")
        with self.world.lock:
            try:
                payload = entry.handler(message)
            except Refusal as refusal:
                return self._refuse(message, str(refusal))
        if payload is None:
            return None
        return Message(message.address, message.command, message.channel, payload[:MAX_PAYLOAD_SIZE])

    @staticmethod
    def _refuse(message: Message, words: str) -> Message:
        text = words.encode()[: MAX_PAYLOAD_SIZE - 1]  # snprintf keeps room for its terminator
        return Message(message.address, message.command | 0x80, message.channel, text)

    def _tables(self) -> dict[int, dict[int, Entry]]:
        stepper = lambda ch: ch < len(STEPPER_NAMES)  # noqa: E731
        digital_in = lambda ch: ch < DIGITAL_INPUT_COUNT  # noqa: E731
        digital_out = lambda ch: ch < DIGITAL_OUTPUT_COUNT  # noqa: E731
        servo = lambda ch: ch < SERVO_COUNT  # noqa: E731
        bus_id = lambda ch: ch <= registers.BROADCAST_ID  # noqa: E731
        bus_one_id = lambda ch: ch < registers.BROADCAST_ID  # noqa: E731
        never = self._unreachable
        return {
            0: {
                0: Entry("INIT", 0, None, self.init),
                1: Entry("PING", 255, None, lambda m: m.payload),
                2: Entry("REBOOT_BOOTLOADER", 0, None, lambda m: None),
                3: Entry("GET_OBSERVABILITY", 0, None, lambda m: self.observability().encode()),
                4: Entry("GET_VERSION", 0, None, lambda m: self.version_json().encode()),
            },
            1: {
                0: Entry("MOVE_STEPS", 4, stepper, self.stepper_move_steps),
                1: Entry("MOVE_AT_SPEED", 4, stepper, self.stepper_move_at_speed),
                2: Entry("SET_SPEED_LIMITS", 8, stepper, self.stepper_set_speed_limits),
                3: Entry("SET_ACCELERATION", 4, stepper, self.stepper_set_acceleration),
                4: Entry("IS_STOPPED", 0, stepper, lambda m: bytes([self._stepper(m).is_stopped()])),
                5: Entry("GET_POSITION", 0, stepper, lambda m: struct.pack("<i", self._stepper(m).position)),
                6: Entry("SET_POSITION", 4, stepper, self.stepper_set_position),
                7: Entry("HOME", 6, stepper, self.stepper_home),
                8: Entry("JITTER", 16, stepper, self.stepper_jitter),
                9: Entry("IS_JITTERING", 0, stepper, lambda m: bytes([self._stepper(m).jitter_active])),
                10: Entry("ENABLE_STALL_DETECTION", 1, stepper, self.stepper_enable_stall_detection),
                11: Entry("GET_STALL_STATUS", 0, stepper, self.stepper_get_stall_status),
                12: Entry("CLEAR_STALL", 0, stepper, self.stepper_clear_stall),
                13: Entry("SET_DIAG_PIN", 1, stepper, self.stepper_set_diag_pin),
            },
            2: {
                0: Entry("SET_ENABLED", 1, stepper, self.drv_set_enabled),
                1: Entry("SET_MICROSTEPS", 2, stepper, self.drv_set_microsteps),
                2: Entry("SET_CURRENT", 3, stepper, self.drv_set_current),
                8: Entry("READ_REGISTER", 1, stepper, self.drv_read_register),
                9: Entry("WRITE_REGISTER", 5, stepper, self.drv_write_register),
            },
            3: {
                0: Entry("READ", 0, digital_in, self.digital_read),
                1: Entry("WRITE", 1, digital_out, self.digital_write),
                2: Entry("WRITE_PWM", 2, digital_out, self.digital_write_pwm),
            },
            # PWM servos: the table is there, and no channel is valid (SERVO_COUNT 0).
            4: {
                0: Entry("MOVE_TO", 2, servo, never),
                1: Entry("SET_SPEED_LIMITS", 4, servo, never),
                2: Entry("SET_ACCELERATION", 2, servo, never),
                3: Entry("GET_POSITION", 0, servo, never),
                4: Entry("IS_STOPPED", 0, servo, never),
                5: Entry("STOP", 0, servo, never),
                6: Entry("SET_ENABLED", 1, servo, never),
                7: Entry("SET_DUTY_LIMITS", 4, servo, never),
                8: Entry("MOVE_TO_AND_RELEASE", 255, servo, never),
            },
            5: {
                0: Entry("PING", 0, bus_id, self.servo_bus_ping),
                1: Entry("READ", 2, bus_id, self.servo_bus_read),
                2: Entry("WRITE", 255, bus_id, self.servo_bus_write),
                3: Entry("MOVE", 18, bus_one_id, self.servo_bus_move),
                4: Entry("STATE", 0, bus_one_id, self.servo_bus_state),
                5: Entry("PROBE", 12, bus_one_id, self.servo_bus_probe),
                6: Entry("STOP", 1, bus_id, self.servo_bus_stop),
            },
        }

    @staticmethod
    def _unreachable(message: Message) -> bytes:
        raise Refusal(f"Invalid channel {message.channel}")

    # -- base -----------------------------------------------------------------

    def initialize_hardware(self) -> None:
        """initialize_hardware(): what INIT and a power-up do. A stepper that is
        moving keeps moving, as on the board."""
        for index, chip in enumerate(self.world.drivers):
            if TMC_UART_BUS_INDEX[index] == 0:
                chip.write(Tmc2209.SLAVECONF, TMC_UART0_SENDDELAY << 8)
        for index, (motion, driver) in enumerate(zip(self.world.steppers, self.drivers)):
            motion.set_acceleration(20_000)
            motion.set_speed_limits(16, 4_000)
            driver.initialize()
            driver.enable_driver(True)
            self.drv_current_on[index] = True
            driver.set_current(0, 0, 0)
            driver.set_microsteps(MICROSTEP_CODES[8])
            driver.enable_stealthchop(True)
            motion.hw_enabled = False
            self.diag_pins[index] = STEPPER_DIAG_PINS[index]
            motion.stall_pin = self.diag_pins[index]
            motion.enable_stall_detection(False)
        for index, output in enumerate(self.world.outputs):
            output.value = False
            output.duty = None
            self.output_pwm_active[index] = False

    def init(self, message: Message) -> bytes:
        self.initialize_hardware()
        return self.configuration().encode()

    def configuration(self) -> str:
        """The detect JSON, the richest form that fits (dump_configuration)."""
        names = json.dumps(list(STEPPER_NAMES), separators=(",", ":"))
        tail = (
            f'"digital_input_count":{DIGITAL_INPUT_COUNT},"digital_output_count":{DIGITAL_OUTPUT_COUNT},'
            f'"servo_count":{SERVO_COUNT}}}'
        )
        for text in (
            f'{{"device_name":"{self.device_name}","stepper_count":{len(STEPPER_NAMES)},"stepper_names":{names},{tail}',
            f'{{"device_name":"{self.device_name}","hw":"{HW_ID}","stepper_count":{len(STEPPER_NAMES)},'
            f'"stepper_names":{names},{tail}',
            f'{{"device_name":"{self.device_name}","hw":"{HW_ID}","stepper_count":{len(STEPPER_NAMES)},{tail}',
        ):
            if len(text) < MAX_PAYLOAD_SIZE:
                return text
        return "{}"

    def observability(self) -> str:
        diag = json.dumps(self.diag_pins, separators=(",", ":"))
        leds = json.dumps(list(DIGITAL_OUTPUT_PINS), separators=(",", ":"))
        return f'{{"hw":"{HW_ID}","diag_pins":{diag},"led_gpios":{leds},"servo_bus":true,"servo_guard":true}}'

    def version_json(self) -> str:
        return json.dumps(
            {
                "firmware_version": self.version,
                "variant": FIRMWARE_VARIANT,
                "commit": "simulated",
                "build_time_utc": "simulated",
            },
            separators=(",", ":"),
        )

    # -- steppers -------------------------------------------------------------

    def _stepper(self, message: Message):
        return self.world.steppers[message.channel]

    def _ensure_enabled(self, channel: int) -> None:
        self.world.steppers[channel].hw_enabled = True
        if not self.drv_current_on[channel]:
            self.drivers[channel].enable_driver(True)
            self.drv_current_on[channel] = True

    def stepper_move_steps(self, message: Message) -> bytes:
        (distance,) = struct.unpack("<i", message.payload)
        self._ensure_enabled(message.channel)
        return bytes([self._stepper(message).move_steps(distance)])

    def stepper_move_at_speed(self, message: Message) -> bytes:
        (speed,) = struct.unpack("<i", message.payload)
        self._ensure_enabled(message.channel)
        return bytes([self._stepper(message).move_at_speed(speed)])

    def stepper_set_speed_limits(self, message: Message) -> bytes:
        low, high = struct.unpack("<II", message.payload)
        self._stepper(message).set_speed_limits(low, high)
        return b""

    def stepper_set_acceleration(self, message: Message) -> bytes:
        (acceleration,) = struct.unpack("<I", message.payload)
        self._stepper(message).set_acceleration(acceleration)
        return b""

    def stepper_set_position(self, message: Message) -> bytes:
        (position,) = struct.unpack("<i", message.payload)
        self._stepper(message).position = position
        return b""

    def stepper_home(self, message: Message) -> bytes:
        (speed,) = struct.unpack("<i", message.payload[:4])
        channel, polarity = message.payload[4], message.payload[5] != 0
        if channel >= DIGITAL_INPUT_COUNT:
            raise Refusal(f"Invalid home pin channel {channel}")
        self._ensure_enabled(message.channel)
        self._stepper(message).home(speed, channel, polarity)
        return b""

    def stepper_jitter(self, message: Message) -> bytes:
        amplitude, cycles, speed, accel = struct.unpack("<iiii", message.payload)
        self._ensure_enabled(message.channel)
        return bytes([self._stepper(message).jitter(amplitude, cycles, speed, accel)])

    def stepper_enable_stall_detection(self, message: Message) -> bytes:
        enable = message.payload[0] != 0
        if enable and self.diag_pins[message.channel] < 0:
            raise Refusal(f"No DIAG pin for channel {message.channel}")
        self._stepper(message).enable_stall_detection(enable)
        return b""

    def stepper_get_stall_status(self, message: Message) -> bytes:
        mask = 0
        for index, motion in enumerate(self.world.steppers):
            if motion.stalled:
                mask |= 1 << index
        return bytes([mask])

    def stepper_clear_stall(self, message: Message) -> bytes:
        self._stepper(message).stalled = False
        return b""

    def _gpio_in_use(self, pin: int) -> bool:
        pins = set(STEPPER_STEP_PINS) | set(STEPPER_DIR_PINS) | set(STEPPER_NEN_PINS)
        pins |= set(TMC_UART_BUS_TX_PINS) | set(TMC_UART_BUS_RX_PINS)
        pins |= set(DIGITAL_INPUT_PINS) | set(DIGITAL_OUTPUT_PINS) | {SERVO_BUS_PIN}
        return pin in pins

    def stepper_set_diag_pin(self, message: Message) -> bytes:
        pin = struct.unpack("<b", message.payload)[0]
        if pin < -1 or pin > 29 or (pin >= 0 and self._gpio_in_use(pin)):
            raise Refusal(f"GPIO {pin} is not free for a DIAG wire")
        motion = self._stepper(message)
        motion.enable_stall_detection(False)
        self.diag_pins[message.channel] = pin
        motion.stall_pin = pin
        return b""

    # -- stepper drivers ------------------------------------------------------

    def drv_set_enabled(self, message: Message) -> bytes:
        if message.payload[0] != 0:
            self._ensure_enabled(message.channel)
        else:
            self.drivers[message.channel].enable_driver(False)
            self.drv_current_on[message.channel] = False
        return b""

    def drv_set_microsteps(self, message: Message) -> bytes:
        (microsteps,) = struct.unpack("<H", message.payload)
        if microsteps not in MICROSTEP_CODES:
            raise Refusal(f"Invalid microstep value {microsteps}")
        self.drivers[message.channel].set_microsteps(MICROSTEP_CODES[microsteps])
        return b""

    def drv_set_current(self, message: Message) -> bytes:
        run, hold, delay = message.payload
        self.drivers[message.channel].set_current(run, hold, delay)
        return b""

    def drv_read_register(self, message: Message) -> bytes:
        register = message.payload[0]
        value = self.world.drivers[message.channel].read(register, self.world.steppers[message.channel])
        if value is None:
            raise Refusal(f"Failed to read register {register}")
        return struct.pack("<I", value)

    def drv_write_register(self, message: Message) -> bytes:
        register, value = struct.unpack("<BI", message.payload)
        self.world.drivers[message.channel].write(register, value)
        return b""

    # -- digital IO -----------------------------------------------------------

    def digital_read(self, message: Message) -> bytes:
        return bytes([self.world.read_input(message.channel)])

    def digital_write(self, message: Message) -> bytes:
        output = self.world.outputs[message.channel]
        output.value = message.payload[0] != 0
        output.duty = None
        self.output_pwm_active[message.channel] = False
        return b""

    def digital_write_pwm(self, message: Message) -> bytes:
        (duty,) = struct.unpack("<H", message.payload)
        output = self.world.outputs[message.channel]
        output.duty = duty
        output.value = duty > 0
        self.output_pwm_active[message.channel] = True
        return b""

    # -- the servo bus --------------------------------------------------------

    @staticmethod
    def _bus_failed(message: Message, error: ServoLinkError) -> Refusal:
        """servo_bus_failed(): words a host tells apart by how they begin."""
        servo_id = message.channel
        if isinstance(error, GarbledReply):
            return Refusal(f"Garbled reply from servo {servo_id}")
        if isinstance(error, LineStuck):
            return Refusal(f"Servo bus line is stuck (servo {servo_id})")
        if isinstance(error, GuardFull):
            return Refusal(f"Servo guard is full (servo {servo_id})")
        return Refusal(f"No reply from servo {servo_id}")

    def _transact(self, message: Message, instruction: int, params: bytes, data_len: int) -> tuple[int, bytes]:
        try:
            return self.wire.transact(message.channel, instruction, params, data_len)
        except ServoLinkError as error:
            raise self._bus_failed(message, error) from None

    def servo_bus_ping(self, message: Message) -> bytes:
        status, _ = self._transact(message, INST_PING, b"", 0)
        return bytes([status])

    def servo_bus_read(self, message: Message) -> bytes:
        count = message.payload[1]
        if count < 1 or count > MAX_DATA:
            raise Refusal(f"READ: Invalid count {count}, expected 1 to {MAX_DATA}")
        status, data = self._transact(message, INST_READ, message.payload, count)
        return bytes([status]) + data

    def servo_bus_write(self, message: Message) -> bytes:
        if len(message.payload) < 2 or len(message.payload) > 1 + MAX_DATA:
            raise Refusal(
                f"WRITE: Invalid payload length {len(message.payload)}, expected 2 to {1 + MAX_DATA}"
            )
        # A servo the host writes to itself is no longer the guard's to judge.
        self.guard.forget(message.channel)
        status, _ = self._transact(message, INST_WRITE, message.payload, 0)
        return bytes([status])

    def _guarded(self, message: Message, action: Callable[[], None]) -> bytes:
        try:
            action()
        except ServoLinkError as error:
            raise self._bus_failed(message, error) from None
        return b""

    def servo_bus_move(self, message: Message) -> bytes:
        move = GuardMove.unpack(message.payload)
        return self._guarded(message, lambda: self.guard.move(message.channel, move, self.world.now_us))

    def servo_bus_probe(self, message: Message) -> bytes:
        probe = GuardProbe.unpack(message.payload)
        return self._guarded(message, lambda: self.guard.probe(message.channel, probe, self.world.now_us))

    def servo_bus_state(self, message: Message) -> bytes:
        return self.guard.report(message.channel, self.world.now_us).pack()

    def servo_bus_stop(self, message: Message) -> bytes:
        release = message.payload[0] != 0
        return self._guarded(message, lambda: self.guard.stop(message.channel, release, self.world.now_us))
