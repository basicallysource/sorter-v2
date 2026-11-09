"""What the bytes in a Feetech serial servo mean.

The two series share one packet format and most register addresses, and differ
in what the numbers mean. Potentiometer servos (the SC series) store words high
byte first and count 0 to 1023 over about 200 degrees. Magnetic ones (the STS
series) store them low byte first and count 0 to 4095 over a full turn (Feetech's
communication protocol manual; its SCSCL.h and SMS_STS.h; the SCS15 and ST3215
memory tables).
"""

from __future__ import annotations

from dataclasses import dataclass

MODEL = 3  # two bytes
ID = 5
MIN_LIMIT = 9  # two bytes: the lowest position the servo accepts
MAX_LIMIT = 11  # two bytes: the highest
TORQUE = 40
STS_GOAL = 41  # acceleration, then position, time and speed
SC_GOAL = 42  # position, time and speed
PRESENT = 56  # the block read while a servo moves
PRESENT_BYTES = 15  # position, speed, load, voltage, temperature, a flag, status, moving, two unused, current

BROADCAST_ID = 254
LAST_ID = 253
FACTORY_ID = 1  # every new servo answers to this until it is given its own

# The status byte every reply carries (and STS register 65).
STATUS_VOLTAGE = 1 << 0
STATUS_SENSOR = 1 << 1
STATUS_TEMPERATURE = 1 << 2
STATUS_CURRENT = 1 << 3
STATUS_ANGLE = 1 << 4
STATUS_OVERLOAD = 1 << 5


@dataclass(frozen=True)
class Series:
    name: str
    big_endian: bool
    lock_register: int  # 0 opens the saved registers (like ID) for writing
    max_raw: int
    degrees_per_count: float
    # How close counts as there, and how little motion is none, in counts.
    arrived_within: int
    flat_within: int

    def word(self, data: bytes) -> int:
        return int.from_bytes(data[:2], "big" if self.big_endian else "little")

    def word_bytes(self, value: int) -> bytes:
        return int(value).to_bytes(2, "big" if self.big_endian else "little")

    def position(self, data: bytes) -> int:
        value = self.word(data)
        if self.big_endian:
            return value & 0x3FF
        # Bit 15 is the sign, in the multi-turn mode nothing here uses.
        return 0 if value & 0x8000 else min(value, self.max_raw)

    def load(self, data: bytes) -> int:
        """0 to 1000, signed by direction: bit 10 is the sign in both series."""
        value = self.word(data)
        magnitude = value & 0x3FF
        return -magnitude if value & 0x400 else magnitude

    def clamp(self, raw: float) -> int:
        return max(0, min(self.max_raw, int(round(raw))))

    def degrees(self, counts: float) -> float:
        return counts * self.degrees_per_count

    def counts(self, degrees: float) -> int:
        return int(round(degrees / self.degrees_per_count))


SC = Series(
    name="SC",
    big_endian=True,
    lock_register=48,
    max_raw=1023,
    degrees_per_count=200.0 / 1024,
    arrived_within=8,
    flat_within=3,
)
STS = Series(
    name="STS",
    big_endian=False,
    lock_register=55,
    max_raw=4095,
    degrees_per_count=360.0 / 4096,
    arrived_within=24,
    flat_within=6,
)


@dataclass(frozen=True)
class Model:
    name: str
    series: Series
    # The two bytes at MODEL this servo reads as. Listed both ways round: the
    # byte order of this word is not the same in every firmware Feetech shipped.
    model_bytes: tuple[tuple[int, int], ...]
    # Whether it has run on a real machine, or is here from its documents alone.
    proven: bool = False


MODELS: tuple[Model, ...] = (
    Model("SC15", SC, ((0, 15), (15, 0), (5, 15), (15, 5)), proven=True),
    Model("SC09", SC, ((0, 4), (0, 9), (4, 0), (5, 4), (4, 5), (9, 0))),
    Model("SC40", SC, ((0, 40), (40, 0))),
    Model("SC60", SC, ((0, 60), (60, 0))),
    Model("STS3215", STS, ((0x09, 0x03),)),
)


def model_for(model_bytes: bytes) -> Model | None:
    """The model that reads as these two bytes, or None for one not known here.
    An unknown model's registers may mean anything, so it is listed and never
    written to."""
    key = (model_bytes[0], model_bytes[1])
    for model in MODELS:
        if key in model.model_bytes:
            return model
    return None


@dataclass(frozen=True)
class Present:
    """One reading of a servo's PRESENT block."""

    position: int
    load: int
    volts: float
    temperature_c: int
    moving: bool
    status: int
    current_ma: float

    @property
    def overloaded(self) -> bool:
        return bool(self.status & STATUS_OVERLOAD)

    @property
    def too_hot(self) -> bool:
        return bool(self.status & STATUS_TEMPERATURE)


def decode_present(series: Series, data: bytes, status: int) -> Present:
    if not series.big_endian:
        status |= data[9]  # register 65 says the same things, and stays set
    return Present(
        position=series.position(data[0:2]),
        load=series.load(data[4:6]),
        volts=data[6] / 10,
        temperature_c=data[7],
        moving=data[10] != 0,
        status=status,
        current_ma=(series.word(data[13:15]) & 0x7FFF) * 6.5,
    )
