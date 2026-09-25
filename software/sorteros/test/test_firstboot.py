"""sorteros-firstboot's progress page and the moment it hands port 80 to the
Sorter UI. Run: cd test && python3 -m unittest test_firstboot"""

import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "build/overlay/usr/local/sbin/sorteros-firstboot.py"
_spec = importlib.util.spec_from_file_location("sorteros_firstboot", _SRC)
fb = importlib.util.module_from_spec(_spec)
sys.modules["sorteros_firstboot"] = fb  # its dataclass looks itself up there
_spec.loader.exec_module(fb)

fb.SOFTWARE_STATUS = Path(tempfile.mkdtemp()) / "software.json"
fb._read_meta = lambda: ("sorter", "4.1.0", "sorter/stable/v0.2.0")
BEFORE_UI = [s.name for s in fb.STAGES if s.before_ui]


def machine(done=(), **states):
    """Stages in `done` are done, the ones named in `states` are (status, info)
    (underscores for dashes), everything else is pending."""
    with fb._state_lock:
        fb._stage_state.clear()
        fb._runtime["starting_since"] = None
    for s in fb.STAGES:
        fb._set_state(s.name, "done" if s.name in done else "pending")
    for name, (status, info) in states.items():
        fb._set_state(name.replace("_", "-"), status, info)


def row(progress, words):
    return next(r for r in progress["rows"] if r["words"] == words)


class Page(unittest.TestCase):
    def test_a_fresh_machine_is_installing(self):
        machine()
        p = fb._progress()
        self.assertEqual(p["phase"], "installing")
        self.assertEqual({r["state"] for r in p["rows"]}, {"pending"})
        self.assertIn("Installing the Sorter", fb._render_status_page().decode())

    def test_the_two_configuring_stages_are_one_row(self):
        machine()
        words = [r["words"] for r in fb._progress()["rows"]]
        self.assertEqual(words.count("Configuring"), 1)
        self.assertEqual(len(words), len(set(words)))

    def test_waiting_for_the_internet(self):
        machine(done=BEFORE_UI[:3], clone_repo=("waiting", fb.WAITING_FOR_INTERNET),
                write_env=("waiting", "repo not cloned yet"))
        p = fb._progress()
        self.assertEqual(p["phase"], "waiting")
        self.assertEqual(row(p, "Downloading the Sorter software")["state"], "waiting")
        # a stage waiting on an earlier one is not a failure
        self.assertEqual(row(p, "Configuring")["state"], "pending")

    def test_a_failure_shows_and_is_retried(self):
        machine(done=BEFORE_UI[:6], uv_sync=("waiting", "/usr/local/bin/uv exited 2"),
                pnpm_install=("active", ""))
        p = fb._progress()
        self.assertEqual(p["phase"], "installing")
        self.assertEqual(row(p, "Installing Python packages"),
                         {"words": "Installing Python packages", "stages": ["uv-sync"],
                          "state": "retrying", "detail": "/usr/local/bin/uv exited 2"})
        self.assertEqual(row(p, "Installing the interface's packages")["state"], "active")
        self.assertIn("Failed, trying again: /usr/local/bin/uv exited 2", fb._render_status_page().decode())

    def test_starting_once_everything_the_ui_needs_is_in_place(self):
        machine(done=BEFORE_UI)
        p = fb._progress()
        self.assertEqual(p["phase"], "starting")
        # not done: that is when the UI has port 80, and this page is gone
        self.assertEqual(row(p, "Starting the Sorter")["state"], "active")
        with fb._state_lock:
            fb._runtime["starting_since"] = fb.time.time() - 41
        p = fb._progress()
        self.assertEqual(p["phase"], "starting")
        self.assertEqual(row(p, "Starting the Sorter"), {"words": "Starting the Sorter", "stages": ["install-services"],
                                                         "state": "active", "detail": "41s"})
        self.assertTrue(all(r["state"] == "done" for r in p["rows"][:-1]))

    def test_the_page_never_links_to_a_ui_that_is_not_there(self):
        for done, starting in ((), None), (BEFORE_UI, None), (BEFORE_UI, 5.0):
            machine(done=done)
            with fb._state_lock:
                fb._runtime["starting_since"] = starting
            page = fb._render_status_page().decode()
            self.assertIn("data-firstboot", page)  # what the page's poller recognises
            self.assertNotIn("Reload", page)
            self.assertNotIn('<meta http-equiv="refresh" content="5"></head>', page)  # only inside <noscript>

    def test_status_json_lists_every_stage(self):
        machine(done=BEFORE_UI[:2])
        status = json.loads(fb._status_json())
        self.assertEqual(status["phase"], "installing")
        self.assertEqual([s["name"] for s in status["stages"]], [s.name for s in fb.STAGES])
        self.assertEqual(status["stages"][0], {"name": "ssh-host-keys", "state": "done", "info": ""})

    def test_names_are_escaped(self):
        machine(done=BEFORE_UI[:6], uv_sync=("waiting", "<b>boom</b>"))
        self.assertNotIn("<b>boom", fb._render_status_page().decode())


class FakeClock:
    def __init__(self):
        self.now = 1_790_000_000.0

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s


class Handover(unittest.TestCase):
    """The backend starts first; port 80 stays with the page until it answers."""

    def setUp(self):
        self.calls: list = []
        self.ui_ready = threading.Event()
        self.saved = (fb.subprocess.run, fb._backend_answers, fb._sorter_services, fb.time)
        fb.subprocess.run = lambda cmd, **kw: self.calls.append(("run", tuple(cmd), self.ui_ready.is_set()))
        fb._sorter_services = lambda: ["sorter-backend-dev.service", "sorter-ui-dev.service"]
        fb.time = FakeClock()

    def tearDown(self):
        fb.subprocess.run, fb._backend_answers, fb._sorter_services, fb.time = self.saved
        with fb._state_lock:
            fb._runtime["starting_since"] = None

    def keeper(self):
        t = threading.Thread(target=self.ui_ready.wait, daemon=True)
        t.start()
        return t

    def test_the_backend_goes_first_and_the_ui_waits_for_it(self):
        answers = iter([False, False, False, True])

        def backend_answers():
            self.calls.append(("asked", self.ui_ready.is_set()))
            return next(answers)
        fb._backend_answers = backend_answers
        fb._start_sorter(self.keeper(), self.ui_ready)
        self.assertEqual(self.calls, [
            ("run", ("systemctl", "start", "sorter-backend-dev.service"), False),
            ("asked", False), ("asked", False), ("asked", False), ("asked", False),
            ("run", ("systemctl", "start", "sorter-ui-dev.service"), True),
        ])

    def test_a_backend_that_never_answers_still_gets_its_ui(self):
        fb._backend_answers = lambda: False
        fb._start_sorter(self.keeper(), self.ui_ready)
        self.assertTrue(self.ui_ready.is_set())
        self.assertEqual(self.calls[-1], ("run", ("systemctl", "start", "sorter-ui-dev.service"), True))
        self.assertGreaterEqual(fb.time.now - 1_790_000_000.0, fb.BACKEND_START_TIMEOUT)

    def test_without_the_page_everything_starts_at_once(self):
        fb._backend_answers = lambda: self.fail("no page, nothing to wait for")
        fb._start_sorter(None, self.ui_ready)
        self.assertEqual(self.calls, [
            ("run", ("systemctl", "start", "sorter-backend-dev.service", "sorter-ui-dev.service"), False)])


if __name__ == "__main__":
    unittest.main()
