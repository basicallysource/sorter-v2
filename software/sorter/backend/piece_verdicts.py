"""What the classification channel made of each piece it saw, by track id, for
the live view: a double drop, or one piece (however many boxes the camera drew
it as)."""

from __future__ import annotations

import threading
from collections import OrderedDict

DOUBLE = "double"
ONE = "one"
_KEEP = 200

_lock = threading.Lock()
_verdicts: "OrderedDict[int, str]" = OrderedDict()


def note(track_id: int | None, verdict: str) -> None:
    if track_id is None:
        return
    with _lock:
        _verdicts[int(track_id)] = verdict
        _verdicts.move_to_end(int(track_id))
        while len(_verdicts) > _KEEP:
            _verdicts.popitem(last=False)


def get(track_id: int | None) -> str | None:
    if track_id is None:
        return None
    with _lock:
        return _verdicts.get(int(track_id))
