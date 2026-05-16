import unittest
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

import numpy as np

from defs.channel import ChannelDetection, PolygonChannel
from subsystems.feeder.analysis import analyzeFeederChannels
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
) -> ChannelDetection:
    channel = _channel()
    return ChannelDetection(
        bbox=bbox,
        channel_id=channel.channel_id,
        channel=channel,
        global_id=global_id,
        source_role="c_channel_2",
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

        blocked = analyzeFeederChannels(gc, [det])
        self.assertTrue(blocked.ch2_dropzone_occupied)

        ignored = analyzeFeederChannels(
            gc,
            [det],
            ignored_dropzone_detection_ids={(2, 123)},
        )
        self.assertFalse(ignored.ch2_dropzone_occupied)
        self.assertGreater(ignored.ch2_dropzone_overlap_max, 0.0)

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
            gc,
            [det],
            ignored_dropzone_detection_ids=manager.ignored_detection_ids(),
        )
        self.assertFalse(analysis.ch2_dropzone_occupied)

        # Same track, same channel, now on the opposite side of the wheel:
        # no longer in dropzone, so it should be removed from the ignore list.
        manager.update([_detection(bbox=(10, 48, 20, 52))], 8.3, rotating_channel_ids={2})
        self.assertNotIn((2, 123), manager.ignored_detection_ids())

    def test_wall_clock_time_without_rotation_does_not_publish_incident(self) -> None:
        stats = _RuntimeStats()
        gc = SimpleNamespace(runtime_stats=stats, logger=_Logger())
        manager = DropzoneStuckIncidentManager(gc=gc)
        det = _detection()

        manager.update([det], 0.0, rotating_channel_ids=set())
        manager.update([det], 12.0, rotating_channel_ids=set())

        self.assertIsNone(stats.active_incident)

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
