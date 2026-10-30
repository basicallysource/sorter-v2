"""How a recovery tells the piece is free, from a picture taken after its last
move settled: None while there is no such picture yet."""

from __future__ import annotations

import math
from typing import Any, Optional

from .runner import Judge

Box = tuple[float, float, float, float]


def _center(box: Box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0


def _newest(perception: Any, channel: int, since: float) -> Any:
    state = perception.read_states().get(channel)
    if state is None or float(getattr(state, "ts", 0.0) or 0.0) < since:
        return None
    return state


def pieceGoneFrom(perception: Any, channel: int, box: Box) -> Judge:
    """Free once no piece on the channel sits where the stuck one sat: it rode
    away with the channel, or fell where it should."""
    cx, cy = _center(box)
    near = max(15.0, 0.25 * max(box[2] - box[0], box[3] - box[1]))

    def judge(since: float) -> Optional[bool]:
        state = _newest(perception, channel, since)
        if state is None:
            return None
        for piece in getattr(state, "pieces", ()) or ():
            px, py = _center(piece.bbox)
            if math.hypot(px - cx, py - cy) <= near:
                return False
        return True

    return judge


def _exitWidth(channel_def: Any) -> int:
    return len(set(channel_def.exit_sections) - set(channel_def.precise_sections))


def exitEmpty(perception: Any, channel: int) -> Judge:
    """Free once no piece sits in the channel's exit: the stuck one, turned
    into it, has fallen. Other pieces were kept out of it."""

    def judge(since: float) -> Optional[bool]:
        state = _newest(perception, channel, since)
        channel_def = perception.channels().get(channel)
        if state is None or channel_def is None:
            return None
        width = _exitWidth(channel_def)
        return not any(-width <= float(p.com_forward_to_exit_deg) <= 0.0 for p in (getattr(state, "pieces", ()) or ()))

    return judge


def turnIntoExit(
    perception: Any, channel: int, target_track: Optional[int] = None, margin_deg: float = 3.0
) -> Optional[float]:
    """Output degrees to turn ``channel`` so the piece with ``target_track``
    (else its lead piece) sits in the middle of its exit, forward or backwards,
    whichever is shorter and carries no other piece through the exit (or within
    ``margin_deg`` of it). None without such a turn, a piece or an exit.

    A piece's place is its forward distance to the exit, 0 to 360, the exit
    being its last ``width`` degrees: turning forward by t brings a piece at u
    into the exit once t passes u; turning back by s, once u + s passes
    360 - width."""
    state = perception.read_states().get(channel)
    channel_def = perception.channels().get(channel)
    pieces = list(getattr(state, "pieces", ()) or ())
    if not pieces or channel_def is None:
        return None
    width = _exitWidth(channel_def)
    if width <= 0:
        return None
    if target_track is None:
        target = pieces[0]
    else:
        target = next((p for p in pieces if getattr(p, "sv_bt_track_id", None) == target_track), None)
        if target is None:
            return None
    others = [float(p.com_forward_to_exit_deg) % 360.0 for p in pieces if p is not target]
    if any(u >= 360.0 - width - margin_deg for u in others):
        return None  # another piece is in the exit, or about to be
    u = float(target.com_forward_to_exit_deg) % 360.0
    middle = 360.0 - width / 2.0
    forward = (u - middle) % 360.0
    back = (middle - u) % 360.0
    ways = []
    if all(forward < o - margin_deg for o in others):
        ways.append(forward)
    if all(o + back < 360.0 - width - margin_deg for o in others):
        ways.append(-back)
    return min(ways, key=abs) if ways else None
