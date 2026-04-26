from __future__ import annotations

import pytest

from rt.services.section_feeder_handler import (
    PulseMode,
    SectionFeederHandler,
)
from rt.services.sector_shadow_observer import ChannelGeometry


_C2_GEOM = ChannelGeometry(
    name="c2",
    exit_arc_deg=30.0,
    intake_center_deg=180.0,
    intake_arc_deg=30.0,
)
_C3_GEOM = ChannelGeometry(
    name="c3",
    exit_arc_deg=20.0,
    intake_center_deg=180.0,
    intake_arc_deg=30.0,
)


class _Recorder:
    """Captures calls to a pulse callable."""

    def __init__(self, *, success: bool = True) -> None:
        self.calls: list[tuple] = []
        self.success = success

    def __call__(self, *args) -> bool:
        self.calls.append(args)
        return self.success


class _StubHw:
    def __init__(self) -> None:
        self._busy = False
        self._pending = 0

    def busy(self) -> bool:
        return self._busy

    def pending(self) -> int:
        return self._pending


def _make(c1=None, c2=None, c3=None, c1_hw=None, c2_hw=None, c3_hw=None) -> SectionFeederHandler:
    return SectionFeederHandler(
        c1_pulse=c1 or _Recorder(),
        c2_pulse=c2 or _Recorder(),
        c3_pulse=c3 or _Recorder(),
        c1_hw=c1_hw,
        c2_hw=c2_hw,
        c3_hw=c3_hw,
        c2_geometry=_C2_GEOM,
        c3_geometry=_C3_GEOM,
        c1_cooldown_s=0.0,
        c2_cooldown_s=0.0,
        c3_cooldown_s=0.0,
    )


def test_disabled_handler_takes_no_action() -> None:
    c1, c2, c3 = _Recorder(), _Recorder(), _Recorder()
    h = _make(c1=c1, c2=c2, c3=c3)
    # enable() not called -> nothing happens.
    h.tick(c2_tracks=[], c3_tracks=[], c4_admission_allowed=True, now_mono=0.0)
    assert c1.calls == [] and c2.calls == [] and c3.calls == []


def test_c1_pulses_when_c2_intake_clear() -> None:
    c1, c2, c3 = _Recorder(), _Recorder(), _Recorder()
    h = _make(c1=c1, c2=c2, c3=c3)
    h.enable()
    # No tracks anywhere. C1 should fire (Main: intake clear → allow C1).
    h.tick(c2_tracks=[], c3_tracks=[], c4_admission_allowed=True, now_mono=0.0)
    assert len(c1.calls) == 1


def test_c1_blocked_when_c2_intake_occupied() -> None:
    c1, c2, c3 = _Recorder(), _Recorder(), _Recorder()
    h = _make(c1=c1, c2=c2, c3=c3)
    h.enable()
    # A track at 180° = C2 intake center.
    h.tick(
        c2_tracks=[{"angle_deg": 180.0}],
        c3_tracks=[],
        c4_admission_allowed=True,
        now_mono=0.0,
    )
    assert c1.calls == []


def test_c2_pulse_normal_when_only_in_middle() -> None:
    c1, c2, c3 = _Recorder(), _Recorder(), _Recorder()
    h = _make(c1=c1, c2=c2, c3=c3)
    h.enable()
    # C2 has a piece at -90° (middle, not exit, not intake).
    h.tick(
        c2_tracks=[{"angle_deg": -90.0}],
        c3_tracks=[],
        c4_admission_allowed=True,
        now_mono=0.0,
    )
    # c2_pulse called with NORMAL mode.
    assert len(c2.calls) == 1
    mode, _, _ = c2.calls[0]
    assert mode is PulseMode.NORMAL


def test_c2_pulse_precise_when_in_exit_arc() -> None:
    c1, c2, c3 = _Recorder(), _Recorder(), _Recorder()
    h = _make(c1=c1, c2=c2, c3=c3)
    h.enable()
    h.tick(
        c2_tracks=[{"angle_deg": 10.0}],  # in C2 exit arc (±30°)
        c3_tracks=[],
        c4_admission_allowed=True,
        now_mono=0.0,
    )
    assert len(c2.calls) == 1
    mode, _, _ = c2.calls[0]
    assert mode is PulseMode.PRECISE


