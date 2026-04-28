from datetime import datetime
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

        atexit.register(self._cleanup)

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _log(self, level: str, msg: str) -> None:
        line = f"[{self._timestamp()}] [{level}] {msg}"
        print(line)
        if self._log_file:
            self._log_file.write(line + "\n")
            self._log_file.flush()

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
        if self._log_file:
            self._log_file.close()
