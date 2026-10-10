import os
import tempfile
import unittest
from unittest.mock import patch

from incident_records import incidentSummary, openIncident


class IncidentSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmpdir.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)

    def test_by_channel_lists_each_shown_channel_once(self) -> None:
        openIncident({"kind": "feeder_jam", "channel": "c3", "channel_label": "C3"})
        openIncident({"kind": "feeder_jam", "channel": "c3", "channel_label": "C3"})
        openIncident({"kind": "piece_held", "channel": "C3"})
        openIncident({"kind": "feeder_jam"})

        by_channel = incidentSummary()["by_channel"]

        self.assertEqual(by_channel, [{"channel": "C3", "count": 3}, {"channel": "unknown", "count": 1}])


if __name__ == "__main__":
    unittest.main()