def test_c3_blocked_when_c4_admission_denied() -> None:
    c1, c2, c3 = _Recorder(), _Recorder(), _Recorder()
    h = _make(c1=c1, c2=c2, c3=c3)
    h.enable()
    h.tick(
        c2_tracks=[],
        c3_tracks=[{"angle_deg": -45.0}],
        c4_admission_allowed=False,
        now_mono=0.0,
    )
    assert c3.calls == []


def test_c3_blocks_c2_via_intake_when_c3_intake_full() -> None:
    c1, c2, c3 = _Recorder(), _Recorder(), _Recorder()
    h = _make(c1=c1, c2=c2, c3=c3)
    h.enable()
    h.tick(
        c2_tracks=[{"angle_deg": -90.0}],   # would otherwise pulse C2 normal
        c3_tracks=[{"angle_deg": 180.0}],   # C3 intake occupied
        c4_admission_allowed=True,
        now_mono=0.0,
    )
    # C3 pulses (its own action), but C2 does not (C3's intake is occupied).
    assert len(c3.calls) == 1
    assert c2.calls == []


def test_handler_respects_cooldowns() -> None:
    c1, c2, c3 = _Recorder(), _Recorder(), _Recorder()
    h = SectionFeederHandler(
        c1_pulse=c1,
        c2_pulse=c2,
        c3_pulse=c3,
        c1_hw=None,
        c2_hw=None,
        c3_hw=None,
        c2_geometry=_C2_GEOM,
        c3_geometry=_C3_GEOM,
        c1_cooldown_s=2.0,
    )
    h.enable()
    # First tick: C1 fires.
    h.tick(c2_tracks=[], c3_tracks=[], c4_admission_allowed=False, now_mono=0.0)
    assert len(c1.calls) == 1
    # 1 s later: cooldown still active.
    h.tick(c2_tracks=[], c3_tracks=[], c4_admission_allowed=False, now_mono=1.0)
    assert len(c1.calls) == 1
    # 2.5 s later: cooldown elapsed, C1 fires again.
    h.tick(c2_tracks=[], c3_tracks=[], c4_admission_allowed=False, now_mono=2.5)
    assert len(c1.calls) == 2


def test_handler_skips_pulse_when_hw_busy() -> None:
    c1 = _Recorder()
    c1_hw = _StubHw()
    c1_hw._busy = True
    h = _make(c1=c1, c1_hw=c1_hw)
    h.enable()
    h.tick(c2_tracks=[], c3_tracks=[], c4_admission_allowed=False, now_mono=0.0)
    assert c1.calls == []
    snap = h.snapshot()
    assert snap["counters"]["c1"]["pulse_count_skipped_busy"] == 1


def test_set_inhibit_freezes_all_pulses() -> None:
    c1, c2, c3 = _Recorder(), _Recorder(), _Recorder()
    h = _make(c1=c1, c2=c2, c3=c3)
    h.enable()
    h.set_inhibit("feed_inhibit")
    h.tick(
        c2_tracks=[{"angle_deg": 10.0}],   # would normally pulse C2 precise
        c3_tracks=[{"angle_deg": -45.0}],  # would normally pulse C3 normal
        c4_admission_allowed=True,
        now_mono=0.0,
    )
    assert c1.calls == [] and c2.calls == [] and c3.calls == []


def test_snapshot_reflects_last_decision() -> None:
    h = _make()
    h.enable()
    h.tick(
        c2_tracks=[{"angle_deg": 10.0}],
        c3_tracks=[],
        c4_admission_allowed=True,
        now_mono=0.0,
    )
    snap = h.snapshot()
    assert snap["enabled"] is True
    assert snap["last_decision"]["c2_action"] == "pulse_precise"
    assert snap["last_decision"]["c4_admission_allowed"] is True
