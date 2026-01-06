from datetime import datetime


class Logger:
    def __init__(self, debug_level):
        self.debug_level = debug_level

    def _timestamp(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def error(self, msg):
        print(f"[{self._timestamp()}] [ERROR] {msg}")

    def warn(self, msg):
        if self.debug_level > 0:
            print(f"[{self._timestamp()}] [WARN] {msg}")

    def info(self, msg):
        if self.debug_level > 1:
            print(f"[{self._timestamp()}] [INFO] {msg}")
