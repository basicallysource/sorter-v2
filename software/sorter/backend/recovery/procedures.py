"""Recovery procedures, as data: the moves the machine tries, in order, to free
a stuck piece, checking after each whether it is free.

A move turns a channel (output degrees; negative turns it backwards), shakes it
(profiles.py), or turns it to bring the piece into its exit. ``this`` is the
channel the piece is on, ``above`` the one that feeds it. A probe turns this
channel a little afterwards: a piece that rides it again has moved, so it is
free; a shake on its own ends where it began and shows nothing. Probes turn
backwards, away from the exit, so they never push a piece off it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .profiles import shakeProfile


@dataclass(frozen=True)
class Move:
    channel: str  # "this" or "above"
    turn_deg: float = 0.0
    shake: str = ""
    to_exit: bool = False
    probe_deg: float = 0.0
    settle_s: float = 1.0

    def describe(self, names: dict[str, str]) -> str:
        name = names.get(self.channel, self.channel)
        if self.to_exit:
            what = f"Turn {name} to bring the piece into its exit"
        elif self.shake:
            what = f"Shake {name}: {shakeProfile(self.shake).label}"
        else:
            way = "back" if self.turn_deg < 0 else "forward"
            what = f"Turn {name} {way} {abs(self.turn_deg):g}°"
        if self.probe_deg:
            way = "back" if self.probe_deg < 0 else "forward"
            what += f", then turn {names.get('this', 'it')} {way} {abs(self.probe_deg):g}° to see if it rides"
        return what


@dataclass(frozen=True)
class Procedure:
    key: str
    title: str
    moves: tuple[Move, ...]
    # At the end (freed or not), turn this channel back by what the procedure
    # turned it, so its pockets sit where they were.
    restore: bool = False

    def steps(self, names: dict[str, str]) -> list[str]:
        return [move.describe(names) for move in self.moves]


# A piece where pieces land that its own channel does not carry: it most likely
# still hangs off the channel above. Nudge that one forward, more, then back;
# shake it; then shake this one and back it up (Spencer, 2026-10-19).
LANDING_HELD = Procedure(
    "landing_held",
    "Free a piece held where pieces land",
    (
        Move("above", turn_deg=3.0, probe_deg=-6.0),
        Move("above", turn_deg=6.0, probe_deg=-6.0),
        Move("above", turn_deg=-6.0, probe_deg=-6.0),
        Move("above", shake="brief", probe_deg=-6.0),
        Move("this", shake="heavy", probe_deg=-6.0),
        Move("this", turn_deg=-15.0, probe_deg=-6.0),
        Move("this", shake="hard", probe_deg=-6.0),
    ),
)

# A piece that rides the classification channel past its exit instead of
# falling off (often a tire): bring it into the exit and shake it off, harder
# each time, backing up once in between.
C4_SHAKE_OFF = Procedure(
    "c4_shake_off",
    "Shake a piece off the classification channel",
    (
        Move("this", to_exit=True, settle_s=1.5),
        Move("this", shake="heavy"),
        Move("this", shake="hard"),
        Move("this", turn_deg=-10.0),
        Move("this", turn_deg=10.0),
        Move("this", shake="max"),
    ),
    restore=True,
)

PROCEDURES: dict[str, Procedure] = {p.key: p for p in (LANDING_HELD, C4_SHAKE_OFF)}
