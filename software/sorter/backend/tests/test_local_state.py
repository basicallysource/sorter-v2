import os
import tempfile
import unittest
from unittest.mock import patch

import db
from local_state import get_machine_id, set_machine_id


class LocalStateTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmpdir.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)

    def test_a_state_read_runs_one_statement_once_the_schema_exists(self) -> None:
        set_machine_id("machine-1")
        statements: list[str] = []
        open_connection = db._open

        def traced_open(path):
            conn = open_connection(path)
            conn.set_trace_callback(statements.append)
            return conn

        with patch.object(db, "_open", traced_open):
            self.assertEqual("machine-1", get_machine_id())
        self.assertEqual(1, len(statements), statements)


if __name__ == "__main__":
    unittest.main()
