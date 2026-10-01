"""Where the machine config is: one answer, and everything asks for it."""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import machine_toml

BACKEND = Path(machine_toml.__file__).resolve().parent


class MachineTomlPathTests(unittest.TestCase):
    def test_without_the_variable_it_is_software_machine_toml(self) -> None:
        with mock.patch.dict(os.environ):
            os.environ.pop(machine_toml.ENV_VAR, None)
            self.assertEqual(machine_toml.machine_toml_path(), BACKEND.parents[1] / "machine.toml")

    def test_a_relative_value_is_taken_from_the_backend_directory(self) -> None:
        # How deployed machines set it in software/.env, and how SorterOS did.
        for value, expected in (
            ("../../machine.toml", BACKEND.parents[1] / "machine.toml"),
            ("../machine.toml", BACKEND.parent / "machine.toml"),
        ):
            with mock.patch.dict(os.environ, {machine_toml.ENV_VAR: value}):
                self.assertEqual(machine_toml.machine_toml_path(), expected)

    def test_it_does_not_depend_on_where_a_process_starts(self) -> None:
        here = os.getcwd()
        try:
            os.chdir("/")
            with mock.patch.dict(os.environ, {machine_toml.ENV_VAR: "../../machine.toml"}):
                self.assertEqual(machine_toml.machine_toml_path(), BACKEND.parents[1] / "machine.toml")
        finally:
            os.chdir(here)

    def test_an_absolute_value_is_used_as_it_is(self) -> None:
        with mock.patch.dict(os.environ, {machine_toml.ENV_VAR: "/srv/sorter/machine.toml"}):
            self.assertEqual(machine_toml.machine_toml_path(), Path("/srv/sorter/machine.toml"))

    def test_nothing_else_reads_the_variable(self) -> None:
        # A dozen readers with a fallback each is how settings saved in the UI
        # ended up in a file the running machine never read.
        own = Path(machine_toml.__file__).resolve()
        offenders = []
        for root, dirs, files in os.walk(BACKEND):
            dirs[:] = [d for d in dirs if d not in {".venv", "node_modules", "__pycache__", "tests"}]
            for name in files:
                path = Path(root, name)
                if name.endswith(".py") and path.resolve() != own:
                    if machine_toml.ENV_VAR in path.read_text(encoding="utf-8", errors="ignore"):
                        offenders.append(str(path.relative_to(BACKEND)))
        self.assertEqual(offenders, [], "ask machine_toml.machine_toml_path() for the path instead")


class MachineTomlEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "machine.toml"
        self._env = mock.patch.dict(os.environ, {machine_toml.ENV_VAR: str(self.path)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmpdir.cleanup()

    def test_no_file_reads_as_empty(self) -> None:
        self.assertEqual(machine_toml.read(), {})

    def test_an_edit_is_written_and_read_back(self) -> None:
        with machine_toml.edit() as config:
            config["chute"] = {"first_bin_center": 12.5, "endstop_active_high": False}
            config["cameras"] = {"c_channel_2": 0, "layout": "split_feeder"}
        self.assertEqual(
            machine_toml.read(),
            {
                "chute": {"first_bin_center": 12.5, "endstop_active_high": False},
                "cameras": {"c_channel_2": 0, "layout": "split_feeder"},
            },
        )

    def test_keys_that_need_quoting_survive(self) -> None:
        # The hand-rolled writer this replaced wrote keys bare, so a key with a dot
        # turned into a nested table.
        with machine_toml.edit() as config:
            config["camera_device_settings"] = {"/dev/video0": {"brightness": 3.0}, "a.b": {"x": 1}}
        self.assertEqual(
            machine_toml.read()["camera_device_settings"],
            {"/dev/video0": {"brightness": 3.0}, "a.b": {"x": 1}},
        )

    def test_none_values_are_left_out(self) -> None:
        with machine_toml.edit() as config:
            config["servo"] = {"port": None, "channels": [{"id": 1, "invert": False}]}
        self.assertEqual(machine_toml.read(), {"servo": {"channels": [{"id": 1, "invert": False}]}})

    def test_an_unchanged_edit_does_not_write(self) -> None:
        self.path.write_text('[machine]\nnickname = "Bench" # kept\n', encoding="utf-8")
        with machine_toml.edit() as config:
            config.get("machine")
        self.assertIn("# kept", self.path.read_text(encoding="utf-8"))

    def test_a_failed_edit_writes_nothing(self) -> None:
        with self.assertRaises(RuntimeError):
            with machine_toml.edit() as config:
                config["machine"] = {"nickname": "half done"}
                raise RuntimeError("validation failed")
        self.assertFalse(self.path.exists())

    def test_a_read_parses_the_file_once_until_it_changes(self) -> None:
        self.path.write_text('[machine]\nnickname = "Bench"\n', encoding="utf-8")
        self.assertEqual(machine_toml.read(), {"machine": {"nickname": "Bench"}})
        with mock.patch.object(machine_toml.tomllib, "loads", side_effect=AssertionError("parsed again")):
            config = machine_toml.read()
        config["machine"]["nickname"] = "changed by a caller"
        self.assertEqual(machine_toml.read(), {"machine": {"nickname": "Bench"}})

        self.path.write_text('[machine]\nnickname = "Shelf"\n', encoding="utf-8")
        self.assertEqual(machine_toml.read(), {"machine": {"nickname": "Shelf"}})
        with machine_toml.edit() as config:
            config["machine"]["nickname"] = "Rack"
        self.assertEqual(machine_toml.read(), {"machine": {"nickname": "Rack"}})

    def test_malformed_file_raises(self) -> None:
        self.path.write_text("[machine\nnickname = ", encoding="utf-8")
        with self.assertRaises(machine_toml.MachineTomlError):
            machine_toml.read()

    def test_concurrent_edits_keep_every_change(self) -> None:
        def bump(key: str) -> None:
            for _ in range(25):
                with machine_toml.edit() as config:
                    counts = config.setdefault("counts", {})
                    counts[key] = counts.get(key, 0) + 1

        threads = [threading.Thread(target=bump, args=(f"t{i}",)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(machine_toml.read()["counts"], {f"t{i}": 25 for i in range(4)})


if __name__ == "__main__":
    unittest.main()
