"""Pretend Feetech serial bus servos, and the line they share.

A servo moves like the pretend servo in the firmware's guard test: its position
chases its goal with an effort proportional to the error, its load is that
effort, and hard stops hold it. Its registers are laid out as the SC series
(big-endian words) or the STS series (little-endian), with what the host reads:
model, ID, angle limits, torque, goal, the 15-byte present block and the EEPROM
lock.

The EEPROM lock: the saved registers (below 40) take a write at once, locked or
not, but only one written while the lock was open (0) survives a power cut. A
servo comes up locked.

`ServoBus` is the line: every servo hears every packet; the ones whose ID it
names answer. Two answering at once garble each other, as on a real open-drain
line: their bytes are ANDed, the second a byte behind the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hardware.feetech import registers
from hardware.feetech.adapter_link import checksum, status_packet
from hardware.feetech.guard import INST_PING, INST_READ, INST_WRITE

EEPROM_END = 40  # registers below this are saved
GOAL_TIME = 44
GOAL_SPEED = 46
SC_LOCK = registers.SC.lock_register
STS_LOCK = registers.STS.lock_register

# What each model reads as at MODEL, and its speed (counts a second at full effort).
MODELS: dict[str, tuple[registers.Series, tuple[int, int], float]] = {
    "SC15": (registers.SC, (0, 15), 600.0),
    "SC09": (registers.SC, (0, 9), 700.0),
    "STS3215": (registers.STS, (0x09, 0x03), 3000.0),
}


@dataclass
class Block:
    """Something in a servo's way, at `position`, on one side of where it was."""

    position: float
    above: bool


@dataclass
class PretendServo:
    servo_id: int
    model: str = "SC15"
    position: float = 500.0
    lower: float = 0.0  # its hard stops: the ends of the door's travel
    upper: float = 1023.0
    blocks: list[Block] = field(default_factory=list)
    plugged: bool = True
    speed: float = 0.0  # counts a second at full effort; 0 for the model's own
    model_bytes: tuple[int, int] | None = None  # None for the model's own
    label: str = ""  # a name for the control channel; IDs can repeat

    def __post_init__(self):
        series, own_bytes, own_speed = MODELS[self.model]
        self.series = series
        if self.model_bytes is None:
            self.model_bytes = own_bytes
        if not self.speed:
            self.speed = own_speed
        self.saved = bytearray(EEPROM_END)
        self.saved[0], self.saved[1] = 3, 10  # firmware version
        self.saved[3], self.saved[4] = self.model_bytes
        self.saved[5] = self.servo_id
        self.saved[7] = 0  # return delay
        self.saved[8] = 1  # answer every instruction
        self.saved[9:11] = series.word_bytes(0)
        self.saved[11:13] = series.word_bytes(series.max_raw)
        self.saved[13] = 70  # temperature limit
        self.saved[16:18] = series.word_bytes(1000)  # max torque
        self.power_up()

    # -- power ----------------------------------------------------------------

    def power_up(self) -> None:
        """What a servo is as its power comes on: the saved registers, no torque,
        locked, holding nothing."""
        self.memory = bytearray(256)
        self.memory[:EEPROM_END] = self.saved
        self.memory[self.lock_register] = 1
        self.torque = False
        self.goal = max(0, min(self.series.max_raw, round(self.position)))
        self.memory[registers.SC_GOAL : registers.SC_GOAL + 2] = self.series.word_bytes(self.goal)
        self.cap_speed = 0.0
        self.load = 0
        self.velocity = 0.0

    @property
    def lock_register(self) -> int:
        return self.series.lock_register

    @property
    def current_id(self) -> int:
        return self.memory[registers.ID]

    @property
    def locked(self) -> bool:
        return self.memory[self.lock_register] != 0

    def _word(self, address: int) -> int:
        return self.series.word(self.memory[address : address + 2])

    # -- the world ------------------------------------------------------------

    def travel(self) -> tuple[float, float]:
        """The lowest and highest it can reach from where it is."""
        low, high = self.lower, self.upper
        for block in self.blocks:
            if block.above:
                high = min(high, block.position)
            else:
                low = max(low, block.position)
        return low, high

    def step(self, seconds: float, powered: bool) -> None:
        if not (powered and self.plugged and self.torque):
            self.load = 0
            self.velocity = 0.0
            return
        error = self.goal - self.position
        effort = max(-1.0, min(1.0, error / 20.0))
        speed = self.speed if self.cap_speed <= 0 else min(self.speed, self.cap_speed)
        nxt = self.position + effort * speed * seconds
        if (error > 0 and nxt > self.goal) or (error < 0 and nxt < self.goal):
            nxt = self.goal
        low, high = self.travel()
        nxt = max(low, min(high, nxt))
        self.velocity = (nxt - self.position) / seconds
        self.position = nxt
        self.load = int(round(effort * 1000.0))

    def push_to(self, position: float) -> float:
        """Turn it by hand. It goes as far as its stops and blocks let it."""
        low, high = self.travel()
        self.position = max(low, min(high, float(position)))
        self.goal = round(self.position) if not self.torque else self.goal
        return self.position

    # -- packets --------------------------------------------------------------

    def _present_block(self) -> bytes:
        series = self.series
        position = max(0, min(series.max_raw, int(round(self.position))))
        speed = min(0x7FFF, int(abs(self.velocity)))
        speed_word = speed | (0x8000 if self.velocity < 0 else 0)
        load_word = (abs(self.load) & 0x3FF) | (0x400 if self.load < 0 else 0)
        moving = 1 if abs(self.velocity) > 0.5 else 0
        current_ma = 30 + abs(self.load) * 1.5 if self.torque else 5
        temperature = 28 + abs(self.load) // 100
        block = bytearray(15)
        block[0:2] = series.word_bytes(position)
        block[2:4] = series.word_bytes(speed_word)
        block[4:6] = series.word_bytes(load_word)
        block[6] = 61  # 6.1 V
        block[7] = temperature
        block[8] = 0
        block[9] = 0  # status (STS register 65)
        block[10] = moving
        block[13:15] = series.word_bytes(int(current_ma / 6.5))
        return bytes(block)

    def _read(self, address: int, count: int) -> bytes:
        self.memory[56:71] = self._present_block()
        self.memory[40] = 1 if self.torque else 0
        return bytes(self.memory[address : address + count])

    def _write(self, address: int, data: bytes) -> None:
        for offset, value in enumerate(data):
            register = address + offset
            if register in (3, 4) or 56 <= register <= 70:
                continue  # read only
            self.memory[register] = value
            if register < EEPROM_END and not self.locked:
                self.saved[register] = value
        end = address + len(data)
        if address <= registers.TORQUE < end:
            self.torque = self.memory[registers.TORQUE] != 0
        if address <= registers.SC_GOAL + 1 and end > registers.SC_GOAL:
            low = self._word(registers.MIN_LIMIT)
            high = self._word(registers.MAX_LIMIT)
            self.goal = max(low, min(high, self.series.position(self.memory[42:44])))
            self._cap_from(address, end)

    def _cap_from(self, address: int, end: int) -> None:
        """A goal's time (SC) or speed (STS) slows the move, when one is given."""
        self.cap_speed = 0.0
        if self.series.big_endian and end > GOAL_TIME + 1:
            time_ms = self._word(GOAL_TIME)
            if time_ms:
                self.cap_speed = abs(self.goal - self.position) / (time_ms / 1000.0)
        elif not self.series.big_endian and end > GOAL_SPEED + 1:
            self.cap_speed = float(self._word(GOAL_SPEED))

    def answer(self, instruction: int, params: bytes, broadcast: bool) -> bytes | None:
        """Carry out one instruction; return its reply packet, or None."""
        servo_id = self.current_id
        status = 0
        if instruction == INST_PING:
            return status_packet(servo_id, status)
        if instruction == INST_READ:
            if len(params) < 2:
                return None
            return status_packet(servo_id, status, self._read(params[0], params[1]))
        if instruction == INST_WRITE:
            if len(params) < 2:
                return None
            self._write(params[0], params[1:])
            if broadcast or self.memory[8] == 0:
                return None
            return status_packet(servo_id, status)
        return None

    def describe(self) -> dict:
        low, high = self.travel()
        return {
            "label": self.label,
            "id": self.current_id,
            "model": self.model,
            "plugged": self.plugged,
            "position": round(self.position, 1),
            "goal": self.goal,
            "torque": self.torque,
            "load": self.load,
            "locked": self.locked,
            "stops": [self.lower, self.upper],
            "blocks": [{"position": block.position, "side": "above" if block.above else "below"} for block in self.blocks],
            "reach": [low, high],
        }


