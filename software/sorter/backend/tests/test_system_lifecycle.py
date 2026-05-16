import threading
import time
import unittest

from fastapi import HTTPException

import server.shared_state as shared_state
from server.routers import steppers, system


class SystemLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            "hardware_state": shared_state.hardware_state,
            "hardware_error": shared_state.hardware_error,
            "hardware_homing_step": shared_state.hardware_homing_step,
            "_hardware_start_fn": shared_state._hardware_start_fn,
            "_hardware_initialize_fn": shared_state._hardware_initialize_fn,
            "_hardware_reset_fn": shared_state._hardware_reset_fn,
            "hardware_runtime_irl": shared_state.hardware_runtime_irl,
            "hardware_worker_thread": shared_state.hardware_worker_thread,
            "command_queue": shared_state.command_queue,
        }
        shared_state.hardware_state = "standby"
        shared_state.hardware_error = None
        shared_state.hardware_homing_step = None
        shared_state._hardware_start_fn = None
        shared_state._hardware_initialize_fn = None
        shared_state._hardware_reset_fn = None
        shared_state.hardware_runtime_irl = None
        shared_state.hardware_worker_thread = None
        shared_state.command_queue = None

    def tearDown(self) -> None:
        worker = shared_state.hardware_worker_thread
        if worker is not None and worker.is_alive():
            worker.join(timeout=1.0)

        shared_state.hardware_state = self._saved["hardware_state"]
        shared_state.hardware_error = self._saved["hardware_error"]
        shared_state.hardware_homing_step = self._saved["hardware_homing_step"]
        shared_state._hardware_start_fn = self._saved["_hardware_start_fn"]
        shared_state._hardware_initialize_fn = self._saved["_hardware_initialize_fn"]
        shared_state._hardware_reset_fn = self._saved["_hardware_reset_fn"]
        shared_state.hardware_runtime_irl = self._saved["hardware_runtime_irl"]
        shared_state.hardware_worker_thread = self._saved["hardware_worker_thread"]
        shared_state.command_queue = self._saved["command_queue"]

    def test_recover_sets_ready_after_success(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def start_fn() -> None:
            started.set()
            release.wait(timeout=1.0)

        shared_state._hardware_start_fn = start_fn

        response = system.recover_system()
        self.assertTrue(response["ok"])
        self.assertEqual("homing", response["hardware_state"])
        self.assertEqual("Safe hardware recovery started.", response["message"])
        self.assertTrue(started.wait(timeout=1.0))

        worker = shared_state.hardware_worker_thread
        self.assertIsNotNone(worker)
        self.assertEqual("homing", shared_state.hardware_state)

        release.set()
        assert worker is not None
        worker.join(timeout=1.0)

        self.assertEqual("ready", shared_state.hardware_state)
        self.assertIsNone(shared_state.hardware_error)
        self.assertIsNone(shared_state.hardware_worker_thread)

    def test_home_endpoint_aliases_safe_recover(self) -> None:
        called = threading.Event()

        def start_fn() -> None:
            called.set()

        shared_state._hardware_start_fn = start_fn

        response = system.home_system()

        self.assertTrue(response["ok"])
        self.assertEqual("homing", response["hardware_state"])
        self.assertTrue(called.wait(timeout=1.0))

    def test_recover_sets_error_after_failure(self) -> None:
        def start_fn() -> None:
            raise RuntimeError("boom")

        shared_state._hardware_start_fn = start_fn

        response = system.recover_system()
        self.assertTrue(response["ok"])

        deadline = time.monotonic() + 1.0
        while shared_state.hardware_worker_thread is not None and time.monotonic() < deadline:
            shared_state.hardware_worker_thread.join(timeout=0.05)

        self.assertEqual("error", shared_state.hardware_state)
        self.assertEqual("boom", shared_state.hardware_error)
        self.assertIsNone(shared_state.hardware_worker_thread)

    def test_recover_does_not_start_twice(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def start_fn() -> None:
            started.set()
            release.wait(timeout=1.0)

        shared_state._hardware_start_fn = start_fn

        first = system.recover_system()
        self.assertTrue(first["ok"])
        self.assertTrue(started.wait(timeout=1.0))

        second = system.recover_system()
        self.assertTrue(second["ok"])
        self.assertEqual("Already recovering hardware.", second["message"])

        release.set()
        worker = shared_state.hardware_worker_thread
        self.assertIsNotNone(worker)
        assert worker is not None
        worker.join(timeout=1.0)

    def test_reset_calls_registered_cleanup(self) -> None:
        calls: list[str] = []

        def reset_fn() -> None:
            calls.append("reset")

        shared_state.hardware_state = "ready"
        shared_state.hardware_homing_step = "Old step"
        shared_state.hardware_error = "old"
        shared_state._hardware_reset_fn = reset_fn

        response = system.reset_system()

        self.assertTrue(response["ok"])
        self.assertEqual(["reset"], calls)
        self.assertEqual("standby", shared_state.hardware_state)
        self.assertIsNone(shared_state.hardware_error)
        self.assertIsNone(shared_state.hardware_homing_step)

    def test_reset_is_blocked_while_homing(self) -> None:
        shared_state.hardware_state = "homing"
        called = False

        def reset_fn() -> None:
            nonlocal called
            called = True

        shared_state._hardware_reset_fn = reset_fn

        response = system.reset_system()

        self.assertFalse(response["ok"])
        self.assertEqual("homing", response["hardware_state"])
        self.assertFalse(called)

    def test_initialize_is_blocked_by_recover_worker(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def start_fn() -> None:
            started.set()
            release.wait(timeout=1.0)

        shared_state._hardware_start_fn = start_fn
        shared_state._hardware_initialize_fn = lambda: None

        first = system.recover_system()
        self.assertTrue(first["ok"])
        self.assertTrue(started.wait(timeout=1.0))

        second = system.initialize_system()
        self.assertFalse(second["ok"])
        self.assertEqual("Another hardware operation is already in progress.", second["message"])

        release.set()
        worker = shared_state.hardware_worker_thread
        self.assertIsNotNone(worker)
        assert worker is not None
        worker.join(timeout=1.0)

    def test_resume_is_blocked_while_hardware_not_ready(self) -> None:
        shared_state.hardware_state = "homing"

        with self.assertRaises(HTTPException) as ctx:
            steppers.resume()

        self.assertEqual(409, ctx.exception.status_code)
        self.assertIn("Cannot resume", str(ctx.exception.detail))

    def test_manual_motion_is_blocked_while_hardware_worker_is_active(self) -> None:
        release = threading.Event()

        def start_fn() -> None:
            release.wait(timeout=1.0)

        shared_state._hardware_start_fn = start_fn
        response = system.recover_system()
        self.assertTrue(response["ok"])

        with self.assertRaises(HTTPException) as ctx:
            steppers.pulse_stepper("carousel", "cw", duration_s=0.1, speed=100)

        self.assertEqual(409, ctx.exception.status_code)
        self.assertIn("Cannot pulse", str(ctx.exception.detail))

        release.set()
        worker = shared_state.hardware_worker_thread
        self.assertIsNotNone(worker)
        assert worker is not None
        worker.join(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
