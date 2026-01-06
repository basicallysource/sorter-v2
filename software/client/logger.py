from datetime import datetime


class Logger:
    def __init__(self, debug_level: int):
        self.debug_level = debug_level

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def error(self, msg: str) -> None:
        print(f"[{self._timestamp()}] [ERROR] {msg}")

    def warn(self, msg: str) -> None:
        if self.debug_level > 0:
            print(f"[{self._timestamp()}] [WARN] {msg}")

    def info(self, msg: str) -> None:
        if self.debug_level > 1:
            print(f"[{self._timestamp()}] [INFO] {msg}")
