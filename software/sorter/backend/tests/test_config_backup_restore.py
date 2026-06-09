import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import local_state
from server import config_backup


class ConfigBackupRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._old_local_state_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._old_suppress_path = os.environ.get("SORTER_CONFIG_BACKUP_SUPPRESS_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmpdir.name)
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(tmp_path / "machine_params.toml")
        os.environ["LOCAL_STATE_DB_PATH"] = str(tmp_path / "local_state.sqlite")
        os.environ["SORTER_CONFIG_BACKUP_SUPPRESS_PATH"] = str(tmp_path / "restore-suppress.json")

    def tearDown(self) -> None:
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params

        if self._old_local_state_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_local_state_db

        if self._old_suppress_path is None:
            os.environ.pop("SORTER_CONFIG_BACKUP_SUPPRESS_PATH", None)
        else:
            os.environ["SORTER_CONFIG_BACKUP_SUPPRESS_PATH"] = self._old_suppress_path

        self._tmpdir.cleanup()

    def test_restore_reconnects_local_machine_identity_from_backup_payload(self) -> None:
        local_state.set_machine_id("fresh-machine")
        backup = {
            "payload": {
                "machine_id": "restored-machine",
                "toml_text": '[machine]\nnickname = "Restored Bench"\n',
                "local_state": {},
            }
        }

        with patch.object(config_backup, "_fetch_version", return_value=backup):
            result = config_backup.restore_version(7)

        self.assertTrue(result["ok"])
        self.assertTrue(result["wrote_machine_id"])
        self.assertTrue(result["wrote_toml"])
        self.assertEqual("restored-machine", local_state.get_machine_id())
        self.assertTrue(result["suppressed_backup_hash"])
        self.assertTrue(config_backup._should_suppress_sync_for_hash(result["suppressed_backup_hash"]))


if __name__ == "__main__":
    unittest.main()
