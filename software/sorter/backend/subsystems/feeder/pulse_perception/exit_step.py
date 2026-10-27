"""One piece in the opening at a time.

A channel's exit is an opening in its wall, and a piece can ride a good way
into it before it slides off. Each exit pulse meanwhile carries the piece
behind it closer, and once that one's center is at the opening too, the next
pulse drops both about half the time, against about one time in a hundred with
it further back (C2 and C3 alike).

So while the lead is in the opening, the exit never turns so far that the next
piece's center comes within ``clear_deg`` of the opening. When it cannot turn
at all, it shakes: back a little, then forward as far, which jolts the lead and
brings the next piece no closer. A next piece already too close is backed off
first, if the lead stays in the opening while it does. After MAX_TRIES of these
for one lead, or when the two are too close to part, the exit pushes as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Back-offs and shakes for one lead before it is pushed off whatever follows.
MAX_TRIES = 4
# A push shorter than this does nothing useful: shake instead.
MIN_PUSH_DEG = 0.5
# Backing off leaves the next piece this much further back than clear_deg, and
# the lead at least this far into the opening.
BACK_OFF_EXTRA_DEG = 1.0


@dataclass(frozen=True)
class ExitStep:
    # "push" forward, "back" off (turn backwards), or "shake" (backwards, then
    # forward as far).
    kind: str
    deg: float
    # Why a push goes ahead with the next piece too close: "" when it is not.
    why: str = ""


def exitStep(
    lead_deg: float,
    next_deg: Optional[float],
    push_deg: float,
    shake_deg: float,
    clear_deg: float,
    tries: int,
) -> ExitStep:
    """The exit's next move. ``lead_deg`` and ``next_deg`` are how far short of
    the opening the lead's and the next piece's centers are (negative: in it),
    ``push_deg`` the exit move without this rule, and ``tries`` the back-offs
    and shakes made for this lead so far."""
    if clear_deg <= 0 or next_deg is None:
        return ExitStep("push", push_deg)
    room = next_deg - clear_deg
    if room >= MIN_PUSH_DEG:
        return ExitStep("push", min(push_deg, room))
    if lead_deg >= 0:
        return ExitStep("push", push_deg, "beside the lead")
    if tries >= MAX_TRIES:
        return ExitStep("push", push_deg, "tries used up")
    if room < 0:
        back = BACK_OFF_EXTRA_DEG - room
        if lead_deg + back > -BACK_OFF_EXTRA_DEG:
            return ExitStep("push", push_deg, "too close to part")
        return ExitStep("back", back)
    return ExitStep("shake", shake_deg)
