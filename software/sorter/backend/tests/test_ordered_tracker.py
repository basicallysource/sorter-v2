"""Synthetic validation of the order-preserving channel tracker.

Geometry (orderedPieceObservations) is mocked so each frame's per-piece travel
gap + zone + bbox are scripted directly — this isolates the association logic
(order preservation, forward-only, coasting, new-at-drop, head-exit, and the
same-frame exit+entry disambiguation that relies on color)."""

import numpy as np
import pytest
from types import SimpleNamespace

from perception import ordered_tracker as ot
from perception.tracker_config import OrderedTrackerConfig

_DROP = 1
_FWD = 3
_CH = SimpleNamespace(center=(0.0, 0.0))
_SCRIPT: dict = {"obs": []}


def setup_function(_):
    # Patch the geometry helper so we drive (gap, zone, bbox) directly.
    ot.orderedPieceObservations = lambda bboxes, channel: list(_SCRIPT["obs"])


def _run(tr, obs, t, frame=None):
    # obs: list of (gap, zone, bbox), leading-first (ascending gap).
    _SCRIPT["obs"] = [(gap, 0, zone, bbox) for (gap, zone, bbox) in obs]
    upd = SimpleNamespace(
        bboxes=[o[2] for o in obs], scores=None, frame_bgr=frame, channel=_CH, timestamp=t
    )
    return tr.update(upd)


def test_single_piece_survives_big_forward_jumps():
    tr = ot.OrderedChannelTracker(OrderedTrackerConfig())
    out = _run(tr, [(300, _DROP, (100, 100, 140, 140))], 0.0)
    pid = out[(100, 100, 140, 140)]
    # Gap leaps 300 -> 180 -> 60 -> 10 (the platter flinging it forward). The id
    # must hold — this is exactly where IoU / angular-velocity trackers fail.
    out = _run(tr, [(180, _FWD, (130, 130, 170, 170))], 0.1)
    assert out[(130, 130, 170, 170)] == pid
    out = _run(tr, [(60, _FWD, (150, 150, 190, 190))], 0.2)
    assert out[(150, 150, 190, 190)] == pid
    out = _run(tr, [(10, _FWD, (160, 160, 200, 200))], 0.3)
    assert out[(160, 160, 200, 200)] == pid


def test_two_pieces_keep_distinct_ids_no_swap():
    tr = ot.OrderedChannelTracker(OrderedTrackerConfig())
    a, b = (200, 200, 240, 240), (60, 60, 100, 100)
    out = _run(tr, [(80, _FWD, b), (260, _DROP, a)], 0.0)  # b leads (smaller gap)
    ida, idb = out[a], out[b]
    assert ida != idb
    out = _run(tr, [(20, _FWD, b), (140, _FWD, a)], 0.1)  # both advance, order kept
    assert out[b] == idb and out[a] == ida


def test_blink_preserves_id():
    tr = ot.OrderedChannelTracker(OrderedTrackerConfig())
    box = (100, 100, 140, 140)
    pid = _run(tr, [(120, _FWD, box)], 0.0)[box]
    assert _run(tr, [], 0.1) == {}  # detector dropout — one empty frame
    out = _run(tr, [(70, _FWD, box)], 0.2)  # reappears, advanced
    assert out[box] == pid


def test_new_piece_at_drop_gets_fresh_id():
    tr = ot.OrderedChannelTracker(OrderedTrackerConfig())
    a = (200, 200, 240, 240)
    ida = _run(tr, [(100, _FWD, a)], 0.0)[a]
    b = (60, 60, 100, 100)  # arrives in the drop zone behind a
    out = _run(tr, [(40, _FWD, a), (300, _DROP, b)], 0.1)
    assert out[a] == ida
    assert out[b] != ida


def test_head_exit_retires_only_head():
    cfg = OrderedTrackerConfig()
    tr = ot.OrderedChannelTracker(cfg)
    a, b = (160, 160, 200, 200), (60, 60, 100, 100)
    out = _run(tr, [(25, _FWD, a), (180, _FWD, b)], 0.0)  # a is head (near exit)
    ida, idb = out[a], out[b]
    # a falls off the exit (gone); b advances. b can't match a's old slot (that
    # would be backward), so a is dropped and b keeps its id.
    out = _run(tr, [(110, _FWD, b)], 0.1)
    assert out[b] == idb
    # After the coast window, a's id is fully retired; b persists.
    out = _run(tr, [(80, _FWD, b)], 0.1 + cfg.max_coast_s + 0.5)
    live = {t.track_id for t in tr._tracks.values()}
    assert ida not in live and idb in live


def test_simultaneous_exit_and_entry_disambiguated_by_color():
    if ot.cv2 is None:
        pytest.skip("cv2 unavailable; color disambiguation not exercisable")
    cfg = OrderedTrackerConfig()
    tr = ot.OrderedChannelTracker(cfg)
    a_box, b_box, c_box = (10, 10, 30, 30), (50, 50, 70, 70), (90, 90, 110, 110)
    frame0 = np.full((130, 130, 3), 40, np.uint8)
    frame0[10:30, 10:30] = (0, 0, 255)   # a = red
    frame0[50:70, 50:70] = (0, 255, 0)   # b = green
    out = _run(tr, [(30, _FWD, a_box), (150, _FWD, b_box)], 0.0, frame0)
    ida, idb = out[a_box], out[b_box]

    # Same frame: a (red, head) falls off; b (green) advances PAST a's old slot;
    # c (blue) enters at the drop. Forward-only would let b inherit a's id, but
    # the color mismatch (red vs green) blocks that, so b keeps its own id.
    frame1 = np.full((130, 130, 3), 40, np.uint8)
    frame1[50:70, 50:70] = (0, 255, 0)   # b still green
    frame1[90:110, 90:110] = (255, 0, 0)  # c = blue
    out = _run(tr, [(20, _FWD, b_box), (300, _DROP, c_box)], 0.1, frame1)
    assert out[b_box] == idb       # b kept its identity (no id shift)
    assert out[c_box] not in (ida, idb)  # c is genuinely new
