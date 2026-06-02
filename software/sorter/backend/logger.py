from datetime import datetime
import queue
import threading
import atexit
from typing import Optional


class Logger:
    def __init__(
        self,
        debug_level: int,
        log_file: Optional[str] = None,
    ):
        self.debug_level = debug_level
        self._log_file = None
        if log_file:
            self._log_file = open(log_file, "a")

        # Log I/O (print -> journald stdout pipe, file write+flush) used to run
        # synchronously on the calling thread. The main loop logs on its hot
        # path (gate/ready spam every tick), so when the journald pipe backed
        # up — which it does under the 4K perception flood + CPU saturation —
        # print() blocked the main thread for 18-30s, stalling the whole
        # machine and freezing the frontend. Now callers only drop a formatted
        # line onto a bounded queue; a single daemon thread does the actual
        # I/O. If the writer can't keep up the queue saturates and we DROP
        # lines (counted) rather than ever block a producer. Dropped logs are
        # the right trade vs. freezing the sorter.
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=20000)
        self._dropped = 0
        self._writer = threading.Thread(
            target=self._drain, name="logger-writer", daemon=True
        )
        self._writer.start()

        atexit.register(self._cleanup)

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _drain(self) -> None:
        last_dropped = 0
        while True:
            line = self._queue.get()
            if line is None:
                break
            # Surface drops so a flood is visible rather than silent.
            dropped = self._dropped
            if dropped != last_dropped:
                notice = (
                    f"[{self._timestamp()}] [WARN] logger dropped "
                    f"{dropped - last_dropped} line(s) under load"
                )
                last_dropped = dropped
                self._write(notice)
            self._write(line)

    def _write(self, line: str) -> None:
        try:
            print(line, flush=True)
            if self._log_file:
                self._log_file.write(line + "\n")
                self._log_file.flush()
        except Exception:
            pass

    def _log(self, level: str, msg: str) -> None:
        line = f"[{self._timestamp()}] [{level}] {msg}"
        try:
            self._queue.put_nowait(line)
        except queue.Full:
            # Never block a producer (esp. the main loop). Drop and count.
            self._dropped += 1

    def _formatMessage(self, msg: str, *args, **kwargs) -> str:
        if args:
            try:
                msg = msg % args
            except Exception:
                msg = " ".join([msg, *[str(arg) for arg in args]])
        if kwargs:
            try:
                msg = msg.format(**kwargs)
            except Exception:
                extras = " ".join(f"{key}={value!r}" for key, value in kwargs.items())
                if extras:
                    msg = f"{msg} {extras}"
        return msg

    def error(self, msg: str, *args, **kwargs) -> None:
        msg = self._formatMessage(msg, *args, **kwargs)
        self._log("ERROR", msg)

    def warn(self, msg: str, *args, **kwargs) -> None:
        if self.debug_level > 0:
            msg = self._formatMessage(msg, *args, **kwargs)
            self._log("WARN", msg)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self.warn(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        if self.debug_level > 1:
            msg = self._formatMessage(msg, *args, **kwargs)
            self._log("INFO", msg)

    def debug(self, msg: str, *args, **kwargs) -> None:
        if self.debug_level > 2:
            msg = self._formatMessage(msg, *args, **kwargs)
            self._log("DEBUG", msg)

    def flushLogs(self) -> None:
        pass

    def _cleanup(self) -> None:
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        if self._writer.is_alive():
            self._writer.join(timeout=2.0)
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
