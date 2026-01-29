import serial
import time
import queue
import threading
from typing import Callable
from global_config import GlobalConfig

COMMAND_QUEUE_TIMEOUT_MS = 1000
READER_SLEEP_MS = 10
ARDUINO_RESET_DELAY_MS = 2000
COMMAND_WRITE_DELAY_MS = 15


class MCU:
    def __init__(self, gc: GlobalConfig, port: str, baud_rate: int = 115200):
        self.gc = gc
        self.port = port
        self.baud_rate = baud_rate
        self.serial = serial.Serial(port, baud_rate, timeout=1)
        time.sleep(ARDUINO_RESET_DELAY_MS / 1000.0)

        self.command_queue: queue.Queue = queue.Queue()
        self.running = True
        self.callbacks: dict[str, Callable] = {}

        self.worker_thread = threading.Thread(target=self._processCommands, daemon=True)
        self.worker_thread.start()

        self.reader_thread = threading.Thread(target=self._readResponses, daemon=True)
        self.reader_thread.start()

        gc.logger.info(f"MCU initialized on {port}")

    def command(self, *args) -> None:
        if self.running:
            self.command_queue.put(args)
            queue_size = self.command_queue.qsize()
            if queue_size > 10:
                self.gc.logger.warn(
                    f"MCU command queue size is large: {queue_size} commands pending"
                )

    def registerCallback(self, message_type: str, callback: Callable) -> None:
        self.callbacks[message_type] = callback

    def _processCommands(self) -> None:
        while self.running:
            try:
                cmd_args = self.command_queue.get(
                    timeout=COMMAND_QUEUE_TIMEOUT_MS / 1000.0
                )
                if not self.running:
                    break
                cmd_str = ",".join(map(str, cmd_args)) + "\n"

                self.serial.write(cmd_str.encode())
                time.sleep(COMMAND_WRITE_DELAY_MS / 1000.0)
                self.command_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self.gc.logger.error(f"Error in command thread: {e}")
                break

    def _readResponses(self) -> None:
        while self.running:
            try:
                if not self.running:
                    break
                if self.serial.in_waiting > 0:
                    line = self.serial.readline().decode().strip()
                    if line:
                        parts = line.split(",")
                        if len(parts) > 0 and parts[0] in self.callbacks:
                            self.callbacks[parts[0]](parts[1:])
                        else:
                            self.gc.logger.info(f"Arduino: {line}")

            except Exception as e:
                if self.running:
                    self.gc.logger.error(f"Error reading from MCU: {e}")
                break
            time.sleep(READER_SLEEP_MS / 1000.0)

    def flush(self) -> None:
        self.command_queue.join()

    def close(self) -> None:
        self.gc.logger.info("Closing MCU connection...")
        self.running = False

        # clear the command queue immediately
        while not self.command_queue.empty():
            try:
                self.command_queue.get_nowait()
                self.command_queue.task_done()
            except queue.Empty:
                break

        try:
            if self.serial and self.serial.is_open:
                self.serial.close()
        except Exception as e:
            self.gc.logger.error(f"Error closing serial port: {e}")

        self.gc.logger.info("MCU connection closed")
