"""What the computer was doing when it last stopped, kept where a restart
cannot lose it.

A machine's journal and /var/log can live in RAM to spare its storage, so after
the computer restarts by itself nothing on it says why. This keeps just enough
beside the machine's data, in boot_record/:

- heartbeat.json: rewritten in place every SORTER_HEARTBEAT_S (30 s; 0 switches
  all of this off): the time, the uptime, what the sorter was doing, memory,
  the backend's memory, the chip's temperature, load and the software version.
  A stop that was asked for (the service stopped, a restart, reboot or shutdown
  from the UI, an update) is written into it, `stopped`, before the stop.
- last_words.log: the newest warning and error lines the backend logged, a ring
  of fixed-size lines; only the new ones are written.
- boot_history.jsonl: one line per start: when the machine was last alive, how
  long it was dark, what it was doing, and what is known about why, from the
  stop mark, the kernel's boot id, what the kernel kept across the restart
  (pstore) and the watchdog's boot status. The newest HISTORY_KEEP.
- pstore/: copies of what the kernel kept, of the newest PSTORE_KEEP restarts.
- seen.json: the newest record the operator pressed Done on.

The supervisor writes the first four (Recorder): it outlives the backend, so a
backend that hangs or dies is recorded too. The backend tells it what the
sorter is doing and its warning lines over a pipe (Reporter), and raises the
dashboard's warning after a restart nobody asked for.

What it costs: a heartbeat reads five small /proc and /sys files and writes one
4 KB block (fdatasync; the file never grows and is never renamed), on a thread
of the supervisor's; nothing starts a subprocess. Nothing here can stop the
supervisor or the backend: a missing or damaged file, an unreadable /sys path
or a read-only disk is said once in the log and left at that. Standard library
only.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import signal
import stat
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

HEARTBEAT_ENV = "SORTER_HEARTBEAT_S"
HEARTBEAT_S = 30.0
HEARTBEAT_MIN_S = 5.0
HEARTBEAT_MAX_S = 3600.0
# The pipe's write end, for the backend the supervisor starts.
REPORT_FD_ENV = "SORTER_BOOT_REPORT_FD"

FOLDER = "boot_record"
HEARTBEAT_FILE = "heartbeat.json"
WORDS_FILE = "last_words.log"
HISTORY_FILE = "boot_history.jsonl"
SEEN_FILE = "seen.json"
PSTORE_FOLDER = "pstore"

# heartbeat.json is two slots written in turn, each one file system block, so
# a write cut short by the stop it is there to record leaves the one before.
SLOT_BYTES = 4096
# last_words.log: WORD_COUNT lines of WORD_BYTES, "<number> <line>", the line
# numbered n at n % WORD_COUNT.
WORD_BYTES = 320
WORD_COUNT = 200
WORD_CHARS = 300
HISTORY_KEEP = 200
HISTORY_SLACK = 40  # trimmed back to HISTORY_KEEP once this many over
RECORD_WORDS = 20
PSTORE_KEEP = 5
PSTORE_MAX_FILES = 12
PSTORE_MAX_BYTES = 1024 * 1024
# Where the kernel shows what it kept, and where the system's own archiver
# (systemd-pstore), on a computer that runs it, moves that at boot.
PSTORE_DIRS = ("/sys/fs/pstore", "/var/lib/systemd/pstore")
WDIOF_CARDRESET = 0x20
_WATCHDOG_BITS = {0x01: "overheated", 0x10: "supply voltage low", WDIOF_CARDRESET: "reset by the watchdog"}
# The backend's exits waiting to be written, at most (a disk that stopped answering).
RECORDS_WAITING = 20
# A stop that was announced counts as asked for if it comes within this.
ASKED_FOR_S = 120.0
STOP_WAIT_S = 3.0
# A backend that keeps ending within FAST_EXIT_S is recorded this many times,
# then counted, so a crash loop does not write a line every few seconds.
FAST_EXIT_S = 30.0
FAST_EXITS_RECORDED = 3
REPORT_TICK_S = 5.0
STATE_EVERY_S = 30.0

# Why a stop was asked for, as the heartbeat's `stopped` says it.
SERVICE_STOP = "service stop"
TERMINAL_STOP = "stopped from the terminal"
RESTART_ASKED = "restart asked from the UI"
REBOOT_ASKED = "reboot asked from the UI"
SHUTDOWN_ASKED = "shutdown asked from the UI"
UPDATE_RESTART = "restart after a software update"

# What a start followed, in a record's `kind`, and in plain words in `what`.
ASKED = "asked"
CLEAN = "stopped_cleanly"
KERNEL_CRASH = "kernel_crashed"
RESET = "reset"
POWER_LOST = "power_lost"
UNEXPLAINED = "unexplained"
BACKEND = "backend_restarted"
FIRST = "first_record"
WHAT = {
    ASKED: "restarted on request",
    CLEAN: "stopped cleanly (the system was shut down)",
    KERNEL_CRASH: "the kernel crashed (record kept)",
    RESET: "restarted without warning: reset or watchdog, memory kept",
    POWER_LOST: "lost power or was reset hard: nothing was kept",
    UNEXPLAINED: "restarted without warning: this computer kept no record of why",
    BACKEND: "the backend stopped and was started again (the computer stayed up)",
    FIRST: "no earlier record: boot records start here",
}
BY_ITSELF = frozenset({KERNEL_CRASH, RESET, POWER_LOST, UNEXPLAINED, BACKEND})
# The dashboard's warnings (incidents/kinds.py).
COMPUTER_WARNING = "computer_restarted"
BACKEND_WARNING = "backend_restarted"

_BEFORE = ("state", "state_age_s", "mem_used_pct", "backend_rss_mb", "temp_c", "load1", "uptime_s", "version")


def heartbeatSeconds() -> float:
    """SORTER_HEARTBEAT_S: seconds between heartbeats, 0 for none of this."""
    try:
        seconds = float(os.environ.get(HEARTBEAT_ENV, "").strip() or HEARTBEAT_S)
    except ValueError:
        return HEARTBEAT_S
    return min(HEARTBEAT_MAX_S, max(HEARTBEAT_MIN_S, seconds)) if seconds > 0 else 0.0


def directory() -> Path:
    import db

    return db.local_state_db_path().parent / FOLDER


# ---------------------------------------------------------------------------
# Reading the kernel's files
# ---------------------------------------------------------------------------


def _text(path: str) -> str | None:
    try:
        with open(path, "r") as handle:
            return handle.read()
    except (OSError, ValueError):
        return None


def uptime() -> float:
    """Seconds since the computer started."""
    try:
        return float((_text("/proc/uptime") or "").split()[0])
    except (IndexError, ValueError):
        return time.monotonic()


def bootId() -> str | None:
    """The kernel's own name for this start of the computer."""
    return (_text("/proc/sys/kernel/random/boot_id") or "").strip() or None


