"""A servo bus that asks again before it calls a servo silent.

Now and then a reply is lost: the servo cable is long, runs beside motor wires
and may cross a slip ring. One lost reply is not a servo that stopped answering,
so every question is asked up to three times before its error is passed on.
Asking again changes nothing: a read reads again, a write writes the same
values, and a guarded move or probe starts over from where the servo is (if the
first one did start the servo, the second is what puts the guard on it).

It also counts, for every servo that has ever answered, how often it was asked,
how often it had to be asked again and how often it never answered: that is how
good the cable to it is.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, TypeVar

from .link import GarbledReply, GuardMove, GuardProbe, GuardReport, LineStuck, NoReply, ServoLink

ATTEMPTS = 3
# A scan pings every ID there is, and most are nobody: twice is enough to not
# lose a servo that is there, without tripling the time the scan takes.
PING_ATTEMPTS = 2
PAUSE_S = 0.003

T = TypeVar("T")


@dataclass
class BusCount:
    asked: int = 0
    # Questions that needed asking more than once, and got their answer.
    repeated: int = 0
    # Questions no attempt got an answer to.
    unanswered: int = 0


class PatientLink(ServoLink):
    def __init__(self, inner: ServoLink):
        self._inner = inner
        self.label = inner.label
        self._counts: dict[int, BusCount] = {}
        # The last questions that got no good answer at some attempt, for finding
        # out which kind of question a cable or a servo loses.
        self._misses: deque[dict] = deque(maxlen=60)
        self._lock = threading.Lock()

    def _ask(self, servo_id: int, what: str, call: Callable[[], T], attempts: int = ATTEMPTS) -> T:
        for attempt in range(1, attempts + 1):
            try:
                answer = call()
            except (NoReply, GarbledReply, LineStuck) as exc:
                self._missed(servo_id, what, attempt, exc)
                if attempt == attempts:
                    self._note(servo_id, answered=False, repeated=False)
                    raise
                time.sleep(PAUSE_S)
                continue
            self._note(servo_id, answered=True, repeated=attempt > 1)
            return answer
        raise AssertionError("unreachable")

    def _missed(self, servo_id: int, what: str, attempt: int, exc: Exception) -> None:
        with self._lock:
            if servo_id in self._counts:
                self._misses.append(
                    {"at": time.time(), "servo_id": servo_id, "what": what, "attempt": attempt, "error": type(exc).__name__}
                )

    def misses(self) -> list[dict]:
        with self._lock:
            return list(self._misses)

    def _note(self, servo_id: int, *, answered: bool, repeated: bool) -> None:
        with self._lock:
            count = self._counts.get(servo_id)
            if count is None:
                # An ID that has never answered is nobody: a scan asks hundreds.
                if not answered:
                    return
                count = self._counts[servo_id] = BusCount()
            count.asked += 1
            if repeated:
                count.repeated += 1
            if not answered:
                count.unanswered += 1

    def counts(self) -> dict[int, BusCount]:
        """A copy of the count for every servo that has ever answered."""
        with self._lock:
            return {servo_id: BusCount(c.asked, c.repeated, c.unanswered) for servo_id, c in self._counts.items()}

    def ping(self, servo_id: int) -> int:
        return self._ask(servo_id, "ping", lambda: self._inner.ping(servo_id), PING_ATTEMPTS)

    def read(self, servo_id: int, address: int, count: int) -> tuple[int, bytes]:
        return self._ask(servo_id, f"read {address}+{count}", lambda: self._inner.read(servo_id, address, count))

    def write(self, servo_id: int, address: int, data: bytes) -> None:
        self._ask(servo_id, f"write {address}", lambda: self._inner.write(servo_id, address, data))

    def move(self, servo_id: int, move: GuardMove) -> None:
        self._ask(servo_id, "move", lambda: self._inner.move(servo_id, move))

    def probe(self, servo_id: int, probe: GuardProbe) -> None:
        self._ask(servo_id, "probe", lambda: self._inner.probe(servo_id, probe))

    def state(self, servo_id: int) -> GuardReport:
        # The guard's own record: nothing goes out on the bus for it.
        return self._inner.state(servo_id)

    def stop(self, servo_id: int, *, release: bool) -> None:
        self._ask(servo_id, "let go" if release else "hold", lambda: self._inner.stop(servo_id, release=release))

    def close(self) -> None:
        self._inner.close()
