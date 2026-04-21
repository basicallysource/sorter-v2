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
    def __init__(self) -> None:
        self.exit_wiggle_c2 = 0
        self.exit_wiggle_c3 = 0
        self.c2_idle_skipped_no_cluster = 0

    def observeStateTransition(self, *args, **kwargs) -> None:
        pass

    def observeBlockedReason(self, *args, **kwargs) -> None:
        pass

    def observeExitWiggleTriggered(self, channel: str, **_kwargs) -> None:
        if channel == "c2":
            self.exit_wiggle_c2 += 1
        elif channel == "c3":
            self.exit_wiggle_c3 += 1

    def observeC2IdleSkippedNoCluster(self, **_kwargs) -> None:
        self.c2_idle_skipped_no_cluster += 1


class _Stepper:
    def __init__(self) -> None:
        self.moves: list[float] = []

    def move_degrees(self, deg: float) -> bool:
        self.moves.append(float(deg))
        return True


def _make_station(
    stats: _RuntimeStats,
    stepper: _Stepper,
    *,
    agitation_enabled: bool = False,
) -> C2Station:
    return C2Station(
        gc=SimpleNamespace(
            logger=_Logger(),
            profiler=_Profiler(),
            runtime_stats=stats,
        ),
        stepper=SimpleNamespace(),
        irl=SimpleNamespace(c_channel_2_rotor_stepper=stepper),
        send_pulse=lambda *args, **kwargs: False,
        feeder_config=SimpleNamespace(
            second_rotor_precision=SimpleNamespace(),
            second_rotor_normal=SimpleNamespace(),
        ),
        separation_driver=SimpleNamespace(active=False, step=lambda *_args: None, cancel=lambda *_args: None),
        gear_ratio=1.0,
        agitation_enabled=agitation_enabled,
        agitation_reverse_deg_output=45.0,
        agitation_forward_deg_output=30.0,
        agitation_min_interval_s=2.0,
        agitation_recent_ch1_window_s=10.0,
    )


def _fake_c2_channel():
    """Minimal PolygonChannel-shaped stub for _c2HasCluster.

    ``_c2HasCluster`` only reads ``center`` and ``radius1_angle_image``, so we
    can build a SimpleNamespace rather than a full PolygonChannel.
    """
    return SimpleNamespace(center=(0.0, 0.0), radius1_angle_image=0.0)


def _c2_detection(angle_deg: float, radius: float = 100.0):
    """Return a ChannelDetection-shaped stub whose bbox-center sits at
    ``angle_deg`` relative to the fake C2 channel center.
    """
    import math as _math

    channel = _fake_c2_channel()
    rad = _math.radians(angle_deg)
    cx = _math.cos(rad) * radius
    cy = _math.sin(rad) * radius
    # 2x2 bbox centered on (cx, cy).
    bbox = (int(cx) - 1, int(cy) - 1, int(cx) + 1, int(cy) + 1)
    return SimpleNamespace(bbox=bbox, channel_id=2, channel=channel)


def _make_idle_ctx(*, detections: list, now_mono: float = 1.0) -> FeederTickContext:
    return FeederTickContext(
        now_mono=now_mono,
        detections=detections,
        analysis=SimpleNamespace(
            ch2_dropzone_occupied=False,
            ch3_dropzone_occupied=False,
            ch2_exit_overlap_max=0.0,
            ch3_exit_overlap_max=0.0,
        ),
        ch2_action=ChannelAction.IDLE,
        ch3_action=ChannelAction.PULSE_NORMAL,  # force ch3 "busy-ish" branch
        can_run=True,
        ch3_held=True,
        classification_channel_block=False,
        classification_channel_piece_count=0,
        ch1_pulse_intent=False,
        ch2_pulse_intent=False,
        ch3_pulse_intent=False,
        ch1_stepper_busy=False,
        ch2_stepper_busy=False,
        ch3_stepper_busy=False,
        wait_stepper_busy=False,
        pulse_sent=False,
    )


