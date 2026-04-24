"""Continuous C-channel transport for teacher-sample collection.

This maintenance service intentionally bypasses sorting/admission decisions:
the orchestrator is paused, perception keeps running, and C1/C2/C3/C4 are
driven by channel-local sample-transport ports. Move-completed events still
flow through the normal event bus, so the teacher sample collector captures
motion-triggered frames with the same metadata as regular runtime moves.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol


_LOG = logging.getLogger(__name__)

DEFAULT_BASE_INTERVAL_S = 2.0
DEFAULT_RATIO = 2.0
DEFAULT_DURATION_S = 600.0
DEFAULT_POLL_S = 0.02
MIN_INTERVAL_S = 0.08
MAX_DURATION_S = 3600.0


class RuntimeControl(Protocol):
    paused: bool

    def pause(self) -> None: ...

    def resume(self) -> None: ...


class SampleTransportPort(Protocol):
    key: str

    def step(self, now_mono: float) -> bool: ...


@dataclass(slots=True)
class _ChannelState:
    key: str
    port: SampleTransportPort
    interval_s: float
    next_at_mono: float
    step_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    last_step_at: float | None = None
    last_skip_at: float | None = None
    last_error: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "interval_s": self.interval_s,
            "step_count": self.step_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "last_step_at": self.last_step_at,
            "last_skip_at": self.last_skip_at,
            "last_error": self.last_error,
        }


def _initial_status() -> dict[str, Any]:
    return {
        "active": False,
        "phase": "idle",
        "started_at": None,
        "finished_at": None,
        "success": None,
        "reason": None,
        "was_paused": None,
        "cancel_requested": False,
        "config": {
            "base_interval_s": DEFAULT_BASE_INTERVAL_S,
            "ratio": DEFAULT_RATIO,
            "duration_s": DEFAULT_DURATION_S,
            "poll_s": DEFAULT_POLL_S,
        },
        "channels": {},
    }


class C1234SampleTransportCoordinator:
    """Owns a continuous C1/C2/C3/C4 transport worker thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._status: dict[str, Any] = _initial_status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            snap = dict(self._status)
            config = snap.get("config")
            channels = snap.get("channels")
            if isinstance(config, dict):
                snap["config"] = dict(config)
            if isinstance(channels, dict):
                snap["channels"] = {
                    str(key): dict(value) if isinstance(value, dict) else value
                    for key, value in channels.items()
                }
            return snap

    def start(
        self,
        *,
        runtimes: Iterable[Any],
        control: RuntimeControl,
        state_publisher: Callable[[str], None] | None = None,
        base_interval_s: float = DEFAULT_BASE_INTERVAL_S,
        ratio: float = DEFAULT_RATIO,
        duration_s: float | None = DEFAULT_DURATION_S,
        poll_s: float = DEFAULT_POLL_S,
    ) -> bool:
        if base_interval_s <= 0.0:
            raise ValueError("base_interval_s must be > 0")
        if ratio <= 1.0:
            raise ValueError("ratio must be > 1")
        if duration_s is not None and duration_s <= 0.0:
            raise ValueError("duration_s must be > 0 when provided")
        if poll_s <= 0.0:
            raise ValueError("poll_s must be > 0")

        ports = self._collect_ports(list(runtimes))
        if not ports:
            raise RuntimeError("no sample-transport-capable C-channel runtimes available")

        channel_states = self._build_channel_states(
            ports,
            base_interval_s=float(base_interval_s),
            ratio=float(ratio),
        )
        bounded_duration = (
            None
            if duration_s is None
            else min(float(duration_s), MAX_DURATION_S)
        )

        with self._lock:
            if bool(self._status.get("active")):
                return False
            self._cancel.clear()
            self._status = {
                "active": True,
                "phase": "starting",
                "started_at": time.time(),
                "finished_at": None,
                "success": None,
                "reason": None,
                "was_paused": bool(getattr(control, "paused", False)),
                "cancel_requested": False,
                "config": {
                    "base_interval_s": float(base_interval_s),
                    "ratio": float(ratio),
                    "duration_s": bounded_duration,
                    "poll_s": float(poll_s),
                },
                "channels": {
                    state.key: state.snapshot() for state in channel_states
                },
            }
            thread = threading.Thread(
                target=self._run,
                kwargs={
                    "states": channel_states,
                    "control": control,
                    "state_publisher": state_publisher,
                    "duration_s": bounded_duration,
                    "poll_s": float(poll_s),
                },
                name="RtSampleTransport",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return True

    def cancel(self) -> bool:
        with self._lock:
            if not bool(self._status.get("active")):
                return False
            next_status = dict(self._status)
            next_status["cancel_requested"] = True
            next_status["phase"] = "cancelling"
            self._status = next_status
            self._cancel.set()
            return True

    def request_cancel(self) -> None:
        self._cancel.set()

    @staticmethod
    def _collect_ports(runtimes: list[Any]) -> list[SampleTransportPort]:
        ports: list[SampleTransportPort] = []
        for runtime in runtimes:
            if runtime is None:
                continue
            port_fn = getattr(runtime, "sample_transport_port", None)
            if not callable(port_fn):
                continue
            try:
                port = port_fn()
            except Exception:
                _LOG.exception(
                    "SampleTransport: sample_transport_port() raised for %s",
                    getattr(runtime, "runtime_id", type(runtime).__name__),
                )
                continue
            key = getattr(port, "key", None)
            if isinstance(key, str) and key:
                ports.append(port)
        order = {"c1": 0, "c2": 1, "c3": 2, "c4": 3}
        ports.sort(key=lambda port: order.get(getattr(port, "key", ""), 99))
        return ports

    @staticmethod
    def _build_channel_states(
        ports: list[SampleTransportPort],
        *,
        base_interval_s: float,
        ratio: float,
    ) -> list[_ChannelState]:
        now = time.monotonic()
        states: list[_ChannelState] = []
        for index, port in enumerate(ports):
            interval = max(MIN_INTERVAL_S, float(base_interval_s) / (ratio**index))
            states.append(
                _ChannelState(
                    key=str(getattr(port, "key", f"c{index + 1}")),
                    port=port,
                    interval_s=interval,
                    next_at_mono=now,
                )
            )
        return states

    def _update_status(self, *, states: list[_ChannelState], **updates: Any) -> None:
        with self._lock:
            next_status = dict(self._status)
            next_status.update(updates)
            next_status["channels"] = {
                state.key: state.snapshot() for state in states
            }
            self._status = next_status

    def _run(
        self,
        *,
        states: list[_ChannelState],
        control: RuntimeControl,
        state_publisher: Callable[[str], None] | None,
        duration_s: float | None,
        poll_s: float,
    ) -> None:
        was_paused = bool(getattr(control, "paused", False))
        deadline = (
            None if duration_s is None else time.monotonic() + float(duration_s)
        )
        success = False
        reason = "cancelled"
        phase = "running"
        try:
            control.pause()
            if callable(state_publisher):
                try:
                    state_publisher("sample_transport")
                except Exception:
                    _LOG.exception("SampleTransport: state publisher raised on start")
            self._update_status(states=states, active=True, phase="running")

            while not self._cancel.is_set():
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    success = True
                    reason = "duration_elapsed"
                    phase = "idle"
                    break
                for state in states:
                    if now < state.next_at_mono:
                        continue
                    try:
                        moved = bool(state.port.step(now))
                    except Exception as exc:
                        state.error_count += 1
                        state.last_error = str(exc) or exc.__class__.__name__
                        _LOG.exception(
                            "SampleTransport: step raised for %s", state.key
                        )
                        moved = False
                    if moved:
                        state.step_count += 1
                        state.last_step_at = time.time()
                    else:
                        state.skipped_count += 1
                        state.last_skip_at = time.time()
                    state.next_at_mono = now + state.interval_s
                self._update_status(states=states, active=True, phase="running")
                self._cancel.wait(timeout=float(poll_s))
            else:
                reason = "cancelled"
                phase = "cancelled"
        except Exception as exc:
            reason = str(exc) or exc.__class__.__name__
            phase = "error"
            _LOG.exception("SampleTransport: worker failed")
        finally:
            if not was_paused:
                try:
                    control.resume()
                except Exception:
                    _LOG.exception("SampleTransport: control.resume raised")
                restore_state = "running"
            else:
                restore_state = "paused"
            if callable(state_publisher):
                try:
                    state_publisher(restore_state)
                except Exception:
                    _LOG.exception("SampleTransport: state publisher raised on finish")
            self._update_status(
                states=states,
                active=False,
                phase="idle" if success else phase,
                finished_at=time.time(),
                success=success,
                reason=reason,
                cancel_requested=False,
            )


__all__ = [
    "C1234SampleTransportCoordinator",
    "DEFAULT_BASE_INTERVAL_S",
    "DEFAULT_DURATION_S",
    "DEFAULT_POLL_S",
    "DEFAULT_RATIO",
]
