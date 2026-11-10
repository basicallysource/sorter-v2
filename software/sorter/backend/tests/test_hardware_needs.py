"""What an action needs from the hardware (server/hardware_needs.py): each state
against each need, and the refusal a route answers with."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import hardware_needs, shared_state
from server.hardware_needs import HOME, START, STOP, WAIT, HardwareNotReady
from server.routers import bins, steppers

STATES = ("standby", "initializing", "initialized", "homing", "ready", "error")

STANDBY_START = "The machine is in standby: the hardware is not started. Start it first."
STANDBY_HOME = "The machine is in standby: the hardware is not started. Home it first."
STARTING = "The hardware is still starting. Try again in a moment."
HOMING = "The machine is homing (Homing distributor). Try again when it is done."
NOT_HOMED = "The machine is started but not homed, so it does not know where the chute is. Home it first."
ERROR_START = "The hardware stopped with an error: Control board link lost. Start it again."
ERROR_HOME = "The hardware stopped with an error: Control board link lost. Home it again."

# (state, need) -> None when met, else (needs, detail).
EXPECTED = {
    ("standby", "idle"): None,
    ("standby", "started"): (START, STANDBY_START),
    ("standby", "homed"): (HOME, STANDBY_HOME),
    ("standby", "stopped"): None,
    ("initializing", "idle"): (WAIT, STARTING),
    ("initializing", "started"): (WAIT, STARTING),
    ("initializing", "homed"): (WAIT, STARTING),
    ("initializing", "stopped"): (WAIT, STARTING),
    ("initialized", "idle"): None,
    ("initialized", "started"): None,
    ("initialized", "homed"): (HOME, NOT_HOMED),
    ("initialized", "stopped"): (STOP, hardware_needs.RUNNING),
    ("homing", "idle"): (WAIT, HOMING),
    ("homing", "started"): (WAIT, HOMING),
    ("homing", "homed"): (WAIT, HOMING),
    ("homing", "stopped"): (WAIT, HOMING),
    ("ready", "idle"): None,
    ("ready", "started"): None,
    ("ready", "homed"): None,
    ("ready", "stopped"): (STOP, hardware_needs.RUNNING),
    ("error", "idle"): None,
    ("error", "started"): (START, ERROR_START),
    ("error", "homed"): (HOME, ERROR_HOME),
    ("error", "stopped"): None,
}


class _Chute:
    def __init__(self, homed: bool) -> None:
        self.homed = homed
        self.moves: list[float] = []

    def angleForVirtualBin(self, section_index: int, bin_index: int, bins_in_section: int):
        return 40.0 + 72.0 * section_index

    def moveToAngle(self, angle: float) -> int:
        self.moves.append(angle)
        return 250


@pytest.fixture(autouse=True)
def hardware(monkeypatch):
    """A machine in `state`, with whatever IRL and controller a test gives it."""

    def put(state: str, *, irl=None, controller=None) -> None:
        monkeypatch.setattr(shared_state, "hardware_state", state)
        monkeypatch.setattr(shared_state, "hardware_runtime_irl", irl)
        monkeypatch.setattr(shared_state, "controller_ref", controller)
        monkeypatch.setattr(
            shared_state, "hardware_homing_step", "Homing distributor..." if state == "homing" else None
        )
        monkeypatch.setattr(
            shared_state,
            "hardware_error",
            {"title": "Control board link lost", "message": "No answer. Home the machine to reconnect."}
            if state == "error"
            else None,
        )

    monkeypatch.setattr(shared_state, "hardware_worker_thread", None)
    put("standby")
    return put


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("need", ("idle", "started", "homed", "stopped"))
def test_each_state_against_each_need(hardware, state, need) -> None:
    hardware(state)

    refusal = hardware_needs.refusalFor(need)

    expected = EXPECTED[(state, need)]
    if expected is None:
        assert refusal is None
    else:
        assert refusal is not None
        assert (refusal.needs, refusal.detail) == expected
        assert refusal.status_code == 503
        assert refusal.hardware_state == state


def test_a_running_start_or_home_is_waited_out_whatever_the_state_says(hardware, monkeypatch) -> None:
    hardware("ready")
    release = threading.Event()
    worker = threading.Thread(target=release.wait, daemon=True)
    worker.start()
    monkeypatch.setattr(shared_state, "hardware_worker_thread", worker)
    try:
        with pytest.raises(HardwareNotReady) as refused:
            hardware_needs.needIdle()
        assert refused.value.needs == WAIT
    finally:
        release.set()
        worker.join(timeout=1.0)


def test_started_gives_the_live_hardware_and_homed_the_controller(hardware) -> None:
    irl = SimpleNamespace()
    controller = SimpleNamespace(irl=irl)

    hardware("initialized", irl=irl)
    assert hardware_needs.needStarted() is irl

    hardware("ready", irl=irl, controller=controller)
    assert hardware_needs.needStarted() is irl
    assert hardware_needs.needHomed() is controller


def test_a_state_ahead_of_its_hardware_is_a_stop_in_progress(hardware) -> None:
    hardware("ready")  # a reset has taken the hardware down; the state follows

    with pytest.raises(HardwareNotReady) as refused:
        hardware_needs.needHomed()

    assert refused.value.needs == WAIT
    assert refused.value.detail == "The hardware is stopping. Try again in a moment."


def test_a_generic_fault_names_its_message(hardware, monkeypatch) -> None:
    hardware("error")
    monkeypatch.setattr(shared_state, "hardware_error", {"title": "Hardware error", "message": "Chute homing failed."})

    refusal = hardware_needs.refusalFor(hardware_needs.STARTED)

    assert refusal is not None
    assert refusal.detail == "The hardware stopped with an error: Chute homing failed. Start it again."


def test_a_stop_reaches_the_hardware_while_it_homes_or_after_an_error(hardware) -> None:
    irl = SimpleNamespace()
    for state in ("homing", "error", "initialized"):
        hardware(state, irl=irl)
        assert hardware_needs.hardwareToStop() is irl

    hardware("standby")
    with pytest.raises(HardwareNotReady) as refused:
        hardware_needs.hardwareToStop()
    assert refused.value.needs == START


def test_a_chute_homed_on_its_own_can_be_aimed_on_a_started_machine(hardware) -> None:
    hardware("initialized")
    hardware_needs.needChuteHomed(_Chute(homed=True))

    with pytest.raises(HardwareNotReady) as refused:
        hardware_needs.needChuteHomed(_Chute(homed=False))
    assert (refused.value.needs, refused.value.detail) == (HOME, NOT_HOMED)

    hardware("ready")
    hardware_needs.needChuteHomed(_Chute(homed=False))


def test_a_chute_move_on_a_machine_not_started_asks_to_home(hardware) -> None:
    for state, detail in (("standby", STANDBY_HOME), ("error", ERROR_HOME)):
        hardware(state)
        with pytest.raises(HardwareNotReady) as refused:
            hardware_needs.needChuteHomed(None)
        assert (refused.value.needs, refused.value.detail) == (HOME, detail)


# --- the refusal as a route answers it ---


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(steppers.router)
    app.include_router(bins.router)
    hardware_needs.installHandler(app)
    with TestClient(app) as test_client:
        yield test_client


def test_a_jog_needs_the_hardware_started(client, hardware) -> None:
    hardware("standby")

    response = client.post("/stepper/pulse", params={"stepper": "carousel", "direction": "cw"})

    assert response.status_code == 503
    assert response.json() == {"detail": STANDBY_START, "needs": START, "hardware_state": "standby"}


def test_moving_the_chute_to_a_bin_needs_it_homed(client, hardware) -> None:
    hardware("initialized", irl=SimpleNamespace(chute=_Chute(homed=False), servos=[]))

    response = client.post("/api/bins/move-to", json={"layer_index": 0, "section_index": 0, "bin_index": 17})

    assert response.status_code == 503
    assert response.json() == {"detail": NOT_HOMED, "needs": HOME, "hardware_state": "initialized"}


def test_a_chute_homed_on_its_own_points_at_a_section(client, hardware) -> None:
    chute = _Chute(homed=True)
    hardware("initialized", irl=SimpleNamespace(chute=chute, servos=[]))

    response = client.post("/api/bins/move-to-section", json={"section_index": 1})

    assert response.status_code == 200
    assert response.json()["target_angle"] == 112.0
    assert chute.moves == [112.0]


def test_anything_that_moves_waits_out_homing(client, hardware) -> None:
    hardware("homing", irl=SimpleNamespace(chute=_Chute(homed=True), servos=[]))

    for response in (
        client.post("/stepper/pulse", params={"stepper": "carousel", "direction": "cw"}),
        client.post("/api/bins/move-to-section", json={"section_index": 0}),
    ):
        assert response.status_code == 503
        assert response.json() == {"detail": HOMING, "needs": WAIT, "hardware_state": "homing"}


def test_resuming_the_sorter_needs_it_homed(client, hardware) -> None:
    hardware("initialized", irl=SimpleNamespace())

    response = client.post("/resume")

    assert response.status_code == 503
    assert response.json()["needs"] == HOME
