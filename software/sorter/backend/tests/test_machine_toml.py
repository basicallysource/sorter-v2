"""Where the machine config is: one answer, and everything asks for it."""

import os
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


if __name__ == "__main__":
    unittest.main()