def _make_wiggle_ctx(
    *,
    now_mono: float,
    ch2_exit_overlap: float,
    ch3_dropzone_occupied: bool,
    ch2_stepper_busy: bool = False,
    pulse_sent: bool = False,
) -> FeederTickContext:
    return FeederTickContext(
        now_mono=now_mono,
        detections=[],
        analysis=SimpleNamespace(
            ch2_dropzone_occupied=False,
            ch3_dropzone_occupied=ch3_dropzone_occupied,
            ch2_exit_overlap_max=ch2_exit_overlap,
            ch3_exit_overlap_max=0.0,
        ),
        ch2_action=ChannelAction.PULSE_PRECISE,
        ch3_action=ChannelAction.IDLE,
        can_run=True,
        ch3_held=False,
        classification_channel_block=False,
        classification_channel_piece_count=0,
        ch1_pulse_intent=False,
        ch2_pulse_intent=False,
        ch3_pulse_intent=False,
        ch1_stepper_busy=False,
        ch2_stepper_busy=ch2_stepper_busy,
        ch3_stepper_busy=False,
        wait_stepper_busy=False,
        pulse_sent=pulse_sent,
    )


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

    def test_exit_wiggle_fires_when_stalled_and_downstream_blocked(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        station = _make_station(stats, stepper)

        # First tick: piece overlaps exit >= threshold, stall-timer starts.
        ctx1 = _make_wiggle_ctx(
            now_mono=0.0,
            ch2_exit_overlap=0.8,
            ch3_dropzone_occupied=True,
        )
        station.run_exit_wiggle(ctx1)
        self.assertEqual(0, stats.exit_wiggle_c2, "should not fire on first tick")
        self.assertEqual([], stepper.moves)

        # Later tick: still stuck, 700 ms later (>=600 ms stall), wiggle fires.
        ctx2 = _make_wiggle_ctx(
            now_mono=0.7,
            ch2_exit_overlap=0.8,
            ch3_dropzone_occupied=True,
        )
        station.run_exit_wiggle(ctx2)
        self.assertEqual(1, stats.exit_wiggle_c2)
        self.assertEqual(2, len(stepper.moves), "reverse then forward jog")
        self.assertLess(stepper.moves[0], 0.0)
        self.assertGreater(stepper.moves[1], 0.0)

    def test_exit_wiggle_skipped_before_stall_elapses(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        station = _make_station(stats, stepper)

        ctx1 = _make_wiggle_ctx(
            now_mono=0.0,
            ch2_exit_overlap=0.8,
            ch3_dropzone_occupied=True,
        )
        station.run_exit_wiggle(ctx1)
        # Only 100 ms later — below stall threshold.
        ctx2 = _make_wiggle_ctx(
            now_mono=0.1,
            ch2_exit_overlap=0.8,
            ch3_dropzone_occupied=True,
        )
        station.run_exit_wiggle(ctx2)
        self.assertEqual(0, stats.exit_wiggle_c2)
        self.assertEqual([], stepper.moves)

    def test_exit_wiggle_skipped_when_downstream_open(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        station = _make_station(stats, stepper)

        ctx1 = _make_wiggle_ctx(
            now_mono=0.0,
            ch2_exit_overlap=0.8,
            ch3_dropzone_occupied=False,
        )
        station.run_exit_wiggle(ctx1)
        ctx2 = _make_wiggle_ctx(
            now_mono=1.0,
            ch2_exit_overlap=0.8,
            ch3_dropzone_occupied=False,
        )
        station.run_exit_wiggle(ctx2)
        self.assertEqual(0, stats.exit_wiggle_c2)
        self.assertEqual([], stepper.moves)


class C2IdleClusterGateTests(unittest.TestCase):
    def _run(self, detections: list) -> tuple[_RuntimeStats, _Stepper]:
        stats = _RuntimeStats()
        stepper = _Stepper()
        station = _make_station(stats, stepper, agitation_enabled=True)
        # Ensure the ch1-recent-pulse window is satisfied so the jog gate is
        # otherwise open — everything except the cluster check is true.
        station.bind_last_ch1_pulse_at(lambda: 1.0)
        ctx = _make_idle_ctx(detections=detections, now_mono=1.0)
        station.run_idle_strategies(ctx)
        return stats, stepper

    def test_no_tracks_skips_idle_jog(self) -> None:
        stats, stepper = self._run(detections=[])
        self.assertEqual([], stepper.moves)
        self.assertEqual(1, stats.c2_idle_skipped_no_cluster)

    def test_single_track_skips_idle_jog(self) -> None:
        stats, stepper = self._run(detections=[_c2_detection(angle_deg=90.0)])
        self.assertEqual([], stepper.moves)
        self.assertEqual(1, stats.c2_idle_skipped_no_cluster)

    def test_two_tracks_far_apart_skip_idle_jog(self) -> None:
        stats, stepper = self._run(
            detections=[
                _c2_detection(angle_deg=20.0),
                _c2_detection(angle_deg=200.0),
            ]
        )
        self.assertEqual([], stepper.moves)
        self.assertEqual(1, stats.c2_idle_skipped_no_cluster)

    def test_two_tracks_within_cluster_gap_trigger_idle_jog(self) -> None:
        stats, stepper = self._run(
            detections=[
                _c2_detection(angle_deg=40.0),
                _c2_detection(angle_deg=45.0),
            ]
        )
        # Reverse then forward jog — same pattern as exit-wiggle.
        self.assertEqual(2, len(stepper.moves))
        self.assertLess(stepper.moves[0], 0.0)
        self.assertGreater(stepper.moves[1], 0.0)
        self.assertEqual(0, stats.c2_idle_skipped_no_cluster)


if __name__ == "__main__":
    unittest.main()
