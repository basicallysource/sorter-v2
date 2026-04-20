import unittest
from types import SimpleNamespace

from subsystems.channels import C1Station, FeederTickContext
from subsystems.feeder.analysis import ChannelAction


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass


class _Profiler:
    def hit(self, *args, **kwargs) -> None:
        pass


class _RuntimeStats:
    def observeStateTransition(self, *args, **kwargs) -> None:
        pass

    def observeBlockedReason(self, *args, **kwargs) -> None:
        pass


class C1StationTests(unittest.TestCase):
    def test_dropzone_occupied_sets_wait_state(self) -> None:
        station = C1Station(
            gc=SimpleNamespace(
                logger=_Logger(),
                profiler=_Profiler(),
                runtime_stats=_RuntimeStats(),
            ),
            stepper=SimpleNamespace(),
            vision=SimpleNamespace(getFeederTracks=lambda _role: []),
            irl_config=SimpleNamespace(
                feeder_config=SimpleNamespace(
                    first_rotor_jam_timeout_s=1.0,
                    first_rotor_jam_min_pulses=1,
                    first_rotor_jam_max_cycles=3,
                )
            ),
            send_pulse=lambda *args, **kwargs: False,
            jam_recovery=SimpleNamespace(
                is_ready=lambda _now: False,
                exhausted=lambda _levels: False,
                run=lambda _cfg, _now: False,
                state_name="shake_l1",
            ),
            feeder_pause_for_ch1_stall=lambda _levels: None,
            max_ch2_pieces_for_feed=5,
            last_ch2_activity_at_ref=lambda: 0.0,
            ch1_pulses_since_ch2_activity_ref=lambda: 0,
            last_ch1_pulse_at_setter=lambda _now: None,
            ch1_pulses_since_ch2_activity_incrementer=lambda: None,
        )
        ctx = FeederTickContext(
            now_mono=1.0,
            detections=[],
            analysis=SimpleNamespace(ch2_dropzone_occupied=True, ch3_dropzone_occupied=False),
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

        station.step(ctx)

        self.assertEqual("feeding.wait_ch2_dropzone_clear", station.current_state)


if __name__ == "__main__":
    unittest.main()
