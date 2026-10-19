import os
import tempfile
import unittest
from unittest.mock import patch

import hive_defaults
import sharing
from hardware_settings.motors import motorNamed
from hardware_settings.steppers import readStepperSettings


class HiveDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["LOCAL_STATE_DB_PATH"] = os.path.join(self._tmpdir.name, "state.sqlite")
        hive_defaults.invalidate()
        sharing.invalidate()

    def tearDown(self) -> None:
        hive_defaults.invalidate()
        sharing.invalidate()
        if self._old_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_db
        self._tmpdir.cleanup()

    def test_a_new_version_is_fetched_once_and_kept(self) -> None:
        fetched: list = []

        def fetch(etag):
            fetched.append(etag)
            return {"version": "v1", "defaults": {"sharing": {"channel_crops": False}}}

        self.assertTrue(hive_defaults.noteVersion("hive-a", "v1", fetch))
        self.assertFalse(hive_defaults.noteVersion("hive-a", "v1", fetch))
        self.assertEqual([None], fetched)
        hive_defaults.invalidate()  # as after a restart
        self.assertEqual("v1", hive_defaults.status()["version"])
        # A newer version is asked for with the one kept, and a 304 keeps it.
        self.assertFalse(hive_defaults.noteVersion("hive-a", "v2", lambda etag: fetched.append(etag)))
        self.assertEqual([None, '"v1"'], fetched)
        self.assertEqual("v1", hive_defaults.status()["version"])

    def test_a_broken_block_or_a_failed_fetch_keeps_what_was_kept(self) -> None:
        hive_defaults.keep("hive-a", "v1", {"sharing": {"network": False}})

        def boom(_etag):
            raise OSError("unreachable")

        self.assertFalse(hive_defaults.noteVersion("hive-a", "v2", boom))
        self.assertFalse(hive_defaults.noteVersion("hive-a", "v2", lambda _e: {"version": "v2"}))
        self.assertEqual("v1", hive_defaults.status()["version"])

    def test_hive_values_replace_code_defaults_and_bad_ones_are_ignored(self) -> None:
        hive_defaults.keep("hive-a", "v1", {"sharing": {"channel_crops": False, "network": "no"}})
        self.assertFalse(sharing.defaults()["channel_crops"])
        self.assertTrue(sharing.defaults()["network"])
        self.assertEqual(False, next(s for s in sharing.streamList() if s["key"] == "channel_crops")["default"])

    def test_stepper_defaults_layer_by_specificity_and_saved_settings_win(self) -> None:
        chute = motorNamed("chute")
        c1 = motorNamed("c_channel_1")
        hive_defaults.keep("hive-a", "v1", {"steppers": {
            "*": {"irun": 20, "microsteps": 16, "inverted": True},
            "chute": {"sgthrs": 70, "microsteps": 3},
        }})
        settings = readStepperSettings(chute, {})
        self.assertEqual((20, 16, 70, False), (settings.irun, settings.microsteps, settings.sgthrs, settings.inverted))
        # The code's own default for this motor is more specific than Hive's for every motor.
        self.assertEqual(4, readStepperSettings(c1, {}).irun)
        saved = readStepperSettings(chute, {"stepper_stallguard": {"chute_stepper": {"enabled": True, "sgthrs": 40, "tcoolthrs": 150}}})
        self.assertEqual(40, saved.sgthrs)

    def test_the_primary_hives_heartbeat_fetches_the_block(self) -> None:
        from server import hive_heartbeat

        beat = hive_heartbeat.HiveHeartbeat.__new__(hive_heartbeat.HiveHeartbeat)
        beat._sync = None
        beat._lock = hive_heartbeat.threading.Lock()
        beat._primary_id = "primary"
        beat._specs_next_at = float("inf")
        fetches: list[str] = []

        class _Client:
            def __init__(self, name):
                self.name = name

            def heartbeat(self, **_kwargs):
                return True, {"limits": None, "defaults_version": "v9"}

            def getDefaults(self, etag):
                fetches.append(self.name)
                return {"version": "v9", "defaults": {}}

        beat._targets = {
            "primary": {"name": "P", "client": _Client("primary")},
            "other": {"name": "O", "client": _Client("other")},
        }
        with patch.object(hive_heartbeat, "_collectNetwork", lambda: None):
            beat._beat()
        self.assertEqual(["primary"], fetches)


if __name__ == "__main__":
    unittest.main()
