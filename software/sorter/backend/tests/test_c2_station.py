import unittest
from types import SimpleNamespace

from subsystems.channels import C2Station, FeederTickContext
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
    def observeStateTransition(self, *args, **kwargs) -> None:
        pass

    def observeBlockedReason(self, *args, **kwargs) -> None:
        pass


class C2StationTests(unittest.TestCase):
    def test_ch3_dropzone_block_sets_wait_state(self) -> None:
        station = C2Station(
            gc=SimpleNamespace(
                logger=_Logger(),
                profiler=_Profiler(),
                runtime_stats=_RuntimeStats(),
            ),
            stepper=SimpleNamespace(),
            irl=SimpleNamespace(c_channel_2_rotor_stepper=SimpleNamespace(move_degrees=lambda *_args: None)),
            send_pulse=lambda *args, **kwargs: False,
            feeder_config=SimpleNamespace(
                second_rotor_precision=SimpleNamespace(),
                second_rotor_normal=SimpleNamespace(),
            ),
            separation_driver=SimpleNamespace(active=False, step=lambda *_args: None, cancel=lambda *_args: None),
            gear_ratio=1.0,
            agitation_enabled=False,
            agitation_reverse_deg_output=45.0,
            agitation_forward_deg_output=30.0,
            agitation_min_interval_s=2.0,
            agitation_recent_ch1_window_s=10.0,
        )
        ctx = FeederTickContext(
            now_mono=1.0,
            detections=[],
            analysis=SimpleNamespace(ch2_dropzone_occupied=False, ch3_dropzone_occupied=True),
            ch2_action=ChannelAction.PULSE_NORMAL,
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

        self.assertEqual("feeding.wait_ch3_dropzone_clear", station.current_state)


if __name__ == "__main__":
    unittest.main()
