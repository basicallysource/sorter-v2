import unittest
from types import SimpleNamespace

from subsystems.channels import C3Station, FeederTickContext
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
        self.exit_wiggle_c3 = 0

    def observeStateTransition(self, *args, **kwargs) -> None:
        pass

    def observeBlockedReason(self, *args, **kwargs) -> None:
        pass

    def observeExitWiggleTriggered(self, channel: str, **_kwargs) -> None:
        if channel == "c3":
            self.exit_wiggle_c3 += 1


class _Stepper:
    def __init__(self) -> None:
        self.moves: list[float] = []

    def move_degrees(self, deg: float) -> bool:
        self.moves.append(float(deg))
        return True


def _make_c3_station(stats: _RuntimeStats, stepper: _Stepper) -> C3Station:
    return C3Station(
        gc=SimpleNamespace(
            logger=_Logger(),
            profiler=_Profiler(),
            runtime_stats=stats,
        ),
        stepper=SimpleNamespace(),
        send_pulse=lambda *args, **kwargs: True,
        feeder_config=SimpleNamespace(
            third_rotor_precision=SimpleNamespace(),
            third_rotor_normal=SimpleNamespace(),
        ),
        irl=SimpleNamespace(c_channel_3_rotor_stepper=stepper),
        gear_ratio=1.0,
    )


def _make_c3_wiggle_ctx(
    *,
    now_mono: float,
    ch3_exit_overlap: float,
    ch3_held: bool,
    ch3_stepper_busy: bool = False,
    pulse_sent: bool = False,
) -> FeederTickContext:
    return FeederTickContext(
        now_mono=now_mono,
        detections=[],
        analysis=SimpleNamespace(
            ch2_dropzone_occupied=False,
            ch3_dropzone_occupied=False,
            ch2_exit_overlap_max=0.0,
            ch3_exit_overlap_max=ch3_exit_overlap,
        ),
        ch2_action=ChannelAction.IDLE,
        ch3_action=ChannelAction.PULSE_PRECISE,
        can_run=True,
        ch3_held=ch3_held,
        classification_channel_block=False,
        classification_channel_piece_count=0,
        ch1_pulse_intent=False,
        ch2_pulse_intent=False,
        ch3_pulse_intent=False,
        ch1_stepper_busy=False,
        ch2_stepper_busy=False,
        ch3_stepper_busy=ch3_stepper_busy,
        wait_stepper_busy=False,
        pulse_sent=pulse_sent,
    )


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

    def test_exit_wiggle_fires_when_stalled_and_ch3_held(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        station = _make_c3_station(stats, stepper)

        ctx1 = _make_c3_wiggle_ctx(
            now_mono=0.0,
            ch3_exit_overlap=0.8,
            ch3_held=True,
        )
        station.run_exit_wiggle(ctx1)
        self.assertEqual(0, stats.exit_wiggle_c3)
        self.assertEqual([], stepper.moves)

        ctx2 = _make_c3_wiggle_ctx(
            now_mono=0.7,
            ch3_exit_overlap=0.8,
            ch3_held=True,
        )
        station.run_exit_wiggle(ctx2)
        self.assertEqual(1, stats.exit_wiggle_c3)
        self.assertEqual(2, len(stepper.moves))
        self.assertLess(stepper.moves[0], 0.0)
        self.assertGreater(stepper.moves[1], 0.0)

    def test_exit_wiggle_skipped_before_stall_elapses(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        station = _make_c3_station(stats, stepper)

        station.run_exit_wiggle(
            _make_c3_wiggle_ctx(now_mono=0.0, ch3_exit_overlap=0.8, ch3_held=True)
        )
        station.run_exit_wiggle(
            _make_c3_wiggle_ctx(now_mono=0.1, ch3_exit_overlap=0.8, ch3_held=True)
        )
        self.assertEqual(0, stats.exit_wiggle_c3)
        self.assertEqual([], stepper.moves)

    def test_exit_wiggle_skipped_when_ch3_not_held(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        station = _make_c3_station(stats, stepper)

        station.run_exit_wiggle(
            _make_c3_wiggle_ctx(now_mono=0.0, ch3_exit_overlap=0.8, ch3_held=False)
        )
        station.run_exit_wiggle(
            _make_c3_wiggle_ctx(now_mono=1.0, ch3_exit_overlap=0.8, ch3_held=False)
        )
        self.assertEqual(0, stats.exit_wiggle_c3)
        self.assertEqual([], stepper.moves)


if __name__ == "__main__":
    unittest.main()
