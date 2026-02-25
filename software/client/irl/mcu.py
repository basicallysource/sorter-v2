import serial
import time
import queue
import threading
from typing import Callable
from global_config import GlobalConfig

COMMAND_QUEUE_TIMEOUT_MS = 1000
READER_SLEEP_MS = 10
ARDUINO_RESET_DELAY_MS = 2000
COMMAND_WRITE_DELAY_MS = 50
COMMAND_ID_START = 1
COMMAND_ID_MAX = 2_000_000_000


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
        self.worker_dead_logged = False
        self.next_command_id = COMMAND_ID_START
        self.pending_command_results: dict[int, dict] = {}
        self.pending_command_lock = threading.Lock()
        self.outstanding_t_count = 0
        self.outstanding_t_lock = threading.Lock()
        self.outstanding_t_drained = threading.Event()
        self.outstanding_t_drained.set()

        self.worker_thread = threading.Thread(target=self._processCommands, daemon=True)
        self.worker_thread.start()

        self.reader_thread = threading.Thread(target=self._readResponses, daemon=True)
        self.reader_thread.start()

        gc.logger.info(f"MCU initialized on {port}")

    def _allocateCommandId(self) -> int:
        with self.pending_command_lock:
            cmd_id = self.next_command_id
            self.next_command_id += 1
            if self.next_command_id > COMMAND_ID_MAX:
                self.next_command_id = COMMAND_ID_START
        return cmd_id

    def command(self, *args) -> int:
        if self.running:
            if not self.worker_thread.is_alive() and not self.worker_dead_logged:
                self.gc.logger.error(
                    "MCU command worker is not alive; queued commands will not be sent"
                )
                self.worker_dead_logged = True

            cmd_id = self._allocateCommandId()
            self.command_queue.put((cmd_id, args))
            queue_size = self.command_queue.qsize()
            if queue_size > 10:
                self.gc.logger.warn(
                    f"MCU command queue size is large: {queue_size} commands pending"
                )

            if queue_size > 3 and len(args) > 0 and args[0] == "T":
                self.gc.logger.warn(
                    f"MCU stepper command queued with backlog: {queue_size} commands pending"
                )
            return cmd_id
        return -1

    def commandBlocking(self, *args, timeout_ms: int) -> str:
        if not self.running:
            raise RuntimeError("MCU not running")
        if timeout_ms <= 0:
            raise RuntimeError("timeout_ms must be > 0")

        cmd_id = self._allocateCommandId()
        sent_event = threading.Event()
        pending = {
            "event": threading.Event(),
            "sent_event": sent_event,
            "ok": None,
            "line": None,
        }
        with self.pending_command_lock:
            self.pending_command_results[cmd_id] = pending

        cmd_type = str(args[0]) if len(args) > 0 else "UNKNOWN"
        cmd_payload = ",".join(map(str, args))
        self.gc.logger.info(
            f"MCU blocking command queued id={cmd_id} timeout_ms={timeout_ms} cmd={cmd_payload}"
        )

        self.command_queue.put((cmd_id, args))

        # wait for worker to actually send the command before starting timeout
        sent_event.wait()

        if pending["event"].wait(timeout_ms / 1000.0):
            with self.pending_command_lock:
                self.pending_command_results.pop(cmd_id, None)
            if pending["ok"]:
                self.gc.logger.info(f"MCU blocking command ok id={cmd_id} type={cmd_type}")
                return str(pending["line"])
            self.gc.logger.error(f"MCU blocking command failed id={cmd_id} type={cmd_type}")
            raise RuntimeError(f"MCU command {cmd_id} failed: {pending['line']}")

        with self.pending_command_lock:
            self.pending_command_results.pop(cmd_id, None)
        self.gc.logger.error(f"MCU blocking command timed out id={cmd_id} type={cmd_type}")
        raise RuntimeError(f"MCU command {cmd_id} timed out after {timeout_ms}ms: {args}")

    def registerCallback(self, message_type: str, callback: Callable) -> None:
        self.callbacks[message_type] = callback

    def _processCommands(self) -> None:
        while self.running:
            try:
                cmd_item = self.command_queue.get(
                    timeout=COMMAND_QUEUE_TIMEOUT_MS / 1000.0
                )
                if not self.running:
                    break
                cmd_id, cmd_args = cmd_item
                cmd_payload = ",".join(map(str, cmd_args))
                cmd_str = f"{cmd_id}|{cmd_payload}\n"

                with self.pending_command_lock:
                    pending = self.pending_command_results.get(cmd_id)
                is_blocking = pending is not None and "sent_event" in pending

                # blocking commands wait for Arduino to finish all prior T commands
                if is_blocking:
                    self.outstanding_t_drained.wait()

                self.serial.write(cmd_str.encode())
                self.serial.flush()

                is_t_cmd = len(cmd_args) > 0 and cmd_args[0] == "T"
                if is_t_cmd:
                    with self.outstanding_t_lock:
                        self.outstanding_t_count += 1
                        self.outstanding_t_drained.clear()

                if is_blocking and pending is not None:
                    pending["sent_event"].set()

                time.sleep(COMMAND_WRITE_DELAY_MS / 1000.0)
                self.command_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self.gc.logger.error(
                    f"Error in command thread: {e} (queue_size={self.command_queue.qsize()})"
                )
                break

    def _readResponses(self) -> None:
        while self.running:
            try:
                if not self.running:
                    break
                if self.serial.in_waiting > 0:
                    line = self.serial.readline().decode().strip()
                    if line:
                        self._handleMcuLineResult(line)
                        parts = line.split(",")
                        if len(parts) > 0 and parts[0] in self.callbacks:
                            self.callbacks[parts[0]](parts[1:])
                        elif line.startswith("ERR,"):
                            self.gc.logger.error(f"Arduino: {line}")
                        else:
                            self.gc.logger.info(f"Arduino: {line}")

            except Exception as e:
                if self.running:
                    self.gc.logger.error(f"Error reading from MCU: {e}")
                break
            time.sleep(READER_SLEEP_MS / 1000.0)

    def _resolvePendingCommand(self, cmd_id: int, ok: bool, line: str) -> None:
        with self.pending_command_lock:
            pending = self.pending_command_results.get(cmd_id)
        if pending is None:
            return
        pending["ok"] = ok
        pending["line"] = line
        pending["event"].set()

    def _decrementOutstandingT(self) -> None:
        with self.outstanding_t_lock:
            if self.outstanding_t_count > 0:
                self.outstanding_t_count -= 1
            if self.outstanding_t_count == 0:
                self.outstanding_t_drained.set()

    def _handleMcuLineResult(self, line: str) -> None:
        if line.startswith("ERR,"):
            parts = line.split(",", 3)
            if len(parts) >= 4:
                err_type = parts[1]
                if err_type == "T":
                    self._decrementOutstandingT()
                try:
                    cmd_id = int(parts[2])
                    self._resolvePendingCommand(cmd_id, False, line)
                except ValueError:
                    pass
            return

        if not line.startswith("T done "):
            return

        self._decrementOutstandingT()

        for token in line.split():
            if token.startswith("id="):
                try:
                    cmd_id = int(token[3:])
                    self._resolvePendingCommand(cmd_id, True, line)
                except ValueError:
                    pass
                return

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