def clockSynced() -> bool | None:
    try:
        import computer_health

        return computer_health.clockSynchronized()
    except Exception:
        return None


_zone: Any = False  # the chip's thermal zone, once looked for


def readings(pid: int | None) -> dict[str, Any]:
    """Memory, the backend's memory, the chip's temperature and load."""
    global _zone
    values: dict[str, Any] = {"mem_used_pct": None, "backend_rss_mb": None, "temp_c": None, "load1": None}
    try:
        import computer_health as health

        if _zone is False:
            _zone = health.mainZone(health.listZones(Path("/")))
        memory = health.memory(health.parseMeminfo(_text("/proc/meminfo") or ""))
        load = health.parseLoadavg(_text("/proc/loadavg") or "")
        rss = health.parseMeminfo(_text(f"/proc/{pid}/status") or "").get("VmRSS") if pid else None
        values["mem_used_pct"] = memory["used_pct"] if memory else None
        values["backend_rss_mb"] = round(rss / 1048576) if rss else None
        values["temp_c"] = health.readTemperature(Path("/"), _zone) if _zone else None
        values["load1"] = load[0] if load else None
    except Exception:
        pass
    return values


def _oomKills() -> int | None:
    """How many processes the kernel has ended for want of memory."""
    for line in (_text("/proc/vmstat") or "").splitlines():
        if line.startswith("oom_kill "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def codeVersion(start: Path | None = None) -> str | None:
    """The commit that is checked out, read from .git."""
    try:
        here = start or Path(__file__).resolve().parent
        for folder in (here, *here.parents):
            git = folder / ".git"
            if git.is_file():  # a worktree: "gitdir: <where its HEAD is>"
                git = (folder / git.read_text().split(":", 1)[1].strip()).resolve()
            if not git.is_dir():
                continue
            head = (git / "HEAD").read_text().strip()
            if not head.startswith("ref:"):
                return head[:12]
            ref = head.split(None, 1)[1]
            common = git / "commondir"
            shared = (git / common.read_text().strip()).resolve() if common.is_file() else git
            for base in (git, shared):
                if (base / ref).is_file():
                    return (base / ref).read_text().strip()[:12]
            for line in (shared / "packed-refs").read_text().splitlines():
                if line.endswith(" " + ref):
                    return line.split()[0][:12]
            return None
    except (OSError, IndexError, ValueError):
        pass
    return None


def readWatchdog() -> dict[str, int]:
    """Each watchdog's boot status, where its driver gives one."""
    found: dict[str, int] = {}
    try:
        names = sorted(os.listdir("/sys/class/watchdog"))
    except OSError:
        return found
    for name in names:
        try:
            found[name] = int((_text(f"/sys/class/watchdog/{name}/bootstatus") or "").strip(), 0)
        except ValueError:
            pass
    return found


def readPstore(seen: set[str]) -> dict[str, Any]:
    """What the kernel kept across the restart: the files in /sys/fs/pstore,
    or when that is empty, the newest in the system archiver's folder. A file
    is new when the record of the start before this one does not list it:
    nothing is deleted from pstore here, so a crash record stays there until
    the power goes."""
    backend = (_text("/sys/module/pstore/parameters/backend") or "").strip()
    found: list[tuple[float, float, str]] = []  # (newest first by this, written at, path)
    for folder in PSTORE_DIRS:
        for root, _dirs, names in os.walk(folder):
            for name in names:
                path = os.path.join(root, name)
                try:
                    info = os.stat(path)
                except OSError:
                    continue
                found.append((max(info.st_mtime, info.st_ctime), info.st_mtime, path))
        if found:
            break
    files: list[dict[str, Any]] = []
    for _newest, changed, path in sorted(found, reverse=True)[:PSTORE_MAX_FILES]:
        try:
            with open(path, "rb") as handle:
                data = handle.read(PSTORE_MAX_BYTES)
        except OSError:
            continue
        if data:
            digest = hashlib.sha1(data).hexdigest()[:16]
            files.append({
                "name": os.path.basename(path),
                "bytes": len(data),
                # When the kernel wrote it, where the kernel says (a crash record's time).
                "time": _stamp(changed) if changed > 0 else None,
                "sha1": digest,
                "new": digest not in seen,
                "data": data,
            })
    return {
        "backend": backend if backend not in ("", "(null)") else None,
        "readable": os.access(PSTORE_DIRS[0], os.R_OK | os.X_OK),
        "files": files,
    }


# ---------------------------------------------------------------------------
# The files
# ---------------------------------------------------------------------------


_datasync = getattr(os, "fdatasync", os.fsync)


class _FixedFile:
    """A file of one size for good, written in place: with fdatasync only the
    blocks written go to the disk, and nothing of the file system's own. Its
    blocks are laid out once, when it is made."""

    def __init__(self, path: Path, size: int) -> None:
        self._fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        if os.fstat(self._fd).st_size != size:
            os.pwrite(self._fd, bytes(size), 0)
            os.ftruncate(self._fd, size)
            os.fsync(self._fd)

    def write(self, offset: int, data: bytes) -> None:
        os.pwrite(self._fd, data, offset)

    def sync(self) -> None:
        _datasync(self._fd)


def _syncFolder(folder: Path) -> None:
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _slot(beat: dict[str, Any]) -> bytes:
    return json.dumps(beat, separators=(",", ":")).encode()[: SLOT_BYTES - 1].ljust(SLOT_BYTES - 1) + b"\n"


def readHeartbeat(folder: Path) -> dict[str, Any] | None:
    """The newest heartbeat that reads whole."""
    try:
        raw = (folder / HEARTBEAT_FILE).read_bytes()
    except OSError:
        return None
    beats = []
    for start in range(0, len(raw), SLOT_BYTES):
        try:
            beat = json.loads(raw[start : start + SLOT_BYTES])
        except ValueError:
            continue
        if isinstance(beat, dict) and isinstance(beat.get("seq"), int) and isinstance(beat.get("t"), (int, float)):
            beats.append(beat)
    return max(beats, key=lambda beat: beat["seq"]) if beats else None


def _line(record: dict[str, Any]) -> bytes:
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode()


def _wordLine(number: int, text: str) -> bytes:
    line = f"{number:010d} ".encode() + text.replace("\n", " | ").encode("utf-8", "replace")
    return line[: WORD_BYTES - 1].ljust(WORD_BYTES - 1) + b"\n"


def readWords(folder: Path) -> list[tuple[int, str]]:
    """(number, line) for every line of last_words.log, oldest first."""
    try:
        raw = (folder / WORDS_FILE).read_bytes()
    except OSError:
        return []
    words = []
    for start in range(0, len(raw) - WORD_BYTES + 1, WORD_BYTES):
        line = raw[start : start + WORD_BYTES]
        if line[:10].isdigit() and line[10:11] == b" ":
            words.append((int(line[:10]), line[11:].decode("utf-8", "replace").rstrip()))
    return sorted(words)


def readHistory(folder: Path) -> list[dict[str, Any]]:
    """Every record of boot_history.jsonl that reads whole, oldest first."""
    try:
        lines = (folder / HISTORY_FILE).read_bytes().splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# What a start followed
# ---------------------------------------------------------------------------


def computerRestarted(previous: dict[str, Any] | None, boot_id: str | None, up: float) -> bool:
    """Whether the computer itself restarted since the last heartbeat: the
    kernel's boot id changed, or without one, its uptime started over."""
    if previous is None:
        return True
    if boot_id and previous.get("boot_id"):
        return previous["boot_id"] != boot_id
    before = previous.get("uptime_s")
    return up < before if isinstance(before, (int, float)) else True


def classify(
    previous: dict[str, Any] | None, restarted: bool, pstore: dict[str, Any], watchdog: dict[str, int]
) -> tuple[str, str, list[str]]:
    """(kind, what in plain words, the evidence) for a start of the supervisor."""
    if previous is None:
        return FIRST, WHAT[FIRST], ["no heartbeat of an earlier run was found"]
    evidence = ["the computer restarted (a new kernel boot id)" if restarted else "the computer stayed up (the same kernel boot id)"]
    mark = previous.get("stopped")
    if mark:
        evidence.append(f"the last heartbeat carries a stop mark: {mark}")
        if mark == SHUTDOWN_ASKED or (restarted and mark in (SERVICE_STOP, TERMINAL_STOP)):
            return CLEAN, WHAT[CLEAN], evidence
        if not restarted and mark in (SERVICE_STOP, TERMINAL_STOP):
            evidence.append("the service was stopped and started again (a deploy or a service restart)")
        return ASKED, WHAT[ASKED], evidence
    evidence.append("the last heartbeat carries no stop mark")
    if not restarted:
        evidence.append("the supervisor ended without being asked to")
        return BACKEND, WHAT[BACKEND], evidence
    watchdog_reset = False
    for name, bits in watchdog.items():
        if bits:
            said = ", ".join(words for bit, words in _WATCHDOG_BITS.items() if bits & bit)
            evidence.append(f"{name} boot status {bits:#x}" + (f": {said}" if said else ""))
            watchdog_reset = watchdog_reset or bool(bits & WDIOF_CARDRESET)
    fresh = [str(f["name"]) for f in pstore.get("files", []) if f.get("new")]
    crash = [name for name in fresh if name.startswith("dmesg")]
    if crash:
        evidence.append(f"the kernel left a crash record: {', '.join(crash)}")
        return KERNEL_CRASH, WHAT[KERNEL_CRASH], evidence
    if fresh:
        evidence.append(f"the kernel's messages from before the restart were kept, with no crash record: {', '.join(fresh)}")
        return RESET, WHAT[RESET], evidence
    if watchdog_reset:
        evidence.append("nothing was kept in memory")
        return RESET, "restarted without warning: the watchdog reset it", evidence
    if pstore.get("backend") and pstore.get("readable"):
        evidence.append(f"nothing was kept in memory (pstore, {pstore['backend']}, is empty)")
        return POWER_LOST, WHAT[POWER_LOST], evidence
    evidence.append(
        "pstore could not be read by this user" if pstore.get("backend") else "this kernel keeps nothing across a restart (no pstore)"
    )
    return UNEXPLAINED, WHAT[UNEXPLAINED], evidence


def _exitWords(code: int | None) -> str:
    if code is None:
        return "the backend ended"
    if code < 0:
        try:
            return f"the backend was ended by {signal.Signals(-code).name}"
        except ValueError:
            return f"the backend was ended by signal {-code}"
    return f"the backend exited with code {code}"


def _stamp(at: float | None) -> str | None:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at)) if isinstance(at, (int, float)) else None


