import unittest
from unittest.mock import patch
from types import SimpleNamespace

from subsystems.channels import C2Station, FeederTickContext
from subsystems.channels.base import EXIT_WIGGLE_OVERLAP_THRESHOLD
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
        self.active_incident = None

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

    def setActiveIncident(self, incident: dict) -> None:
        self.active_incident = dict(incident)

    def activeIncident(self):
        return dict(self.active_incident) if self.active_incident else None


class _Stepper:
    def __init__(self) -> None:
        self.moves: list[float] = []

    def move_degrees(self, deg: float) -> bool:
        self.moves.append(float(deg))
        return True


class _SeparationDriver:
    def __init__(self, *, active: bool = False) -> None:
        self.active = active
        self.step_calls: list[tuple[float, bool]] = []
        self.cancel_reasons: list[str] = []

    def step(self, now_mono: float, allowed: bool) -> None:
        self.step_calls.append((float(now_mono), bool(allowed)))

    def cancel(self, reason: str) -> None:
        if not self.active:
            return
        self.cancel_reasons.append(str(reason))
        self.active = False


def _make_station(
    stats: _RuntimeStats,
    stepper: _Stepper,
    *,
    agitation_enabled: bool = False,
    separation_driver: _SeparationDriver | None = None,
    separation_incident_enabled: bool = False,
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
        separation_driver=separation_driver or _SeparationDriver(),
        gear_ratio=1.0,
        agitation_enabled=agitation_enabled,
        agitation_reverse_deg_output=45.0,
        agitation_forward_deg_output=30.0,
        agitation_min_interval_s=2.0,
        agitation_recent_ch1_window_s=10.0,
        separation_incident_enabled=separation_incident_enabled,
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

    def test_exit_incident_published_when_stalled_and_downstream_blocked(self) -> None:
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
        self.assertIsNone(stats.active_incident, "should not fire on first tick")
        self.assertEqual([], stepper.moves)

        # Later tick: still stuck, 1100 ms later (>=1000 ms stall), incident publishes.
        ctx2 = _make_wiggle_ctx(
            now_mono=1.1,
            ch2_exit_overlap=0.8,
            ch3_dropzone_occupied=True,
        )
        station.run_exit_wiggle(ctx2)
        self.assertEqual("exit_stuck", stats.active_incident["kind"])
        self.assertEqual("channel_exit_stuck", stats.active_incident["source_kind"])
        self.assertEqual("c2", stats.active_incident["channel"])
        self.assertGreaterEqual(
            stats.active_incident["overlap_ratio"],
            EXIT_WIGGLE_OVERLAP_THRESHOLD,
        )
        self.assertEqual([], stepper.moves)

    def test_exit_incident_waits_until_bbox_is_four_fifths_inside_exit(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        station = _make_station(stats, stepper)

        station.run_exit_wiggle(
            _make_wiggle_ctx(
                now_mono=0.0,
                ch2_exit_overlap=0.75,
                ch3_dropzone_occupied=True,
            )
        )
        station.run_exit_wiggle(
            _make_wiggle_ctx(
                now_mono=1.2,
                ch2_exit_overlap=0.75,
                ch3_dropzone_occupied=True,
            )
        )

        self.assertIsNone(stats.active_incident)
        self.assertEqual([], stepper.moves)

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
        self.assertIsNone(stats.active_incident)
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
        self.assertIsNone(stats.active_incident)
        self.assertEqual([], stepper.moves)

    def test_sample_collection_mode_skips_exit_wiggle(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        station = _make_station(stats, stepper)

        ctx1 = _make_wiggle_ctx(
            now_mono=0.0,
            ch2_exit_overlap=0.8,
            ch3_dropzone_occupied=True,
        )
        ctx1.sample_collection_mode = True
        station.run_exit_wiggle(ctx1)
        ctx2 = _make_wiggle_ctx(
            now_mono=1.0,
            ch2_exit_overlap=0.8,
            ch3_dropzone_occupied=True,
        )
        ctx2.sample_collection_mode = True
        station.run_exit_wiggle(ctx2)

        self.assertIsNone(stats.active_incident)
        self.assertEqual([], stepper.moves)

    def test_sample_collection_mode_cancels_idle_separation(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        separation = _SeparationDriver(active=True)
        station = _make_station(stats, stepper, separation_driver=separation)
        ctx = _make_idle_ctx(
            detections=[_c2_detection(angle_deg=40.0), _c2_detection(angle_deg=45.0)],
            now_mono=1.0,
        )
        ctx.ch2_action = ChannelAction.PULSE_NORMAL
        ctx.sample_collection_mode = True

        station.run_idle_strategies(ctx)

        self.assertEqual(["sample collection mode"], separation.cancel_reasons)
        self.assertEqual([], separation.step_calls)

    def test_c2_slipstick_separation_is_disabled_by_default(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        separation = _SeparationDriver(active=False)
        station = _make_station(stats, stepper, separation_driver=separation)
        ctx = _make_idle_ctx(detections=[_c2_detection(angle_deg=90.0)], now_mono=1.0)
        ctx.ch2_action = ChannelAction.PULSE_NORMAL

        station.run_idle_strategies(ctx)

        self.assertEqual([], separation.step_calls)
        self.assertEqual([], separation.cancel_reasons)
        self.assertIsNone(stats.active_incident)

    def test_disabled_c2_slipstick_cancels_active_driver(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        separation = _SeparationDriver(active=True)
        station = _make_station(stats, stepper, separation_driver=separation)
        ctx = _make_idle_ctx(detections=[_c2_detection(angle_deg=90.0)], now_mono=1.0)
        ctx.ch2_action = ChannelAction.PULSE_NORMAL

        station.run_idle_strategies(ctx)

        self.assertEqual(["c2 separation incident disabled"], separation.cancel_reasons)
        self.assertEqual([], separation.step_calls)
        self.assertFalse(separation.active)

    def test_enabled_c2_slipstick_publishes_incident_instead_of_running_driver(self) -> None:
        stats = _RuntimeStats()
        stepper = _Stepper()
        separation = _SeparationDriver(active=False)
        station = _make_station(
            stats,
            stepper,
            separation_driver=separation,
            separation_incident_enabled=True,
        )
        ctx = _make_idle_ctx(detections=[_c2_detection(angle_deg=90.0)], now_mono=1.0)
        ctx.ch2_action = ChannelAction.PULSE_NORMAL

        with patch("subsystems.channels.base._incident_handling_off", return_value=False):
            station.run_idle_strategies(ctx)

        self.assertEqual([], separation.step_calls)
        self.assertEqual("c2_separation_needed", stats.active_incident["kind"])
        self.assertEqual("c2", stats.active_incident["channel"])
        self.assertFalse(stats.active_incident["automated_motion_enabled"])


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