def collide(replies: list[bytes]) -> bytes:
    """What the line carries when several servos answer at once: open drain, so a
    0 bit wins (the bytes AND), and no two start in the same instant."""
    length = max(len(reply) + index for index, reply in enumerate(replies))
    line = bytearray([0xFF]) * length
    for index, reply in enumerate(replies):
        for offset, byte in enumerate(reply):
            line[index + offset] &= byte
    return bytes(line)


class ServoBus:
    """The servos on one line, and its power."""

    def __init__(self, servos: list[PretendServo] | None = None):
        self.servos: list[PretendServo] = list(servos or [])
        self.powered = True
        self.stuck = False  # the line held low: nothing gets through

    def find(self, servo_id: int) -> list[PretendServo]:
        return [servo for servo in self.servos if servo.current_id == servo_id]

    def exchange(self, packet: bytes) -> bytes:
        """Put one instruction packet on the line; return what comes back."""
        if self.stuck or len(packet) < 6 or packet[:2] != b"\xff\xff":
            return b""
        servo_id, length, instruction = packet[2], packet[3], packet[4]
        if length < 2 or len(packet) < length + 4:
            return b""
        params = packet[5 : 5 + length - 2]
        if packet[5 + length - 2] != checksum(packet[2 : 5 + length - 2]):
            return b""  # servos ignore a packet whose checksum is wrong
        broadcast = servo_id == registers.BROADCAST_ID
        replies = []
        for servo in self.servos:
            if not (self.powered and servo.plugged):
                continue
            if broadcast or servo.current_id == servo_id:
                reply = servo.answer(instruction, params, broadcast and instruction == INST_WRITE)
                if reply:
                    replies.append(reply)
        if not replies:
            return b""
        return replies[0] if len(replies) == 1 else collide(replies)

    def step(self, seconds: float) -> None:
        for servo in self.servos:
            servo.step(seconds, self.powered)

    def cut_power(self) -> None:
        self.powered = False
        for servo in self.servos:
            servo.load = 0
            servo.velocity = 0.0

    def restore_power(self) -> None:
        self.powered = True
        for servo in self.servos:
            if servo.plugged:
                servo.power_up()