def _span(seconds: float) -> str:
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= 2 * size:
            return f"{seconds / size:.0f} {unit}s"
    return f"{seconds:.0f} seconds"


def _say(message: str) -> None:
    try:
        print(f"[supervisor] {message}", flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# In the supervisor
# ---------------------------------------------------------------------------


def _harmless(method: Callable[..., Any]) -> Callable[..., Any]:
    """For what the supervisor calls: a failure in here is said once and is
    never the supervisor's."""

    def call(self: "Recorder", *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:
            self._sayOnce(method.__name__, exc)
            return None

    return call


class Recorder:
    """The supervisor's side. Its own thread does all the reading and writing;
    what the supervisor calls only takes notes, so a disk that stops answering
    never holds up a backend restart."""

    def __init__(self, folder: Path | None = None, interval_s: float | None = None) -> None:
        self.interval_s = heartbeatSeconds() if interval_s is None else interval_s
        self.on = self.interval_s > 0
        self._folder = folder
        self._lock = threading.Lock()  # the notes below; never held while a file is written
        self._io = threading.Lock()  # the files
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._said: set[str] = set()
        # Notes
        self._pid: int | None = None
        self._starts = 0
        self._state = "starting"
        self._state_at = time.monotonic()
        self._version: str | None = None
        self._oom_kills: int | None = None
        self._asked: tuple[str, float, bool] | None = None  # (why, when, takes the computer down)
        self._beat_now = False
        self._words: deque[tuple[int, str]] = deque(maxlen=WORD_COUNT)
        self._word_count = 0
        # Set once everything the running backend wrote to its pipe is read.
        self._heard = threading.Event()
        self._records: list[dict[str, Any]] = []
        self._fast_exits = 0
        self._unrecorded = 0
        self._latest: dict[str, Any] | None = None
        # Files
        self._heartbeat: _FixedFile | None = None
        self._ring: _FixedFile | None = None
        self._seq = 0
        self._word_base = 0
        self._words_written = 0
        self._next_id = 1
        self._history_lines = 0
        self._history_torn = False
        self._final = False
        # The run before
        self._began = (time.monotonic(), uptime())
        self._boot_id = bootId()
        self._previous: dict[str, Any] | None = None
        self._previous_words: list[str] = []
        self._restarted = True
        self._pstore: dict[str, Any] = {"backend": None, "readable": False, "files": []}
        self._kept: str | None = None
        self._watchdog: dict[str, int] = {}
        self._boot_record_id: int | None = None
        # The boot record, while its times are from a clock not yet synchronized.
        self._unsynced: dict[str, Any] | None = None

    # -- what the supervisor calls -----------------------------------------

    @_harmless
    def begin(self) -> None:
        if self.on:
            threading.Thread(target=self._run, name="boot-record", daemon=True).start()

    @_harmless
    def channel(self) -> int | None:
        """A pipe for the next backend to report through: its write end, for
        the supervisor to hand to the backend and then close. None when off."""
        if not self.on:
            return None
        try:
            read_fd, write_fd = os.pipe()
        except OSError:
            return None
        self._heard = threading.Event()
        threading.Thread(target=self._listen, args=(read_fd, self._heard), name="boot-record-reports", daemon=True).start()
        return write_fd

    @_harmless
    def backendStarted(self, pid: int) -> None:
        if not self.on:
            return
        version, oom_kills = codeVersion(), _oomKills()
        with self._lock:
            self._pid, self._version, self._oom_kills = pid, version, oom_kills
            self._starts += 1
            self._state, self._state_at = "starting", time.monotonic()

    def backendExited(self, code: int | None, ran_s: float | None, asked: str | None = None) -> str | None:
        """Note that the backend ended while the supervisor stays, for the
        history. Returns why, when that was asked for."""
        try:
            return self._noteExit(code, ran_s, asked)
        except Exception as exc:
            self._sayOnce("backendExited", exc)
            return asked

    def _noteExit(self, code: int | None, ran_s: float | None, asked: str | None) -> str | None:
        if not self.on or self._stop.is_set():
            return asked
        oom_kills = _oomKills() if code == -signal.SIGKILL else None
        now = time.time()
        with self._lock:
            pending = self._asked
            if asked is None and pending is not None and time.monotonic() - pending[1] <= ASKED_FOR_S:
                asked = pending[0]
            if pending is not None and not pending[2]:
                self._asked = None
            state, self._state, self._state_at = self._state, "not running", time.monotonic()
            self._pid = None
            self._fast_exits = self._fast_exits + 1 if ran_s is not None and ran_s < FAST_EXIT_S else 0
            if (asked is None and self._fast_exits > FAST_EXITS_RECORDED) or len(self._records) >= RECORDS_WAITING:
                self._unrecorded += 1
                return asked
            evidence = [_exitWords(code)]
            if oom_kills is not None and self._oom_kills is not None and oom_kills > self._oom_kills:
                evidence.append("the kernel's out-of-memory killer ran")
            if asked is not None:
                evidence.append(f"asked for: {asked}")
            kind = ASKED if asked is not None else BACKEND
            record = {
                "at": round(now, 2),
                "time": _stamp(now),
                "kind": kind,
                "what": WHAT[kind],
                "by_itself": asked is None,
                "computer_restarted": False,
                "evidence": evidence,
                "last_alive": round(now, 2),
                "last_alive_time": _stamp(now),
                "dark_s": None,
                "ran_s": round(ran_s) if ran_s is not None else None,
                "before": {**{key: (self._latest or {}).get(key) for key in _BEFORE}, "state": state},
                "stopped": asked,
                "last_words": self._heard,  # filled in once its last lines are read (_writeRecords)
                "version": self._version,
            }
            if self._unrecorded:
                record["exits_not_recorded"], self._unrecorded = self._unrecorded, 0
            self._records.append(record)
        self._wake.set()
        return asked

    @_harmless
    def asked(self, why: str, computer: bool = False) -> None:
        """A stop that was asked for is coming. One that takes the computer
        down goes into the heartbeat at once."""
        if not self.on:
            return
        with self._lock:
            self._asked = (why, time.monotonic(), computer)
            self._beat_now = self._beat_now or computer
        if computer:
            self._wake.set()

    def stopping(self, why: str) -> None:
        """The supervisor is going: leave the mark on the disk before it does."""
        self._stop.set()
        self._wake.set()
        if not self.on:
            return
        if not self._io.acquire(timeout=STOP_WAIT_S):
            _say("boot record: the stop mark was not written, the disk did not answer")
            return
        try:
            self._bootRecord()
            self._writeRecords()
            self._beat(stopped=self._mark() or why)
        except Exception as exc:
            _say(f"boot record: the stop mark was not written: {exc}")
        finally:
            self._io.release()

    @_harmless
    def report(self, message: dict[str, Any]) -> None:
        """One line from the backend: its state, a warning line, or a stop."""
        with self._lock:
            if "s" in message:
                self._state, self._state_at = str(message["s"])[:40], time.monotonic()
            if "w" in message:
                self._word_count += 1
                self._words.append((self._word_count, str(message["w"])[:WORD_CHARS]))
        if "stop" in message:
            self.asked(str(message["stop"])[:80], computer=bool(message.get("computer")))

    # -- its own thread ----------------------------------------------------

    def _run(self) -> None:
        if not self._guard(self._load):
            self.on = False
            return
        next_beat = 0.0
        while not self._stop.is_set():
            self._wake.clear()
            with self._lock:
                due = self._beat_now or time.monotonic() >= next_beat
            self._guard(self._write, due)
            if due:
                next_beat = time.monotonic() + self.interval_s
            self._wake.wait(max(0.0, next_beat - time.monotonic()))

    def _guard(self, step: Callable[..., None], *args: Any) -> bool:
        try:
            step(*args)
            return True
        except Exception as exc:
            self._sayOnce(step.__name__, exc)
            return False

    def _sayOnce(self, step: str, exc: Exception) -> None:
        if step not in self._said:
            self._said.add(step)
            _say(f"boot record: {step.strip('_')} failed, and is not said again: {type(exc).__name__}: {exc}")

    def _listen(self, fd: int, heard: threading.Event) -> None:
        try:
            with os.fdopen(fd, "rb") as pipe:
                for raw in pipe:
                    try:
                        message = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(message, dict):
                        self.report(message)
        except Exception:
            pass
        finally:
            heard.set()

    def _load(self) -> None:
        """Read what the last run left, before anything here overwrites it."""
        with self._io:
            folder = self._folder or directory()
            folder.mkdir(parents=True, exist_ok=True)
            self._folder = folder
            self._previous = readHeartbeat(folder)
            words = readWords(folder)
            self._previous_words = [text for _n, text in words[-RECORD_WORDS:]]
            self._word_base = words[-1][0] if words else 0
            self._seq = self._previous["seq"] if self._previous else 0
            try:
                raw = (folder / HISTORY_FILE).read_bytes()
            except OSError:
                raw = b""
            self._history_lines = raw.count(b"\n")
            self._history_torn = bool(raw) and not raw.endswith(b"\n")
            history = readHistory(folder)
            self._boot_record_id = max((r["id"] for r in history if isinstance(r.get("id"), int)), default=0) + 1
            self._next_id = self._boot_record_id + 1
            self._restarted = computerRestarted(self._previous, self._boot_id, self._began[1])
            self._heartbeat = _FixedFile(folder / HEARTBEAT_FILE, 2 * SLOT_BYTES)
            self._ring = _FixedFile(folder / WORDS_FILE, WORD_COUNT * WORD_BYTES)
            _syncFolder(folder)
            if self._restarted:
                listed = next((r.get("pstore") for r in reversed(history) if r.get("computer_restarted")), None)
                seen = {str(f.get("sha1")) for f in listed or [] if isinstance(f, dict)}
                self._pstore = readPstore(seen)
                self._watchdog = readWatchdog()
                self._kept = self._keepPstore(self._pstore["files"], self._boot_record_id)

    def _keepPstore(self, files: list[dict[str, Any]], record_id: int) -> str | None:
        fresh = [f for f in files if f["new"]]
        kept: str | None = None
        try:
            if fresh:
                assert self._folder is not None
                root = self._folder / PSTORE_FOLDER
                name = f"{record_id:06d}-{time.strftime('%Y%m%d-%H%M%S')}"
                (root / name).mkdir(parents=True, exist_ok=True)
                for index, f in enumerate(fresh):
                    path = root / name / str(f["name"])
                    with open(root / name / f"{index}-{f['name']}" if path.exists() else path, "wb") as out:
                        out.write(f["data"])
                        out.flush()
                        os.fsync(out.fileno())
                _syncFolder(root / name)
                _syncFolder(root)
                kept = f"{PSTORE_FOLDER}/{name}"
                for old in sorted(p for p in root.iterdir() if p.is_dir())[:-PSTORE_KEEP]:
                    shutil.rmtree(old, ignore_errors=True)
        except OSError as exc:
            _say(f"boot record: what the kernel kept was not copied: {exc}")
        for f in files:
            f.pop("data", None)
        return kept

    def _write(self, beat: bool) -> None:
        with self._io:
            self._bootRecord()
            self._fixClock()
            self._writeRecords()
            if beat:
                self._beat()

    def _mark(self) -> str | None:
        """Why the computer is about to go down, if the backend said so."""
        with self._lock:
            asked = self._asked
        return asked[0] if asked is not None and asked[2] and time.monotonic() - asked[1] <= ASKED_FOR_S else None

    def _bootRecord(self) -> None:
        """This start's line of the history: what the last run left, and what
        that says about why it ended."""
        if self._boot_record_id is None:
            return
        record_id, self._boot_record_id = self._boot_record_id, None
        previous = self._previous
        kind, what, evidence = classify(previous, self._restarted, self._pstore, self._watchdog)
        alive = previous.get("t") if previous else None
        synced = clockSynced()
        record = {
            "id": record_id,
            **self._times(synced),
            "kind": kind,
            "what": what,
            "by_itself": kind in BY_ITSELF,
            "computer_restarted": self._restarted,
            "evidence": evidence,
            "last_alive": alive,
            "last_alive_time": _stamp(alive),
            "last_alive_clock_synced": previous.get("clock_synced") if previous else None,
            "uptime_s": round(self._began[1]),
            "before": {key: previous.get(key) for key in _BEFORE} if previous else None,
            "stopped": previous.get("stopped") if previous else None,
            "last_words": self._previous_words,
            "pstore": self._pstore["files"],
            "pstore_kept": self._kept,
            "watchdog": self._watchdog,
            "version": codeVersion(),
        }
        try:
            self._append(record)
        except Exception:
            self._boot_record_id = record_id  # tried again with the next heartbeat
            raise
        self._unsynced = record if synced is False else None
        dark = record["dark_s"]
        before = record["before"] or {}
        line = f"boot record: {what}"
        if alive is not None:
            line += (
                f"; last alive {record['last_alive_time']} ({before.get('state')}, memory {before.get('mem_used_pct')}%, "
                f"backend {before.get('backend_rss_mb')} MB, {before.get('temp_c')} °C, load {before.get('load1')})"
            )
        if dark is not None:
            line += f", dark for {_span(dark)}"
        if synced is False:
            line += " (the clock is not synchronized yet, so the times may be off)"
        _say(("WARN " if kind in BY_ITSELF else "") + line)
        _say(("WARN " if kind in BY_ITSELF else "") + f"boot record: evidence: {'; '.join(evidence)}" + (f"; kept in {self._kept}" if self._kept else ""))

    def _times(self, synced: bool | None) -> dict[str, Any]:
        """When this start was, and how long the machine was dark before it,
        on the clock as it is set by now. Dark for an unknown time when the
        clock reads earlier than the last heartbeat (a computer without a
        clock of its own, before the network has set it)."""
        at = time.time() - (time.monotonic() - self._began[0])
        alive = (self._previous or {}).get("t")
        known = isinstance(alive, (int, float)) and at >= alive
        return {"at": round(at, 2), "time": _stamp(at), "dark_s": round(at - alive) if known else None, "clock_synced": synced}

    def _fixClock(self) -> None:
        """The boot record was written before the clock was synchronized: once
        it is, put the record's times right."""
        record = self._unsynced
        if record is None or clockSynced() is not True:
            return
        self._unsynced = None
        record.update(self._times(True))

        def put(lines: list[bytes]) -> list[bytes]:
            for index in range(len(lines) - 1, -1, -1):
                try:
                    found = json.loads(lines[index]).get("id") == record["id"]
                except (ValueError, AttributeError):
                    found = False
                if found:
                    lines[index] = _line(record)
                    break
            return lines

        self._rewriteHistory(put)
        dark = record["dark_s"]
        _say(f"boot record: the clock is synchronized now: this start was at {record['time']}" + (f", dark for {_span(dark)}" if dark is not None else ""))

    def _writeRecords(self) -> None:
        while True:
            with self._lock:
                record = self._records[0] if self._records else None
            if record is None:
                return
            heard = record["last_words"]
            if isinstance(heard, threading.Event):
                # The backend's last lines can still be in its pipe.
                heard.wait(0.5)
                with self._lock:
                    record["last_words"] = [text for _n, text in list(self._words)[-RECORD_WORDS:]]
            self._append(record)
            with self._lock:
                self._records.remove(record)
            _say(("WARN " if record["kind"] in BY_ITSELF else "") + f"boot record: {record['what']}: {'; '.join(record['evidence'])}")

    def _append(self, record: dict[str, Any]) -> None:
        assert self._folder is not None
        if "id" not in record:
            record["id"] = self._next_id
            self._next_id += 1
        fd = os.open(self._folder / HISTORY_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (b"\n" if self._history_torn else b"") + _line(record) + b"\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        self._history_torn = False
        self._history_lines += 1
        if self._history_lines > HISTORY_KEEP + HISTORY_SLACK:
            try:
                self._rewriteHistory(lambda lines: lines[-HISTORY_KEEP:])
            except OSError:
                pass  # the line is written; trimmed with a later one

    def _rewriteHistory(self, change: Callable[[list[bytes]], list[bytes]]) -> None:
        assert self._folder is not None
        path = self._folder / HISTORY_FILE
        lines = change(path.read_bytes().splitlines())
        fresh = path.with_suffix(".tmp")
        with open(fresh, "wb") as out:
            out.write(b"".join(line + b"\n" for line in lines))
            out.flush()
            os.fsync(out.fileno())
        os.replace(fresh, path)
        _syncFolder(self._folder)
        self._history_lines = len(lines)
        self._history_torn = False

    def _beat(self, stopped: str | None = None) -> None:
        if self._final or self._heartbeat is None or self._ring is None:
            return
        now = time.time()
        with self._lock:
            pid, starts, version = self._pid, self._starts, self._version
            state, state_age = self._state, time.monotonic() - self._state_at
            self._beat_now = False
            words = [word for word in self._words if word[0] > self._words_written]
        beat = {
            "seq": self._seq + 1,
            "t": round(now, 2),
            "time": _stamp(now),
            "uptime_s": round(uptime(), 1),
            "boot_id": self._boot_id,
            "state": state,
            "state_age_s": round(state_age),
            **readings(pid),
            "version": version,
            "backend_pid": pid,
            "backend_starts": starts,
            "clock_synced": clockSynced(),
            "stopped": stopped or self._mark(),
        }
        self._seq += 1
        self._heartbeat.write((self._seq % 2) * SLOT_BYTES, _slot(beat))
        self._heartbeat.sync()
        self._final = stopped is not None
        with self._lock:
            self._latest = beat
        if words:
            for number, text in words:
                self._ring.write(((self._word_base + number) % WORD_COUNT) * WORD_BYTES, _wordLine(self._word_base + number, text))
            self._ring.sync()
            self._words_written = words[-1][0]


# ---------------------------------------------------------------------------
# In the backend
# ---------------------------------------------------------------------------


_report_fd: int | None = None
_report_fd_read = False


def _reportFd() -> int | None:
    """The pipe to the supervisor, when the supervisor started this backend."""
    global _report_fd, _report_fd_read
    if not _report_fd_read:
        _report_fd_read = True
        try:
            # Taken out of the environment: the number means nothing to a
            # program this backend starts.
            fd = int(os.environ.pop(REPORT_FD_ENV, ""))
            if stat.S_ISFIFO(os.fstat(fd).st_mode):
                os.set_blocking(fd, False)
                os.set_inheritable(fd, False)
                _report_fd = fd
        except (OSError, ValueError):
            pass
    return _report_fd


def _send(message: dict[str, Any]) -> None:
    """Never waits: with the pipe full the line is dropped."""
    global _report_fd
    fd = _reportFd()
    if fd is None:
        return
    try:
        os.write(fd, json.dumps(message, separators=(",", ":")).encode() + b"\n")
    except BlockingIOError:
        pass
    except OSError:
        _report_fd = None  # the supervisor is gone


def announceStop(why: str, computer: bool = False) -> None:
    """Say that the stop about to come was asked for (`computer`: it takes the
    whole computer down), so the next start is not taken for a failure."""
    _send({"stop": why, "computer": computer})


def sorterState() -> str:
    """What the sorter is doing, in one word: standby, homing, sorting, paused, ..."""
    from server import shared_state

    hardware = shared_state.hardware_state
    state = getattr(getattr(shared_state.controller_ref, "state", None), "value", None)
    if hardware != "ready" or state is None:
        return hardware
    return "sorting" if state == "running" else str(state)


_history_cache: tuple[Any, list[dict[str, Any]]] = (None, [])


def history() -> list[dict[str, Any]]:
    """Every record kept, oldest first; read again only when the file changed.
    The list is shared: do not change it."""
    global _history_cache
    key = None
    try:
        folder = directory()
        info = os.stat(folder / HISTORY_FILE)
        key = (info.st_mtime_ns, info.st_size)
    except OSError:
        pass
    if key != _history_cache[0]:
        _history_cache = (key, readHistory(folder) if key else [])
    return _history_cache[1]


def lastRestart() -> dict[str, Any] | None:
    """The newest record in short, for the system status."""
    records = history()
    if not records:
        return None
    record = records[-1]
    keys = ("id", "at", "kind", "what", "by_itself", "computer_restarted", "last_alive", "dark_s")
    return {key: record.get(key) for key in keys}


def _readSeen(folder: Path) -> dict[str, int]:
    try:
        seen = json.loads((folder / SEEN_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in seen.items() if isinstance(v, int)} if isinstance(seen, dict) else {}


def markSeen(warning: str, record_id: Any) -> None:
    """The operator pressed Done on this warning: it stays away for the
    restarts up to this record."""
    folder = directory()
    seen = _readSeen(folder)
    newest = max((r["id"] for r in history() if isinstance(r.get("id"), int)), default=0)
    seen[warning] = max(seen.get(warning, 0), record_id if isinstance(record_id, int) else newest)
    fresh = folder / (SEEN_FILE + ".tmp")
    fresh.write_text(json.dumps(seen))
    os.replace(fresh, folder / SEEN_FILE)


def restartDetail(records: list[dict[str, Any]]) -> str:
    """What the warning's card says about the newest of these restarts."""
    record = records[-1]
    before = record.get("before") or {}
    figures = [str(before["state"])] if before.get("state") else []
    if isinstance(before.get("mem_used_pct"), (int, float)):
        figures.append(f"memory {before['mem_used_pct']:.0f}% used")
    if isinstance(before.get("backend_rss_mb"), (int, float)):
        figures.append(f"the backend held {before['backend_rss_mb']:.0f} MB")
    if isinstance(before.get("temp_c"), (int, float)):
        figures.append(f"{before['temp_c']:.0f} °C")
    doing = f" ({', '.join(figures)})" if figures else ""
    clock = lambda at: time.strftime("%H:%M on %b %d", time.localtime(at)) if isinstance(at, (int, float)) else "an unknown time"
    if record.get("computer_restarted"):
        text = f"It was last alive at {clock(record.get('last_alive'))}{doing} and came back at {clock(record.get('at'))}"
        if isinstance(record.get("dark_s"), (int, float)):
            text += f", {_span(record['dark_s'])} later"
        text += f". As far as it can tell: {record.get('what')}."
    else:
        why = "; ".join(str(e) for e in (record.get("evidence") or [])[:2]) or str(record.get("what"))
        text = f"It stopped at {clock(record.get('at'))}{doing} and was started again; the computer stayed up. As far as it can tell: {why}."
        last = [str(line) for line in (record.get("last_words") or [])[-1:] if "[FATAL]" in str(line)]
        if last:
            text += f" Its last line: {last[0][:200]}"
    if record.get("clock_synced") is False or record.get("last_alive_clock_synced") is False:
        text += " The computer's clock was not synchronized, so these times may be off."
    if len(records) > 1:
        more = len(records) - 1
        text += f" It happened {more} more time{'s' if more > 1 else ''} before that."
    return text


class Reporter:
    """The backend's side: every REPORT_TICK_S, on a thread of its own, it
    hands the supervisor the new warning and error lines and what the sorter
    is doing, and looks for a restart nobody asked for to warn about."""

    def __init__(self, gc: Any) -> None:
        self._gc = gc
        self._sent = 0
        self._state: str | None = None
        self._state_at = 0.0
        self._raised_for: Any = None
        self._failed = False

    def start(self) -> None:
        earlier = sys.excepthook

        def lastWords(kind: Any, value: Any, trace: Any) -> None:
            # The backend is ending on an exception: its last line.
            try:
                self.flush()
                where, last = "", trace
                while last is not None and last.tb_next is not None:
                    last = last.tb_next
                if last is not None:
                    where = f" at {os.path.basename(last.tb_frame.f_code.co_filename)}:{last.tb_lineno}"
                _send({"w": f"[{_stamp(time.time())}] [FATAL] the backend ended on {kind.__name__}: {value}{where}"[:WORD_CHARS]})
            except Exception:
                pass
            earlier(kind, value, trace)

        _reportFd()  # opened here, before any thread asks for it
        sys.excepthook = lastWords
        atexit.register(self.flush)
        threading.Thread(target=self._run, name="boot-report", daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exc:
                if not self._failed:
                    self._failed = True
                    self._gc.logger.warning(f"boot record: {type(exc).__name__}: {exc}")
            time.sleep(REPORT_TICK_S)

    def flush(self) -> None:
        """Hand over the warning and error lines logged since the last time."""
        problems = getattr(getattr(self._gc, "logger", None), "problems", None)
        if not problems or problems[-1][0] <= self._sent or _reportFd() is None:
            return
        for number, line in problems.copy():
            if number > self._sent:
                _send({"w": line})
                self._sent = number

    def tick(self) -> None:
        self.flush()
        if _reportFd() is not None:
            state, now = sorterState(), time.monotonic()
            if state != self._state or now - self._state_at >= STATE_EVERY_S:
                _send({"s": state})
                self._state, self._state_at = state, now
        self._raiseWarnings()

    def _raiseWarnings(self) -> None:
        records = history()
        if records is self._raised_for:
            return
        self._raised_for = records
        if not records:
            return
        import incidents

        seen = _readSeen(directory())
        for warning, computer in ((COMPUTER_WARNING, True), (BACKEND_WARNING, False)):
            fresh = [
                r
                for r in records
                if r.get("kind") in BY_ITSELF
                and bool(r.get("computer_restarted")) is computer
                and isinstance(r.get("id"), int)
                and r["id"] > seen.get(warning, 0)
            ]
            if fresh:
                incidents.report(
                    self._gc, warning, subject="", record_id=fresh[-1]["id"], restarts=len(fresh), detail=restartDetail(fresh)
                )


def start(gc: Any) -> Reporter:
    reporter = Reporter(gc)
    reporter.start()
    return reporter
