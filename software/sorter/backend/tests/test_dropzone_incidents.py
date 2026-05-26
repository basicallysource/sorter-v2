import unittest
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

import numpy as np

from defs.channel import ChannelDetection, PolygonChannel
from subsystems.feeder.analysis import ChannelAction, analyzeFeederChannels, bboxSectionOverlapRatio
from subsystems.feeder.dropzone_incidents import DropzoneStuckIncidentManager
from toml_config import setDashboardConfig


class _RuntimeStats:
    def __init__(self) -> None:
        self.active_incident: dict | None = None

    def setActiveIncident(self, incident: dict) -> None:
        self.active_incident = dict(incident)

    def activeIncident(self):
        return dict(self.active_incident) if self.active_incident else None

    def clearActiveIncident(self, **_kwargs) -> None:
        self.active_incident = None


class _Logger:
    def warning(self, *_args, **_kwargs) -> None:
        pass


def _channel() -> PolygonChannel:
    return PolygonChannel(
        channel_id=2,
        polygon=np.array([[0, 0], [100, 0], [100, 100], [0, 100]], dtype=np.int32),
        center=(50.0, 50.0),
        radius1_angle_image=0.0,
        mask=np.ones((100, 100), dtype=np.uint8),
        dropzone_sections={0, 1, 2, 3, 356, 357, 358, 359},
        exit_sections=set(),
    )


def _detection(
    *,
    bbox: tuple[int, int, int, int] = (80, 48, 90, 52),
    global_id: int = 123,
    channel_id: int = 2,
) -> ChannelDetection:
    channel = _channel()
    channel.channel_id = int(channel_id)
    return ChannelDetection(
        bbox=bbox,
        channel_id=channel.channel_id,
        channel=channel,
        global_id=global_id,
        source_role="carousel" if channel.channel_id == 4 else "c_channel_2",
    )


def _exit_detection(*, motion_confirmed: bool) -> ChannelDetection:
    channel = PolygonChannel(
        channel_id=2,
        polygon=np.array([[0, 0], [100, 0], [100, 100], [0, 100]], dtype=np.int32),
        center=(50.0, 50.0),
        radius1_angle_image=0.0,
        mask=np.ones((100, 100), dtype=np.uint8),
        dropzone_sections=set(),
        exit_sections={0},
    )
    return ChannelDetection(
        bbox=(80, 48, 90, 52),
        channel_id=channel.channel_id,
        channel=channel,
        global_id=456,
        source_role="c_channel_2",
        motion_confirmed=motion_confirmed,
    )


class DropzoneIncidentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.machine_params_path = Path(self._tmpdir.name) / "machine_params.toml"
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.machine_params_path)

    def tearDown(self) -> None:
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params
        self._tmpdir.cleanup()

    def test_analyzer_ignores_acknowledged_dropzone_track_for_backpressure(self) -> None:
        gc = SimpleNamespace()
        det = _detection()

        blocked = analyzeFeederChannels([det])
        self.assertTrue(blocked.ch2_dropzone_occupied)

        ignored = analyzeFeederChannels(
            [det],
            ignored_dropzone_detection_ids={(2, 123)},
        )
        self.assertFalse(ignored.ch2_dropzone_occupied)
        self.assertGreater(ignored.ch2_dropzone_overlap_max, 0.0)

    def test_analyzer_ignores_unconfirmed_tracker_hits_for_exit_signal(self) -> None:
        gc = SimpleNamespace()

        unconfirmed = analyzeFeederChannels(
            [_exit_detection(motion_confirmed=False)],
        )
        self.assertEqual(0.0, unconfirmed.ch2_exit_overlap_max)
        self.assertFalse(unconfirmed.ch2_exit_center_crossed)
        self.assertEqual(ChannelAction.PULSE_NORMAL, unconfirmed.ch2_action)

        confirmed = analyzeFeederChannels(
            [_exit_detection(motion_confirmed=True)],
        )
        self.assertGreater(confirmed.ch2_exit_overlap_max, 0.0)
        self.assertTrue(confirmed.ch2_exit_center_crossed)
        self.assertEqual(ChannelAction.PULSE_PRECISE, confirmed.ch2_action)

    def test_stuck_dropzone_track_counts_accumulated_motion_then_acknowledges(self) -> None:
        stats = _RuntimeStats()
        gc = SimpleNamespace(runtime_stats=stats, logger=_Logger())
        manager = DropzoneStuckIncidentManager(gc=gc)
        det = _detection()

        self.assertFalse(manager.update([det], 0.0, rotating_channel_ids={2}))
        self.assertIsNone(stats.active_incident)

        self.assertFalse(manager.update([det], 2.0, rotating_channel_ids={2}))
        self.assertIsNone(stats.active_incident)

        # Paused time does not count against the piece.
        self.assertFalse(manager.update([det], 4.0, rotating_channel_ids=set()))
        self.assertFalse(manager.update([det], 5.0, rotating_channel_ids={2}))
        self.assertIsNone(stats.active_incident)

        self.assertTrue(manager.update([det], 8.0, rotating_channel_ids={2}))
        self.assertEqual("channel_dropzone_stuck", stats.active_incident["kind"])
        self.assertEqual("c2", stats.active_incident["channel"])
        self.assertEqual(123, stats.active_incident["global_id"])
        self.assertEqual(5000, stats.active_incident["accumulated_motion_ms"])

        result = manager.acknowledge_active_incident(stats.active_incident, 8.1)
        self.assertTrue(result["ignored_until_dropzone_clear"])
        self.assertIsNone(stats.active_incident)
        self.assertIn((2, 123), manager.ignored_detection_ids())

        manager.update([det], 8.2, rotating_channel_ids={2})
        analysis = analyzeFeederChannels(
            [det],
            ignored_dropzone_detection_ids=manager.ignored_detection_ids(),
        )
        self.assertFalse(analysis.ch2_dropzone_occupied)

        # Same track, same channel, now on the opposite side of the wheel:
        # no longer in dropzone, so it should be removed from the ignore list.
        manager.update([_detection(bbox=(10, 48, 20, 52))], 8.3, rotating_channel_ids={2})
        self.assertNotIn((2, 123), manager.ignored_detection_ids())

    def test_c4_dropzone_track_can_publish_same_incident(self) -> None:
        stats = _RuntimeStats()
        gc = SimpleNamespace(runtime_stats=stats, logger=_Logger())
        manager = DropzoneStuckIncidentManager(gc=gc)
        det = _detection(channel_id=4, global_id=6254)

        manager.update([det], 0.0, rotating_channel_ids={4})
        published = manager.update([det], 5.0, rotating_channel_ids={4})

        self.assertTrue(published)
        self.assertEqual("channel_dropzone_stuck", stats.active_incident["kind"])
        self.assertEqual("c4", stats.active_incident["channel"])
        self.assertEqual("carousel", stats.active_incident["role"])
        self.assertEqual(6254, stats.active_incident["global_id"])

    def test_c4_automatic_ignore_notifies_callback_until_track_leaves(self) -> None:
        setDashboardConfig({"incident_handling": {"channel_dropzone_stuck": "automatic"}})
        stats = _RuntimeStats()
        changes: list[tuple[int, int, bool]] = []
        gc = SimpleNamespace(runtime_stats=stats, logger=_Logger())
        manager = DropzoneStuckIncidentManager(
            gc=gc,
            on_ignored_change=lambda channel_id, global_id, ignored: changes.append(
                (channel_id, global_id, ignored)
            ),
        )
        det = _detection(channel_id=4, global_id=6254)

        manager.update([det], 0.0, rotating_channel_ids={4})
        self.assertFalse(manager.update([det], 5.0, rotating_channel_ids={4}))
        self.assertIn((4, 6254), manager.ignored_detection_ids())
        self.assertEqual((4, 6254, True), changes[-1])

        manager.update([_detection(channel_id=4, global_id=6254, bbox=(10, 48, 20, 52))], 5.1, rotating_channel_ids={4})

        self.assertNotIn((4, 6254), manager.ignored_detection_ids())
        self.assertEqual((4, 6254, False), changes[-1])

    def test_wall_clock_time_without_rotation_does_not_publish_incident(self) -> None:
        stats = _RuntimeStats()
        gc = SimpleNamespace(runtime_stats=stats, logger=_Logger())
        manager = DropzoneStuckIncidentManager(gc=gc)
        det = _detection()

        manager.update([det], 0.0, rotating_channel_ids=set())
        manager.update([det], 12.0, rotating_channel_ids=set())

        self.assertIsNone(stats.active_incident)

    def test_blocking_dropzone_edge_track_can_become_incident(self) -> None:
        stats = _RuntimeStats()
        gc = SimpleNamespace(runtime_stats=stats, logger=_Logger())
        manager = DropzoneStuckIncidentManager(gc=gc)
        det = _detection(bbox=(70, 20, 90, 80))

        self.assertLess(
            bboxSectionOverlapRatio(det.bbox, det.channel, det.channel.dropzone_sections),
            2.0 / 3.0,
        )
        self.assertFalse(manager.update([det], 0.0, rotating_channel_ids={2}))
        published = manager.update([det], 5.0, rotating_channel_ids={2})

        self.assertTrue(published)
        self.assertEqual("channel_dropzone_stuck", stats.active_incident["kind"])
        self.assertEqual("c2", stats.active_incident["channel"])

    def test_commanded_pulse_motion_counts_even_between_ticks(self) -> None:
        stats = _RuntimeStats()
        gc = SimpleNamespace(runtime_stats=stats, logger=_Logger())
        manager = DropzoneStuckIncidentManager(gc=gc)
        det = _detection(channel_id=3, global_id=555)

        self.assertFalse(manager.update([det], 0.0, rotating_channel_ids=set()))
        for index in range(4):
            manager.note_channel_motion(3, 1.25)
            published = manager.update([det], float(index + 1), rotating_channel_ids=set())

        self.assertTrue(published)
        self.assertEqual("channel_dropzone_stuck", stats.active_incident["kind"])
        self.assertEqual("c3", stats.active_incident["channel"])
        self.assertEqual(555, stats.active_incident["global_id"])
        self.assertEqual(5000, stats.active_incident["accumulated_motion_ms"])

    def test_automatic_policy_ignores_stuck_track_without_active_incident(self) -> None:
        setDashboardConfig({"incident_handling": {"channel_dropzone_stuck": "automatic"}})
        stats = _RuntimeStats()
        gc = SimpleNamespace(runtime_stats=stats, logger=_Logger())
        manager = DropzoneStuckIncidentManager(gc=gc)
        det = _detection()

        manager.update([det], 0.0, rotating_channel_ids={2})
        published = manager.update([det], 5.0, rotating_channel_ids={2})

        self.assertFalse(published)
        self.assertIsNone(stats.active_incident)
        self.assertIn((2, 123), manager.ignored_detection_ids())

    def test_off_policy_does_not_publish_or_ignore_stuck_track(self) -> None:
        setDashboardConfig({"incident_handling": {"channel_dropzone_stuck": "off"}})
        stats = _RuntimeStats()
        gc = SimpleNamespace(runtime_stats=stats, logger=_Logger())
        manager = DropzoneStuckIncidentManager(gc=gc)
        det = _detection()

        manager.update([det], 0.0, rotating_channel_ids={2})
        published = manager.update([det], 5.0, rotating_channel_ids={2})

        self.assertFalse(published)
        self.assertIsNone(stats.active_incident)
        self.assertNotIn((2, 123), manager.ignored_detection_ids())

    def test_manual_clear_does_not_ignore_track(self) -> None:
        stats = _RuntimeStats()
        gc = SimpleNamespace(runtime_stats=stats, logger=_Logger())
        manager = DropzoneStuckIncidentManager(gc=gc)
        det = _detection()

        manager.update([det], 0.0, rotating_channel_ids={2})
        manager.update([det], 5.0, rotating_channel_ids={2})
        result = manager.clear_active_incident(stats.active_incident)

        self.assertTrue(result["cleared"])
        self.assertIsNone(stats.active_incident)
        self.assertNotIn((2, 123), manager.ignored_detection_ids())


if __name__ == "__main__":
    unittest.main()
