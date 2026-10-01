import os
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

import db


class DbTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        env = mock.patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmpdir.name, "state.sqlite")})
        env.start()
        self.addCleanup(env.stop)
        self.logger = mock.Mock()
        db.configure(self.logger)
        self.addCleanup(db.configure, None)

    def warnings(self, text: str) -> list[str]:
        return [c.args[0] for c in self.logger.warning.call_args_list if text in c.args[0]]

    def test_schema_runs_once_per_database_and_each_connection_closes(self) -> None:
        runs = []

        def schema(conn: sqlite3.Connection) -> None:
            runs.append(1)
            conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")

        for _ in range(3):
            with db.connect(schema) as conn:
                conn.execute("INSERT INTO t VALUES (1)")
                conn.commit()
        self.assertEqual(1, len(runs))
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_closing_a_connection_does_not_checkpoint(self) -> None:
        # A close that finds no other connection checkpoints and deletes the
        # WAL; db's idle connection must keep that from happening, even on a
        # database it just created.
        with db.connect() as conn:
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.commit()
        self.assertTrue(os.path.exists(os.environ["LOCAL_STATE_DB_PATH"] + "-wal"))

    def test_every_connection_is_wal_with_synchronous_normal(self) -> None:
        with db.connect() as conn:
            self.assertEqual("wal", conn.execute("PRAGMA journal_mode").fetchone()[0])
            self.assertEqual(1, conn.execute("PRAGMA synchronous").fetchone()[0])

    def test_a_connection_held_too_long_is_logged(self) -> None:
        with mock.patch.object(db, "SLOW_MS", 0.0):
            with db.connect() as conn:
                conn.execute("SELECT 1")
        slow = self.warnings("[db] slow ")
        self.assertEqual(1, len(slow))
        self.assertIn(".test_a_connection_held_too_long_is_logged ", slow[0])

    def test_deferred_writes_run_in_order_on_the_writer_thread(self) -> None:
        ran: list[str] = []

        def write(name: str) -> None:
            ran.append(f"{name} on {threading.current_thread().name}")

        db.defer("first", lambda: write("first"))
        db.defer("broken", lambda: 1 / 0)
        db.defer("second", lambda: write("second"))
        self.assertTrue(db.drain(5.0))
        self.assertEqual(["first on db-writer", "second on db-writer"], ran)
        self.assertEqual(1, len(self.warnings("[db] broken failed")))

    def test_connections_on_a_realtime_thread_are_logged_once_per_interval(self) -> None:
        db.watch_realtime_thread()
        self.addCleanup(db.watch_realtime_thread, False)
        for _ in range(3):
            with db.connect():
                pass
        self.assertEqual(1, len(self.warnings("[db] on realtime thread")))


if __name__ == "__main__":
    unittest.main()
