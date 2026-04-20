import unittest
from types import SimpleNamespace

from subsystems.channels import C3Station, FeederTickContext
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


class C3StationTests(unittest.TestCase):
    def test_precise_action_sets_precise_state(self) -> None:
        station = C3Station(
            gc=SimpleNamespace(
                logger=_Logger(),
                profiler=_Profiler(),
                runtime_stats=_RuntimeStats(),
            ),
            stepper=SimpleNamespace(),
            send_pulse=lambda *args, **kwargs: True,
            feeder_config=SimpleNamespace(
                third_rotor_precision=SimpleNamespace(),
                third_rotor_normal=SimpleNamespace(),
            ),
        )
        ctx = FeederTickContext(
            now_mono=1.0,
            detections=[],
            analysis=SimpleNamespace(ch2_dropzone_occupied=False, ch3_dropzone_occupied=False),
            ch2_action=ChannelAction.IDLE,
            ch3_action=ChannelAction.PULSE_PRECISE,
            can_run=True,
            ch3_held=False,
            classification_channel_block=False,
            classification_channel_piece_count=0,
            ch1_pulse_intent=False,
            ch2_pulse_intent=False,
            ch3_pulse_intent=True,
            ch1_stepper_busy=False,
            ch2_stepper_busy=False,
            ch3_stepper_busy=False,
            wait_stepper_busy=False,
        )

        station.step(ctx)

        self.assertEqual("feeding.pulse_ch3_precise", station.current_state)


if __name__ == "__main__":
    unittest.main()
