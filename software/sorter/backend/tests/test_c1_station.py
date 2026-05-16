import unittest
from types import SimpleNamespace
from unittest.mock import patch

from subsystems.channels import C1Station, FeederTickContext
from subsystems.feeder.analysis import ChannelAction


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass


class _Profiler:
    def hit(self, *args, **kwargs) -> None:
        pass


class _RuntimeStats:
    def __init__(self) -> None:
        self.active_incident = None
        self.blocked_reasons: list[tuple[str, str]] = []

    def observeStateTransition(self, *args, **kwargs) -> None:
        pass

    def observeBlockedReason(self, machine: str, reason: str) -> None:
        self.blocked_reasons.append((machine, reason))

    def setActiveIncident(self, incident: dict) -> None:
        self.active_incident = dict(incident)

    def activeIncident(self):
        return dict(self.active_incident) if self.active_incident else None


class _JamRecovery:
    def __init__(self, *, ready: bool = False, exhausted: bool = False) -> None:
        self.ready = ready
        self.exhausted_value = exhausted
        self.run_calls = 0
        self.state_name = "shake_l1"

    def is_ready(self, _now: float) -> bool:
        return self.ready

    def exhausted(self, _levels: int) -> bool:
        return self.exhausted_value

    def run(self, _cfg, _now: float) -> bool:
        self.run_calls += 1
        return True


def _make_station(
    *,
    stats: _RuntimeStats | None = None,
    jam_recovery: _JamRecovery | None = None,
    last_ch2_activity_at_ref=lambda: 0.0,
    ch1_pulses_since_ch2_activity_ref=lambda: 0,
    send_pulse=lambda *args, **kwargs: False,
) -> C1Station:
    return C1Station(
        gc=SimpleNamespace(
            logger=_Logger(),
            profiler=_Profiler(),
            runtime_stats=stats or _RuntimeStats(),
        ),
        stepper=SimpleNamespace(),
        vision=SimpleNamespace(getFeederTracks=lambda _role: []),
        irl_config=SimpleNamespace(
            feeder_config=SimpleNamespace(
                first_rotor=SimpleNamespace(),
                first_rotor_jam_timeout_s=1.0,
                first_rotor_jam_min_pulses=2,
                first_rotor_jam_max_cycles=3,
            )
        ),
        send_pulse=send_pulse,
        jam_recovery=jam_recovery or _JamRecovery(),
        feeder_pause_for_ch1_stall=lambda _levels: None,
        max_ch2_pieces_for_feed=5,
        last_ch2_activity_at_ref=last_ch2_activity_at_ref,
        ch1_pulses_since_ch2_activity_ref=ch1_pulses_since_ch2_activity_ref,
        last_ch1_pulse_at_setter=lambda _now: None,
        ch1_pulses_since_ch2_activity_incrementer=lambda: None,
    )


def _make_ctx(*, now_mono: float, ch2_dropzone_occupied: bool = False, ch3_dropzone_occupied: bool = False) -> FeederTickContext:
    return FeederTickContext(
        now_mono=now_mono,
        detections=[],
        analysis=SimpleNamespace(
            ch2_dropzone_occupied=ch2_dropzone_occupied,
            ch3_dropzone_occupied=ch3_dropzone_occupied,
        ),
        ch2_action=ChannelAction.IDLE,
        ch3_action=ChannelAction.IDLE,
        can_run=True,
        ch3_held=False,
        classification_channel_block=False,
        classification_channel_piece_count=0,
        ch1_pulse_intent=False,
        ch2_pulse_intent=False,
        ch3_pulse_intent=False,
        ch1_stepper_busy=False,
        ch2_stepper_busy=False,
        ch3_stepper_busy=False,
        wait_stepper_busy=False,
    )


class C1StationTests(unittest.TestCase):
    def test_dropzone_occupied_sets_wait_state(self) -> None:
        station = _make_station()
        ctx = _make_ctx(now_mono=1.0, ch2_dropzone_occupied=True)

        station.step(ctx)

        self.assertEqual("feeding.wait_ch2_dropzone_clear", station.current_state)

    def test_bulk_feeder_stall_publishes_incident_instead_of_hidden_recovery(self) -> None:
        stats = _RuntimeStats()
        jam_recovery = _JamRecovery(ready=True)
        station = _make_station(
            stats=stats,
            jam_recovery=jam_recovery,
            last_ch2_activity_at_ref=lambda: 0.0,
            ch1_pulses_since_ch2_activity_ref=lambda: 3,
        )
        ctx = _make_ctx(now_mono=2.5)

        with patch("subsystems.channels.base._incident_handling_off", return_value=False):
            station.step(ctx)

        self.assertEqual("bulk_feeder_stalled", stats.active_incident["kind"])
        self.assertEqual("c1", stats.active_incident["channel"])
        self.assertEqual(2500, stats.active_incident["stalled_ms"])
        self.assertEqual(3, stats.active_incident["pulses_since_activity"])
        self.assertEqual("feeding.wait_bulk_feeder_stalled_incident", station.current_state)
        self.assertTrue(ctx.abort_tick)
        self.assertEqual(0, jam_recovery.run_calls)


if __name__ == "__main__":
    unittest.main()
