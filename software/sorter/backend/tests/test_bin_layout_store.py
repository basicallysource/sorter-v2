import os
import tempfile
import unittest
from unittest.mock import patch

from bin_layout_store import count_bin_layouts, get_bin_layout, set_bin_layout


class BinLayoutStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmpdir.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)

    def test_writing_a_bin_layout_stamps_servo_channels_and_keeps_a_preset(self) -> None:
        set_bin_layout({"layers": [{"sections": [["small"]], "servo_channel_id": 3}, {"sections": [["small"]]}]})
        self.assertEqual([3, 1], [layer["servo_channel_id"] for layer in get_bin_layout()["layers"]])
        self.assertEqual(1, count_bin_layouts())


if __name__ == "__main__":
    unittest.main()
