import threading
from typing import Optional, TypeVar
from enum import Enum
from .istate_machine import IStateMachine
from irl.config import IRLInterface
from global_config import GlobalConfig

THREAD_STOP_TIMEOUT_S = 2.0

T = TypeVar("T", bound=Enum)


class BaseState(IStateMachine[T]):
    def __init__(self, irl: IRLInterface, gc: GlobalConfig):
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self._execution_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def step(self) -> Optional[T]:
        return None

    def cleanup(self) -> None:
        self._stop_execution_thread()

    def _ensure_execution_thread_started(self) -> None:
        if self._execution_thread is None or not self._execution_thread.is_alive():
            self._stop_event.clear()
            self._execution_thread = threading.Thread(
                target=self._execution_loop, daemon=True
            )
            self._execution_thread.start()

    def _execution_loop(self) -> None:
        pass

    def _stop_execution_thread(self) -> None:
        if self._execution_thread is not None and self._execution_thread.is_alive():
            self._stop_event.set()
            self._execution_thread.join(timeout=THREAD_STOP_TIMEOUT_S)
