import os
import tempfile
import unittest
from unittest.mock import patch

from incident_records import incidentSummary, listIncidents, openIncident


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


class IncidentListingTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmpdir.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)

    def _open(self, count: int, kind: str = "exit_stuck") -> None:
        for _ in range(count):
            openIncident({"kind": kind})

    def test_a_listing_holds_still_while_incidents_are_raised(self) -> None:
        self._open(5)
        first = listIncidents(limit=2)
        self.assertEqual([i["id"] for i in first["items"]], [5, 4])
        self.assertEqual((first["total"], first["newer"], first["anchor"]), (5, 0, 5))

        self._open(3)  # raised while someone reads

        second = listIncidents(limit=2, cursor=int(first["next_cursor"]), anchor=first["anchor"])
        self.assertEqual([i["id"] for i in second["items"]], [3, 2])
        self.assertEqual((second["total"], second["newer"]), (5, 3))
        third = listIncidents(limit=2, cursor=int(second["next_cursor"]), anchor=first["anchor"])
        self.assertEqual([i["id"] for i in third["items"]], [1])
        self.assertIsNone(third["next_cursor"])

    def test_a_page_can_be_read_by_its_offset_and_the_counts_alone(self) -> None:
        self._open(6)
        jumped = listIncidents(limit=2, offset=2, anchor=6)
        self.assertEqual([i["id"] for i in jumped["items"]], [4, 3])
        counts = listIncidents(limit=0, anchor=4)
        self.assertEqual((counts["items"], counts["total"], counts["newer"]), ([], 4, 2))

    def test_the_filters_apply_to_the_listing_and_to_what_came_after(self) -> None:
        self._open(2, "feeder_jam")
        self._open(2, "exit_stuck")
        first = listIncidents(limit=1, kind="exit_stuck")
        self.assertEqual((first["total"], first["newer"]), (2, 0))
        self._open(1, "exit_stuck")
        self._open(1, "feeder_jam")
        again = listIncidents(limit=1, kind="exit_stuck", anchor=first["anchor"])
        self.assertEqual((again["total"], again["newer"]), (2, 1))


if __name__ == "__main__":
    unittest.main()
