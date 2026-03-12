from datetime import datetime
import threading
import atexit
from typing import Optional, Callable, List, Dict, Any
import time


class LogEntry:
    timestamp: float
    level: str
    message: str

    def __init__(self, level: str, message: str):
        self.timestamp = time.time()
        self.level = level
        self.message = message


class Logger:
    def __init__(
        self,
        debug_level: int,
        buffer_size: int = 100,
        upload_callback: Optional[Callable[[List[LogEntry]], None]] = None,
    ):
        self.debug_level = debug_level
        self.buffer_size = buffer_size
        self.upload_callback = upload_callback
        self._buffer: List[LogEntry] = []
        self._buffer_lock = threading.Lock()

        atexit.register(self._cleanup)

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _addToBuffer(self, entry: LogEntry) -> None:
        with self._buffer_lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self.buffer_size:
                self._flushBuffer()

    def _flushBuffer(self) -> None:
        if not self._buffer or self.upload_callback is None:
            return

        entries_to_upload = self._buffer.copy()
        self._buffer.clear()

        thread = threading.Thread(
            target=self.upload_callback,
            args=(entries_to_upload,),
            daemon=True,
        )
        thread.start()

    def error(self, msg: str, **kwargs) -> None:
        entry = LogEntry("ERROR", msg)
        self._addToBuffer(entry)
        print(f"[{self._timestamp()}] [ERROR] {msg}")

    def warn(self, msg: str, **kwargs) -> None:
        if self.debug_level > 0:
            entry = LogEntry("WARN", msg)
            self._addToBuffer(entry)
            print(f"[{self._timestamp()}] [WARN] {msg}")

    def warning(self, msg: str) -> None:
        self.warn(msg)

    def info(self, msg: str) -> None:
        if self.debug_level > 1:
            entry = LogEntry("INFO", msg)
            self._addToBuffer(entry)
            print(f"[{self._timestamp()}] [INFO] {msg}")

    def debug(self, msg: str) -> None:
        if self.debug_level > 2:
            entry = LogEntry("DEBUG", msg)
            self._addToBuffer(entry)
            print(f"[{self._timestamp()}] [DEBUG] {msg}")

    def flushLogs(self) -> None:
        with self._buffer_lock:
            self._flushBuffer()

    def _cleanup(self) -> None:
        # bug: at exit not all remaining logs get flushed
        self.flushLogs()
