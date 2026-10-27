"""One recovery procedure running against one stuck piece, stepped by the
control loop while the piece's incident holds the machine.

Each move's motions go out one at a time, each once the one before has finished;
then the move settles, and the judge looks at a picture taken after that: freed
(the piece is gone from where it was stuck), not yet, or no new picture yet.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from .motors import ChannelMotor
from .procedures import Move, Procedure
from .profiles import shakeProfile

RUNNING = "running"
FREED = "freed"
GAVE_UP = "gave up"
STOPPED = "stopped"

# A motor that should have finished by now is asked again this often.
RECHECK_S = 0.2

Judge = Callable[[float], Optional[bool]]


class Recovery:
    def __init__(
        self,
        procedure: Procedure,
        motors: dict[str, ChannelMotor],
        judge: Judge,
        exit_turn: Callable[[], Optional[float]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.procedure = procedure
        self.motors = motors
        self.judge = judge
        self.exit_turn = exit_turn
        self._clock = clock
        self._wall = wall
        self.index = 0
        self.state = RUNNING
        self.restoring = False
        self._motions: list[tuple[str, str, float | str]] = []
        self._moving: Optional[str] = None
        self._wait_until = 0.0
        self._settled_at: Optional[float] = None
        self._net_turn = 0.0
        self._begin(procedure.moves[0])

    @property
    def names(self) -> dict[str, str]:
        return {role: motor.label for role, motor in self.motors.items()}

    @property
    def done(self) -> bool:
        return self.state != RUNNING and not self.restoring and self._moving is None and not self._motions

    def progress(self) -> dict[str, object]:
        moves = self.procedure.moves
        index = min(self.index, len(moves) - 1)
        if self.restoring:
            doing = f"Turning {self.names.get('this', 'the channel')} back to where it was"
        elif self.state == RUNNING:
            doing = moves[index].describe(self.names)
        else:
            doing = ""
        return {
            "procedure": self.procedure.key,
            "title": self.procedure.title,
            "step": index + 1,
            "steps": len(moves),
            "doing": doing,
            "state": self.state,
        }

    def stop(self) -> None:
        """Stop where it is: the motion under way finishes, nothing more goes out."""
        if self.state == RUNNING or self.restoring:
            self.state = STOPPED if self.state == RUNNING else self.state
            self.restoring = False
            self._motions = []

    def step(self) -> None:
        if self.done:
            return
        now = self._clock()
        if now < self._wait_until:
            return
        if self._moving is not None:
            if not self.motors[self._moving].idle():
                self._wait_until = now + RECHECK_S
                return
            self._moving = None
        if self._motions:
            self._startMotion(now)
            return
        if self.restoring:
            self.restoring = False
            return
        if self.state != RUNNING:
            return
        move = self.procedure.moves[self.index]
        if self._settled_at is None:
            self._settled_at = self._wall() + move.settle_s
            self._wait_until = now + move.settle_s
            return
        verdict = self.judge(self._settled_at)
        if verdict is None:
            self._wait_until = now + 0.1
            return
        if verdict:
            self._finish(FREED)
            return
        self.index += 1
        if self.index >= len(self.procedure.moves):
            self._finish(GAVE_UP)
            return
        self._begin(self.procedure.moves[self.index])

    def _begin(self, move: Move) -> None:
        motions: list[tuple[str, str, float | str]] = []
        if move.to_exit:
            deg = self.exit_turn() if self.exit_turn is not None else None
            if deg:
                motions.append(("this", "turn", float(deg)))
        elif move.shake:
            motions.append((move.channel, "shake", move.shake))
        elif move.turn_deg:
            motions.append((move.channel, "turn", move.turn_deg))
        if move.probe_deg:
            motions.append(("this", "turn", move.probe_deg))
        self._motions = motions
        self._settled_at = None

    def _startMotion(self, now: float) -> None:
        role, kind, value = self._motions.pop(0)
        motor = self.motors[role]
        if kind == "turn":
            seconds = motor.turn(float(value))
            if seconds is not None and role == "this":
                self._net_turn += float(value)
        else:
            seconds = motor.shake(shakeProfile(str(value)))
        if seconds is None:
            # The motor would not take it: try again a moment later.
            self._motions.insert(0, (role, kind, value))
            self._wait_until = now + 0.5
            return
        self._moving = role
        self._wait_until = now + seconds

    def _finish(self, state: str) -> None:
        self.state = state
        self._motions = []
        if self.procedure.restore and abs(self._net_turn) > 1e-6:
            self.restoring = True
            self._motions = [("this", "turn", -self._net_turn)]
            self._net_turn = 0.0
