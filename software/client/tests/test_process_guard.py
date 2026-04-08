import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from process_guard import APP_NAME, ProcessGuardError, acquire_backend_process_guard


class _DummyLogger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass


class ProcessGuardTests(unittest.TestCase):
    def test_acquire_overwrites_stale_metadata_when_lock_is_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "backend.lock"
            lock_path.write_text('{"app": "stale", "pid": 999999}', encoding="utf-8")

            guard = acquire_backend_process_guard(
                script_path=Path(__file__).resolve().parents[1] / "main.py",
                repo_root=Path(__file__).resolve().parents[3],
                port=None,
                logger=_DummyLogger(),
                cleanup_port_conflicts=False,
                lock_path=lock_path,
            )

            try:
                payload = lock_path.read_text(encoding="utf-8")
                self.assertIn(APP_NAME, payload)
                self.assertIn(f'"pid": {guard.metadata["pid"]}', payload)
            finally:
                guard.release()

    def test_acquire_reclaims_existing_backend_lock_holder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "backend.lock"
            script_path = Path(__file__).resolve().parents[1] / "main.py"
            repo_root = Path(__file__).resolve().parents[3]
            proc = _spawn_lock_holder(
                lock_path=lock_path,
                app_name=APP_NAME,
                script_path=script_path,
                repo_root=repo_root,
            )

            try:
                guard = acquire_backend_process_guard(
                    script_path=script_path,
                    repo_root=repo_root,
                    port=None,
                    logger=_DummyLogger(),
                    cleanup_port_conflicts=False,
                    lock_path=lock_path,
                )
                try:
                    proc.wait(timeout=2.0)
                    self.assertIsNotNone(proc.returncode)
                    self.assertEqual(guard.metadata["pid"], os.getpid())
                finally:
                    guard.release()
            finally:
                _terminate_subprocess(proc)

    def test_acquire_rejects_foreign_lock_holder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "backend.lock"
            script_path = Path(__file__).resolve().parents[1] / "main.py"
            repo_root = Path(__file__).resolve().parents[3]
            proc = _spawn_lock_holder(
                lock_path=lock_path,
                app_name="other-app",
                script_path=script_path,
                repo_root=repo_root,
            )

            try:
                with self.assertRaises(ProcessGuardError):
                    acquire_backend_process_guard(
                        script_path=script_path,
                        repo_root=repo_root,
                        port=None,
                        logger=_DummyLogger(),
                        cleanup_port_conflicts=False,
                        lock_path=lock_path,
                    )
            finally:
                _terminate_subprocess(proc)


def _spawn_lock_holder(
    *,
    lock_path: Path,
    app_name: str,
    script_path: Path,
    repo_root: Path,
) -> subprocess.Popen[str]:
    holder_code = textwrap.dedent(
        """
        import fcntl
        import getpass
        import json
        import os
        from pathlib import Path
        import signal
        import sys
        import time

        lock_path = Path(sys.argv[1])
        app_name = sys.argv[2]
        script_path = sys.argv[3]
        repo_root = sys.argv[4]

        handle = lock_path.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        payload = {
            "app": app_name,
            "pid": os.getpid(),
            "user": getpass.getuser(),
            "script_path": script_path,
            "repo_root": repo_root,
            "cwd": str(Path(script_path).parent),
            "port": None,
            "started_at": time.time(),
        }
        handle.seek(0)
        handle.truncate()
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
        print("ready", flush=True)

        def _exit(*_args):
            sys.exit(0)

        signal.signal(signal.SIGTERM, _exit)
        signal.signal(signal.SIGINT, _exit)

        while True:
            time.sleep(0.1)
        """
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            holder_code,
            str(lock_path),
            app_name,
            str(script_path),
            str(repo_root),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    ready_line = proc.stdout.readline().strip()
    if ready_line != "ready":
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        _terminate_subprocess(proc)
        raise AssertionError(f"Lock holder failed to start. stdout={ready_line!r} stderr={stderr!r}")
    return proc


def _terminate_subprocess(proc: subprocess.Popen[str]) -> None:
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
