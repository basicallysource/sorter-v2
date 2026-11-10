"""What an action needs from the hardware, and the one refusal when it is not there.

The hardware is in one state at a time (``shared_state.hardware_state``). The
UI's header shows each state by a label (``AppHeader.svelte``), and a refusal
names the state in the same words:

    state         header label        what it means
    standby       Standby             nothing is started
    initializing  Starting            the boards are being found, the motors powered
    initialized   Started, not homed  motors powered, boards talking, nothing homed
    homing        Homing              starting, then finding home on every axis
    ready         Ready               homed: it knows where the chute and channels are
    error         Error               stopped with an error (``hardware_error`` says which)

A route asks first for what its action needs, and gets what it works with:

    needIdle()            no start or home is running (they own the motors)
    needStarted()         started or homed; returns the live hardware (the IRL)
    needHomed()           homed; returns the sorter's controller
    needChuteHomed(chute) homed, or started with the chute homed on its own
    needStopped()         in standby or stopped with an error (to flash firmware)
    hardwareToStop()      the live hardware in any state, for a stop

When the need is not met the call raises ``HardwareNotReady``: HTTP 503, with
``detail``, the sentence for the person at the machine (the true state and the
one thing to do), and beside it ``needs``, that thing as a word a page can offer
a button for (``start``, ``home``, ``wait`` or ``stop``), and ``hardware_state``.
``installHandler(app)`` puts the two extra fields in the answer; without it the
refusal still answers 503 with its ``detail``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request

from hardware.fault import HardwareFault
from server import shared_state

# What a refusal asks for (`needs`).
START = "start"
HOME = "home"
WAIT = "wait"
STOP = "stop"

# What an action needs, from least to most.
IDLE = "idle"
STARTED = "started"
HOMED = "homed"
# Flashing firmware needs the opposite: the hardware not running.
STOPPED = "stopped"

# The sentence for a running machine asked to do what needs it stopped.
RUNNING = "The hardware is running. Reset it to standby first."

STARTED_STATES = frozenset({"initialized", "ready"})
BUSY_STATES = frozenset({"initializing", "homing"})
STOPPED_STATES = frozenset({"standby", "error"})


class HardwareNotReady(HTTPException):
    """The hardware is not in the state an action needs."""

    def __init__(self, detail: str, needs: str, hardware_state: str) -> None:
        super().__init__(status_code=503, detail=detail)
        self.needs = needs
        self.hardware_state = hardware_state

    def body(self) -> dict[str, str]:
        return {"detail": self.detail, "needs": self.needs, "hardware_state": self.hardware_state}


def installHandler(app: FastAPI) -> None:
    """Answer a HardwareNotReady with `needs` and `hardware_state` beside `detail`."""

    async def _answer(_request: Request, exc: HardwareNotReady) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.body(), headers=exc.headers)

    app.add_exception_handler(HardwareNotReady, _answer)


def _busy() -> bool:
    worker = shared_state.hardware_worker_thread
    return (worker is not None and worker.is_alive()) or shared_state.hardware_state in BUSY_STATES


def _homingStep() -> str:
    step = (shared_state.hardware_homing_step or "").strip().rstrip(".…").strip()
    return f" ({step})" if step else ""


def _fault() -> str:
    fault = shared_state.hardware_error or {}
    title = str(fault.get("title") or "").strip()
    message = str(fault.get("message") or "").strip()
    text = title if title and title != HardwareFault.GENERIC_TITLE else message
    text = text.rstrip(". ")
    return f": {text}" if text else ""


def refusalFor(level: str) -> HardwareNotReady | None:
    """Why the hardware does not meet `level` now, or None when it does."""
    state = shared_state.hardware_state
    if _busy():
        if state == "homing":
            return HardwareNotReady(
                f"The machine is homing{_homingStep()}. Try again when it is done.", WAIT, state
            )
        return HardwareNotReady("The hardware is still starting. Try again in a moment.", WAIT, state)
    if level == IDLE:
        return None
    if level == STOPPED:
        if state in STOPPED_STATES:
            return None
        return HardwareNotReady(RUNNING, STOP, state)
    if level == STARTED and state in STARTED_STATES:
        return None
    if level == HOMED and state == "ready":
        return None

    needs = HOME if level == HOMED else START
    do = "Home it" if needs == HOME else "Start it"
    if state == "error":
        return HardwareNotReady(f"The hardware stopped with an error{_fault()}. {do} again.", needs, state)
    if state == "initialized":
        return HardwareNotReady(
            "The machine is started but not homed, so it does not know where the chute is. Home it first.",
            HOME,
            state,
        )
    return HardwareNotReady(f"The machine is in standby: the hardware is not started. {do} first.", needs, state)


def _need(level: str) -> None:
    refusal = refusalFor(level)
    if refusal is not None:
        raise refusal


def _stopping() -> HardwareNotReady:
    # The state still says started while the hardware is gone: a reset is
    # taking it down, and the state follows in a moment.
    return HardwareNotReady(
        "The hardware is stopping. Try again in a moment.", WAIT, shared_state.hardware_state
    )


def needIdle() -> None:
    """No start or home is running. While one is, it owns every motor."""
    _need(IDLE)


def needStarted() -> Any:
    """The hardware is started (homed or not): the live hardware (the IRL)."""
    _need(STARTED)
    irl = shared_state.getActiveIRL()
    if irl is None:
        raise _stopping()
    return irl


def needHomed() -> Any:
    """The machine is homed and its sorter built: the controller."""
    _need(HOMED)
    controller = shared_state.controller_ref
    if controller is None:
        raise _stopping()
    return controller


def needChuteHomed(chute: Any | None) -> None:
    """The chute knows where it is, for a move that aims it (`chute` is the live
    one, or None). Homing the machine homes the chute; on a machine only started,
    the chute can be homed on its own (Home the chute, on the Bins and Chute
    pages). Refused, the one thing to do is to home, from any state."""
    state = shared_state.hardware_state
    if not _busy() and (
        state == "ready" or (state in STARTED_STATES and bool(getattr(chute, "homed", False)))
    ):
        return
    _need(HOMED)
    raise _stopping()


def needStopped() -> None:
    """The hardware is not running: in standby, or stopped with an error."""
    _need(STOPPED)


def hardwareToStop() -> Any:
    """The live hardware in whatever state it is in, for stopping a motor: a stop
    works while the machine homes and after an error. Refuses only when there is
    no hardware running to stop."""
    irl = shared_state.getActiveIRL()
    if irl is not None:
        return irl
    raise refusalFor(STARTED) or _stopping()
