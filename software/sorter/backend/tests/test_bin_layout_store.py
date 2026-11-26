import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bin_layout_store
import local_state
from bin_layout_store import count_bin_layouts, get_bin_layout, set_bin_categories, set_bin_layout
from server import shared_state


class BinLayoutStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.tmp = tmpdir.name
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmpdir.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)

    def test_writing_a_bin_layout_stamps_servo_channels_and_keeps_a_preset(self) -> None:
        set_bin_layout({"layers": [{"sections": [["small"]], "servo_channel_id": 3}, {"sections": [["small"]]}]})
        self.assertEqual([3, 1], [layer["servo_channel_id"] for layer in get_bin_layout()["layers"]])
        self.assertEqual(1, count_bin_layouts())

    def test_every_layout_the_machine_runs_is_kept_with_its_category_names(self) -> None:
        profile = os.path.join(self.tmp, "active_sorting_profile.json")
        with open(profile, "w") as handle:
            json.dump({"categories": {"bl_5": {"name": "Brick"}, "bl_26": {"name": "Plate"}}, "program": {}}, handle)
        local_state.set_sorting_profile_sync_state({"profile_id": "p1", "profile_name": "Bulk", "version_number": 2})
        with patch.object(shared_state, "gc_ref", SimpleNamespace(sorting_profile_path=profile)):
            set_bin_layout({"layers": [{"sections": [["small", "small"]]}]})
            set_bin_categories([[[["bl_5"], []]]])
            # A write that changes nothing adds no row.
            set_bin_categories([[[["bl_5"], []]]])
            set_bin_categories([[[["bl_5"], ["bl_26", "misc"]]]])

        rows = bin_layout_store.listHistoryAfter(0, 10)
        self.assertEqual([1, 2, 3], [row["id"] for row in rows])
        self.assertEqual(3, bin_layout_store.maxHistoryId())
        last = rows[-1]["layout"]
        self.assertEqual([[[["bl_5"], ["bl_26", "misc"]]]], last["bin_categories"])
        self.assertEqual({"bl_26": "Plate", "bl_5": "Brick"}, last["category_names"])
        self.assertEqual("Bulk", last["profile"]["profile_name"])
        self.assertEqual([["small", "small"]], last["layers"][0]["sections"])
        self.assertEqual([], bin_layout_store.listHistoryAfter(3, 10))


if __name__ == "__main__":
    unittest.main()
