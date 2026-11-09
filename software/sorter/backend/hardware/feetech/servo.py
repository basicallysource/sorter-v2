"""One servo on a bus: who it is, where it is, and moving it without ever
leaning on whatever is in its way.

Positions here are the servo's own counts (0 to `series.max_raw`). Nothing in
this module knows what a servo is for.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import registers
from .link import (
    FLAG_RELEASE_AFTER_BACKOFF,
    FLAG_RELEASE_ON_ARRIVAL,
    GarbledReply,
    GuardMove,
    GuardProbe,
    GuardReport,
    GuardState,
    NoReply,
    ServoLink,
    ServoLinkError,
    series_flag,
)

# A move's own time on top of the time its distance takes, before the guard
# gives up on it.
MOVE_GRACE_MS = 1500
# The fastest a door servo is asked to turn, in degrees a second, when no speed
# is given. An SC15 does about 300 unloaded.
DEFAULT_SPEED_DEG_S = 180.0
# The servos' IDs a scan asks. Doors are numbered from 1; a new servo is 1.
SCAN_IDS = range(1, 21)


class UnknownModel(ServoLinkError):
    """A servo answered, but its model is not one whose registers are known
    here, so it is never written to."""

    def __init__(self, servo_id: int, model_bytes: bytes):
        self.servo_id = servo_id
        self.model_bytes = bytes(model_bytes)
        super().__init__(
            f"Servo {servo_id} is a model this software does not know "
            f"(it reads {model_bytes[0]}, {model_bytes[1]}), so it will not be moved."
        )


@dataclass(frozen=True)
class FoundServo:
    """What a scan learned about one ID on the bus."""

    servo_id: int
    # "ok": one servo of a known model. "shared": two or more servos answer to
    # this ID at once. "unknown": a model this software does not know.
    state: str
    model: str | None = None
    position: int | None = None
    volts: float | None = None
    temperature_c: int | None = None
    torque_on: bool | None = None


class BusServo:
    def __init__(self, link: ServoLink, servo_id: int, model: registers.Model):
        self.link = link
        self.servo_id = servo_id
        self.model = model
        self.series = model.series

    @classmethod
    def identify(cls, link: ServoLink, servo_id: int) -> "BusServo":
        """The servo answering to this ID. Raises NoReply if there is none,
        GarbledReply if several share it and UnknownModel for one not known here."""
        _, model_bytes = link.read(servo_id, registers.MODEL, 2)
        model = registers.model_for(model_bytes)
        if model is None:
            raise UnknownModel(servo_id, model_bytes)
        return cls(link, servo_id, model)

    # --- reading ---

    def present(self) -> registers.Present:
        status, data = self.link.read(self.servo_id, registers.PRESENT, registers.PRESENT_BYTES)
        return registers.decode_present(self.series, data, status)

    def torque_on(self) -> bool:
        _, data = self.link.read(self.servo_id, registers.TORQUE, 1)
        return data[0] != 0

    def limits(self) -> tuple[int, int]:
        """The lowest and highest position the servo itself accepts."""
        _, data = self.link.read(self.servo_id, registers.MIN_LIMIT, 4)
        return self.series.word(data[0:2]), self.series.word(data[2:4])

    def state(self) -> GuardReport:
        return self.link.state(self.servo_id)

    # --- moving ---

    def move(
        self,
        goal: int,
        *,
        speed_deg_s: float | None = None,
        release_on_arrival: bool = False,
        release_after_backoff: bool = True,
        stall_load: int = 400,
        stall_ms: int = 150,
        backoff: int | None = None,
    ) -> None:
        """Start a guarded move to `goal`. It ends by arriving, by stalling (the
        servo is backed off, and by default let go), or by running out of time."""
        goal = self.series.clamp(goal)
        speed_counts = max(1.0, self.series.counts(speed_deg_s or DEFAULT_SPEED_DEG_S))
        distance = abs(goal - self.present().position)
        time_ms = int(min(60000, max(20, distance / speed_counts * 1000)))
        flags = series_flag(self.series)
        if release_on_arrival:
            flags |= FLAG_RELEASE_ON_ARRIVAL
        if release_after_backoff:
            flags |= FLAG_RELEASE_AFTER_BACKOFF
        self.link.move(
            self.servo_id,
            GuardMove(
                flags=flags,
                goal=goal,
                # The SC series takes the move's time; the STS series its speed.
                time_ms=time_ms if self.series.big_endian else 0,
                speed=0 if self.series.big_endian else int(min(0xFFFF, speed_counts)),
                accel=0 if self.series.big_endian else 50,
                stall_load=stall_load,
                stall_ms=stall_ms,
                flat=self.series.flat_within,
                arrived=self.series.arrived_within,
                backoff=self.series.counts(6.0) if backoff is None else backoff,
                timeout_ms=min(0xFFFF, time_ms + MOVE_GRACE_MS),
            ),
        )

    def probe(self, direction: int, *, limit: int | None = None, backoff: int | None = None) -> None:
        """Start a slow search for whatever stops the servo toward higher counts
        (direction +1) or lower (-1), no further than `limit`. It ends in
        contact, where the report's mark is the place, or with no contact."""
        if limit is None:
            limit = self.series.max_raw if direction > 0 else 0
        self.link.probe(
            self.servo_id,
            GuardProbe(
                flags=series_flag(self.series) | FLAG_RELEASE_AFTER_BACKOFF,
                direction=1 if direction > 0 else -1,
                limit=self.series.clamp(limit),
                # About half a degree every 20 ms: 30 degrees a second.
                step=max(1, self.series.counts(0.6)),
                period_ms=20,
                # A free servo trails its creeping goal by a degree at most.
                lag=max(4, self.series.counts(2.4)),
                load=700,
                backoff=self.series.counts(3.0) if backoff is None else backoff,
            ),
        )

    def wait(self, timeout_s: float = 30.0, poll_s: float = 0.02) -> GuardReport:
        """Wait for the move or probe under way to end, and return how."""
        deadline = time.monotonic() + timeout_s
        report = self.state()
        while report.busy and time.monotonic() < deadline:
            time.sleep(poll_s)
            report = self.state()
        return report

    def hold(self) -> None:
        self.link.stop(self.servo_id, release=False)

    def release(self) -> None:
        self.link.stop(self.servo_id, release=True)

    # --- its ID ---

    def set_id(self, new_id: int) -> "BusServo":
        """Give the servo another ID, kept through power off. Refused if a servo
        already answers to it. Returns the servo under its new ID."""
        if not 1 <= new_id <= registers.LAST_ID:
            raise ValueError(f"A servo's ID is 1 to {registers.LAST_ID}.")
        if new_id == self.servo_id:
            return self
        try:
            self.link.ping(new_id)
        except NoReply:
            pass
        except GarbledReply:
            raise ValueError(f"Several servos already answer to ID {new_id}.") from None
        else:
            raise ValueError(f"A servo already answers to ID {new_id}.")
        lock = self.series.lock_register
        self.link.write(self.servo_id, lock, b"\x00")
        time.sleep(0.01)
        try:
            self.link.write(self.servo_id, registers.ID, bytes([new_id]))
        except NoReply:
            # The servo takes the new ID at once and answers this write from
            # it, which reads as silence here. What answers at the new ID next
            # says whether it worked.
            pass
        time.sleep(0.01)
        try:
            self.link.write(new_id, lock, b"\x01")
        except NoReply:
            # It did not take the ID. Its old lock goes back, if it still answers there.
            try:
                self.link.write(self.servo_id, lock, b"\x01")
            except ServoLinkError:
                pass
            raise ServoLinkError(
                f"No servo answers to ID {new_id} after the change, so servo {self.servo_id} did not take it."
            ) from None
        return BusServo(self.link, new_id, self.model)


def scan(link: ServoLink, ids: range = SCAN_IDS) -> list[FoundServo]:
    """Ask every ID in turn and say what answers. Two servos with one ID answer
    over each other: sometimes their pings line up and read as one servo, so a
    longer read, where they differ, is asked for too."""
    found: list[FoundServo] = []
    for servo_id in ids:
        try:
            link.ping(servo_id)
            servo = BusServo.identify(link, servo_id)
            present = servo.present()
            found.append(
                FoundServo(
                    servo_id=servo_id,
                    state="ok",
                    model=servo.model.name,
                    position=present.position,
                    volts=present.volts,
                    temperature_c=present.temperature_c,
                    torque_on=servo.torque_on(),
                )
            )
        except NoReply:
            continue
        except GarbledReply:
            found.append(FoundServo(servo_id=servo_id, state="shared"))
        except UnknownModel:
            found.append(FoundServo(servo_id=servo_id, state="unknown"))
    return found
