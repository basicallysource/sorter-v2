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


def channelEmpty(perception: Any, channel: int) -> Judge:
    """Free once the channel shows no piece at all."""

    def judge(since: float) -> Optional[bool]:
        state = _newest(perception, channel, since)
        if state is None:
            return None
        return not (getattr(state, "pieces", ()) or ())

    return judge


def turnIntoExit(perception: Any, channel: int) -> Optional[float]:
    """Output degrees to turn ``channel`` so its lead piece sits in the middle
    of its exit: forward, or backwards when that is shorter. None without a
    piece or an exit."""
    state = perception.read_states().get(channel)
    channel_def = perception.channels().get(channel)
    pieces = getattr(state, "pieces", ()) or ()
    if not pieces or channel_def is None:
        return None
    width = len(set(channel_def.exit_sections) - set(channel_def.precise_sections))
    if width <= 0:
        return None
    forward = (float(pieces[0].com_forward_to_exit_deg) + width / 2.0) % 360.0
    return forward if forward <= 180.0 else forward - 360.0
