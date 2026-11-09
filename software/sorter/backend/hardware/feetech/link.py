"""A link to a servo bus: one conversation with one servo at a time, and moves
that are watched until they end.

A servo pushing against something it cannot move draws its stall current until
something lets go. So nothing above a link ever moves a servo with a bare write:
it asks for a guarded move, and the link (the control board's firmware, or the
guard in `guard.py` for a USB adapter) reads the servo every few milliseconds,
backs it off when it meets resistance, and reports what happened.

The wire formats here are the control board's (`SERVO_BUS MOVE`, `PROBE` and
`STATE` in the firmware's README).
"""

from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum

from . import registers


class ServoLinkError(Exception):
    """A servo conversation that got no good answer."""


class NoReply(ServoLinkError):
    """Silence: no servo has that ID, or it has no power."""


class GarbledReply(ServoLinkError):
    """Bytes came back that are no packet: two servos share the ID and answer
    over each other (new servos all come as ID 1), or the line is noisy."""


class LineStuck(ServoLinkError):
    """The line did not carry what was sent: it is held low or shorted."""


class GuardFull(ServoLinkError):
    """The guard already watches as many moving servos as it can."""


class LinkDown(ServoLinkError):
    """The way to the bus itself failed: the board or the adapter is gone."""


class GuardState(IntEnum):
    IDLE = 0  # not watched: never moved through the guard, or handed back
    MOVING = 1
    ARRIVED = 2
    STALLED = 3  # met resistance on the way, and backed off
    TIMED_OUT = 4  # neither arrived nor stalled in time, and stopped where it was
    LOST = 5  # stopped answering
    PROBING = 6
    CONTACT = 7  # a probe met resistance, and backed off
    NO_CONTACT = 8  # a probe reached its limit and met nothing


FLAG_SC = 1 << 0  # the SC series; without it, the STS series
FLAG_RELEASE_ON_ARRIVAL = 1 << 1
FLAG_RELEASE_AFTER_BACKOFF = 1 << 2


def series_flag(series: registers.Series) -> int:
    return FLAG_SC if series.big_endian else 0


@dataclass(frozen=True)
class GuardMove:
    """A move to `goal`, watched until it arrives, stalls or runs out of time."""

    flags: int
    goal: int
    time_ms: int = 0  # SC: the move's time, 0 for as fast as it goes
    speed: int = 0  # STS: counts a second, 0 for as fast as it goes
    accel: int = 0  # STS: the acceleration register
    stall_load: int = 400  # load, 0 to 1000, that with no motion is a stall
    stall_ms: int = 150  # how long that must last
    flat: int = 3  # counts of motion below which it is not moving
    arrived: int = 8  # counts from the goal that are the goal
    backoff: int = 30  # counts to come back from where it stalled
    timeout_ms: int = 4000  # 0 for no limit

    _FORMAT = "<BHHHBHHBBHH"

    def pack(self) -> bytes:
        return struct.pack(
            self._FORMAT,
            self.flags,
            self.goal,
            self.time_ms,
            self.speed,
            self.accel,
            self.stall_load,
            self.stall_ms,
            self.flat,
            self.arrived,
            self.backoff,
            self.timeout_ms,
        )

    @classmethod
    def unpack(cls, payload: bytes) -> "GuardMove":
        return cls(*struct.unpack(cls._FORMAT, payload))


@dataclass(frozen=True)
class GuardProbe:
    """A slow search for whatever stops the servo in one direction."""

    flags: int
    direction: int  # +1 toward higher counts, -1 toward lower
    limit: int  # the position never to pass
    step: int = 3  # counts the goal advances each period
    period_ms: int = 20
    lag: int = 12  # counts behind its goal that mean it is held
    load: int = 700  # load, 0 to 1000, that means it is held
    backoff: int = 15  # counts to come back from where it was held

    _FORMAT = "<BbBBHHHH"

    def pack(self) -> bytes:
        return struct.pack(
            self._FORMAT,
            self.flags,
            self.direction,
            self.step,
            self.period_ms,
            self.limit,
            self.lag,
            self.load,
            self.backoff,
        )

    @classmethod
    def unpack(cls, payload: bytes) -> "GuardProbe":
        flags, direction, step, period_ms, limit, lag, load, backoff = struct.unpack(cls._FORMAT, payload)
        return cls(flags, direction, limit, step, period_ms, lag, load, backoff)


@dataclass(frozen=True)
class GuardReport:
    """What the guard knows of one servo."""

    state: GuardState
    position: int  # as last read
    load: int  # as last read, signed by direction
    mark: int  # where it stalled or met resistance
    peak_load: int  # the most load seen since it began
    elapsed_ms: int  # since it began, until it ended

    _FORMAT = "<BHhHHH"

    @property
    def busy(self) -> bool:
        return self.state in (GuardState.MOVING, GuardState.PROBING)

    def pack(self) -> bytes:
        return struct.pack(
            self._FORMAT, int(self.state), self.position, self.load, self.mark, self.peak_load, self.elapsed_ms
        )

    @classmethod
    def unpack(cls, payload: bytes) -> "GuardReport":
        state, position, load, mark, peak_load, elapsed_ms = struct.unpack(cls._FORMAT, payload[: struct.calcsize(cls._FORMAT)])
        return cls(GuardState(state), position, load, mark, peak_load, elapsed_ms)


class ServoLink(ABC):
    """One servo bus. Every method raises a ServoLinkError when no good answer
    comes; none of them is retried here."""

    #: What a person would call the thing this bus hangs off, for messages.
    label: str = "servo bus"

    @abstractmethod
    def ping(self, servo_id: int) -> int:
        """The servo's status byte."""

    @abstractmethod
    def read(self, servo_id: int, address: int, count: int) -> tuple[int, bytes]:
        """The servo's status byte and `count` bytes from `address`."""

    @abstractmethod
    def write(self, servo_id: int, address: int, data: bytes) -> None:
        """Write registers. This ends any guarded move of that servo: whoever
        writes to a servo has taken it over."""

    @abstractmethod
    def move(self, servo_id: int, move: GuardMove) -> None: ...

    @abstractmethod
    def probe(self, servo_id: int, probe: GuardProbe) -> None: ...

    @abstractmethod
    def state(self, servo_id: int) -> GuardReport: ...

    @abstractmethod
    def stop(self, servo_id: int, *, release: bool) -> None:
        """Stop watching and stop the servo: let it go, or hold it where it is.
        `registers.BROADCAST_ID` is every servo, and only lets go."""

    def close(self) -> None:
        return
