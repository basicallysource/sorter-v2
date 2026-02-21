from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import logging
import queue

from defs.sorter_controller import SorterLifecycle

from defs.events import (
    IdentityEvent,
    MachineIdentityData,
    PauseCommandEvent,
    PauseCommandData,
    ResumeCommandEvent,
    ResumeCommandData,
)
from bricklink.api import getPartInfo
from global_config import GlobalConfig
from runtime_variables import RuntimeVariables, VARIABLE_DEFS
from hardware.bus import MCUBus, MCUBusError
from hardware.sorter_interface import SorterInterface

app = FastAPI(title="Sorter API", version="0.0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

active_connections: List[WebSocket] = []
server_loop: Optional[asyncio.AbstractEventLoop] = None
runtime_vars: Optional[RuntimeVariables] = None
command_queue: Optional[queue.Queue] = None
controller_ref: Optional[Any] = None
gc_ref: Optional[GlobalConfig] = None

# Hardware debug state
hardware_bus: Optional[MCUBus] = None
hardware_interfaces: Dict[str, SorterInterface] = {}

logger = logging.getLogger("hardware_api")


def setGlobalConfig(gc: GlobalConfig) -> None:
    global gc_ref
    gc_ref = gc


def setRuntimeVariables(rv: RuntimeVariables) -> None:
    global runtime_vars
    runtime_vars = rv


def setCommandQueue(q: queue.Queue) -> None:
    global command_queue
    command_queue = q


def setController(c: Any) -> None:
    global controller_ref
    controller_ref = c


@app.on_event("startup")
async def onStartup() -> None:
    global server_loop
    server_loop = asyncio.get_running_loop()


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    active_connections.append(websocket)

    machine_id = gc_ref.machine_id if gc_ref is not None else "unknown"
    identity_event = IdentityEvent(
        tag="identity",
        data=MachineIdentityData(machine_id=machine_id, nickname=None),
    )
    await websocket.send_json(identity_event.model_dump())

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)


async def broadcastEvent(event: dict) -> None:
    dead_connections = []
    for connection in active_connections[:]:
        try:
            await connection.send_json(event)
        except Exception:
            dead_connections.append(connection)
    for conn in dead_connections:
        if conn in active_connections:
            active_connections.remove(conn)


class BricklinkPartResponse(BaseModel):
    no: str
    name: str
    type: str
    category_id: Optional[int] = None
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    weight: Optional[str] = None
    dim_x: Optional[str] = None
    dim_y: Optional[str] = None
    dim_z: Optional[str] = None
    year_released: Optional[int] = None
    is_obsolete: Optional[bool] = None


@app.get("/bricklink/part/{part_id}", response_model=BricklinkPartResponse)
def getBricklinkPart(part_id: str) -> BricklinkPartResponse:
    data = getPartInfo(part_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Part not found")
    return BricklinkPartResponse(**data)


class RuntimeVariableDef(BaseModel):
    type: str
    min: float
    max: float
    unit: str


class RuntimeVariablesResponse(BaseModel):
    definitions: Dict[str, RuntimeVariableDef]
    values: Dict[str, Any]


class RuntimeVariablesUpdateRequest(BaseModel):
    values: Dict[str, Any]


@app.get("/runtime-variables", response_model=RuntimeVariablesResponse)
def getRuntimeVariables() -> RuntimeVariablesResponse:
    if runtime_vars is None:
        raise HTTPException(status_code=500, detail="Runtime variables not initialized")
    defs = {k: RuntimeVariableDef(**v) for k, v in VARIABLE_DEFS.items()}
    return RuntimeVariablesResponse(definitions=defs, values=runtime_vars.getAll())


@app.post("/runtime-variables", response_model=RuntimeVariablesResponse)
def updateRuntimeVariables(
    req: RuntimeVariablesUpdateRequest,
) -> RuntimeVariablesResponse:
    if runtime_vars is None:
        raise HTTPException(status_code=500, detail="Runtime variables not initialized")
    runtime_vars.setAll(req.values)
    defs = {k: RuntimeVariableDef(**v) for k, v in VARIABLE_DEFS.items()}
    return RuntimeVariablesResponse(definitions=defs, values=runtime_vars.getAll())


class StateResponse(BaseModel):
    state: str


@app.get("/state", response_model=StateResponse)
def getState() -> StateResponse:
    if controller_ref is None:
        return StateResponse(state=SorterLifecycle.INITIALIZING.value)
    return StateResponse(state=controller_ref.state.value)


class CommandResponse(BaseModel):
    success: bool


@app.post("/pause", response_model=CommandResponse)
def pause() -> CommandResponse:
    if command_queue is None:
        raise HTTPException(status_code=500, detail="Command queue not initialized")
    event = PauseCommandEvent(tag="pause", data=PauseCommandData())
    command_queue.put(event)
    return CommandResponse(success=True)


@app.post("/resume", response_model=CommandResponse)
def resume() -> CommandResponse:
    if command_queue is None:
        raise HTTPException(status_code=500, detail="Command queue not initialized")
    event = ResumeCommandEvent(tag="resume", data=ResumeCommandData())
    command_queue.put(event)
    return CommandResponse(success=True)


# --- Hardware Debug API ---


def setHardwareInterfaces(bus: Optional[MCUBus], ifaces: Dict[str, SorterInterface]) -> None:
    global hardware_bus, hardware_interfaces
    hardware_bus = bus
    hardware_interfaces = ifaces


def _initHardware() -> Dict[str, SorterInterface]:
    """Discover and initialize hardware interfaces."""
    global hardware_bus, hardware_interfaces
    hardware_interfaces = {}
    ports = MCUBus.enumerate_buses()
    if not ports:
        logger.warning("No MCU buses found")
        hardware_bus = None
        return hardware_interfaces
    hardware_bus = MCUBus(port=ports[0])
    logger.info(f"Connected to bus on {ports[0]}")
    devices = hardware_bus.scan_devices()
    for addr in devices:
        try:
            iface = SorterInterface(hardware_bus, addr)
            hardware_interfaces[iface.name] = iface
            logger.info(f"Found interface: {iface.name} at address {addr}")
        except Exception as e:
            logger.error(f"Failed to init device at address {addr}: {e}")
    return hardware_interfaces


def _getInterface(name: str) -> SorterInterface:
    if name not in hardware_interfaces:
        raise HTTPException(status_code=404, detail=f"Device '{name}' not found")
    return hardware_interfaces[name]


# Models

class HwDeviceInfo(BaseModel):
    name: str
    board_info: Dict[str, Any]
    stepper_count: int
    digital_input_count: int
    digital_output_count: int


class HwDevicesResponse(BaseModel):
    devices: List[HwDeviceInfo]
    bus_port: Optional[str]


class HwStepperInfo(BaseModel):
    channel: int
    position: int
    stopped: bool


class HwDigitalInputInfo(BaseModel):
    channel: int
    value: bool


class HwDigitalOutputInfo(BaseModel):
    channel: int
    value: bool


class HwDeviceStatusResponse(BaseModel):
    name: str
    steppers: List[HwStepperInfo]
    digital_inputs: List[HwDigitalInputInfo]
    digital_outputs: List[HwDigitalOutputInfo]


class HwCommandResult(BaseModel):
    success: bool
    error: Optional[str] = None


class HwMoveRequest(BaseModel):
    steps: int


class HwSpeedRequest(BaseModel):
    speed: int


class HwSpeedLimitsRequest(BaseModel):
    min_speed: int
    max_speed: int


class HwAccelerationRequest(BaseModel):
    acceleration: int


class HwPositionRequest(BaseModel):
    position: int


class HwMicrostepsRequest(BaseModel):
    microsteps: int


class HwCurrentRequest(BaseModel):
    irun: int
    ihold: int
    ihold_delay: int


class HwHomeRequest(BaseModel):
    speed: int
    pin: int
    active_high: bool = True


class HwDigitalWriteRequest(BaseModel):
    value: bool


# Endpoints

@app.get("/hardware/devices", response_model=HwDevicesResponse)
def hw_list_devices():
    devices = []
    for name, iface in hardware_interfaces.items():
        devices.append(HwDeviceInfo(
            name=name,
            board_info=iface._board_info,
            stepper_count=len(iface.steppers),
            digital_input_count=len(iface.digital_inputs),
            digital_output_count=len(iface.digital_outputs),
        ))
    return HwDevicesResponse(
        devices=devices,
        bus_port=hardware_bus._serial.port if hardware_bus else None,
    )


@app.post("/hardware/devices/rescan", response_model=HwDevicesResponse)
def hw_rescan_devices():
    _initHardware()
    return hw_list_devices()


@app.post("/hardware/devices/{name}/reboot-bootloader", response_model=HwCommandResult)
def hw_reboot_bootloader(name: str):
    iface = _getInterface(name)
    try:
        iface.reboot_to_bootloader()
        return HwCommandResult(success=True)
    except Exception as e:
        return HwCommandResult(success=False, error=str(e))


@app.get("/hardware/devices/{name}/status", response_model=HwDeviceStatusResponse)
def hw_device_status(name: str):
    iface = _getInterface(name)
    steppers = []
    for s in iface.steppers:
        try:
            steppers.append(HwStepperInfo(channel=s.channel, position=s.position, stopped=s.stopped))
        except MCUBusError:
            steppers.append(HwStepperInfo(channel=s.channel, position=0, stopped=True))
    digital_inputs = []
    for d in iface.digital_inputs:
        try:
            digital_inputs.append(HwDigitalInputInfo(channel=d.channel, value=d.value))
        except MCUBusError:
            digital_inputs.append(HwDigitalInputInfo(channel=d.channel, value=False))
    digital_outputs = []
    for d in iface.digital_outputs:
        digital_outputs.append(HwDigitalOutputInfo(channel=d.channel, value=d.value))
    return HwDeviceStatusResponse(
        name=name, steppers=steppers, digital_inputs=digital_inputs, digital_outputs=digital_outputs
    )


@app.post("/hardware/devices/{name}/steppers/{channel}/move", response_model=HwCommandResult)
def hw_stepper_move(name: str, channel: int, req: HwMoveRequest):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        result = iface.steppers[channel].move_steps(req.steps)
        return HwCommandResult(success=result)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/move-at-speed", response_model=HwCommandResult)
def hw_stepper_move_at_speed(name: str, channel: int, req: HwSpeedRequest):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        result = iface.steppers[channel].move_at_speed(req.speed)
        return HwCommandResult(success=result)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/stop", response_model=HwCommandResult)
def hw_stepper_stop(name: str, channel: int):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        result = iface.steppers[channel].move_steps(0)
        return HwCommandResult(success=result)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/set-speed", response_model=HwCommandResult)
def hw_stepper_set_speed(name: str, channel: int, req: HwSpeedLimitsRequest):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        result = iface.steppers[channel].set_speed_limits(req.min_speed, req.max_speed)
        return HwCommandResult(success=result)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/set-acceleration", response_model=HwCommandResult)
def hw_stepper_set_acceleration(name: str, channel: int, req: HwAccelerationRequest):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        result = iface.steppers[channel].set_acceleration(req.acceleration)
        return HwCommandResult(success=result)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/set-position", response_model=HwCommandResult)
def hw_stepper_set_position(name: str, channel: int, req: HwPositionRequest):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        iface.steppers[channel].position = req.position
        return HwCommandResult(success=True)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/enable", response_model=HwCommandResult)
def hw_stepper_enable(name: str, channel: int):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        iface.steppers[channel].enabled = True
        return HwCommandResult(success=True)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/disable", response_model=HwCommandResult)
def hw_stepper_disable(name: str, channel: int):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        iface.steppers[channel].enabled = False
        return HwCommandResult(success=True)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/set-microsteps", response_model=HwCommandResult)
def hw_stepper_set_microsteps(name: str, channel: int, req: HwMicrostepsRequest):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        iface.steppers[channel].set_microsteps(req.microsteps)
        return HwCommandResult(success=True)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/set-current", response_model=HwCommandResult)
def hw_stepper_set_current(name: str, channel: int, req: HwCurrentRequest):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        iface.steppers[channel].set_current(req.irun, req.ihold, req.ihold_delay)
        return HwCommandResult(success=True)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/home", response_model=HwCommandResult)
def hw_stepper_home(name: str, channel: int, req: HwHomeRequest):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        result = iface.steppers[channel].home(req.speed, req.pin, req.active_high)
        return HwCommandResult(success=result)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.get("/hardware/devices/{name}/digital-inputs/{channel}")
def hw_read_digital_input(name: str, channel: int):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.digital_inputs):
        raise HTTPException(status_code=404, detail=f"Digital input channel {channel} not found")
    try:
        return {"value": iface.digital_inputs[channel].value}
    except MCUBusError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/hardware/devices/{name}/digital-outputs/{channel}", response_model=HwCommandResult)
def hw_write_digital_output(name: str, channel: int, req: HwDigitalWriteRequest):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.digital_outputs):
        raise HTTPException(status_code=404, detail=f"Digital output channel {channel} not found")
    try:
        iface.digital_outputs[channel].value = req.value
        return HwCommandResult(success=True)
    except MCUBusError as e:
        return HwCommandResult(success=False, error=str(e))


@app.get("/hardware/devices/{name}/steppers/{channel}/read-register/{address}")
def hw_stepper_read_register(name: str, channel: int, address: int):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        value = iface.steppers[channel].read_driver_register(address)
        return {"value": value, "hex": f"0x{value:08X}"}
    except MCUBusError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/hardware/devices/{name}/steppers/{channel}/write-register/{address}")
def hw_stepper_write_register(name: str, channel: int, address: int, value: int):
    iface = _getInterface(name)
    if channel < 0 or channel >= len(iface.steppers):
        raise HTTPException(status_code=404, detail=f"Stepper channel {channel} not found")
    try:
        iface.steppers[channel].write_driver_register(address, value)
        return {"success": True}
    except MCUBusError as e:
        raise HTTPException(status_code=500, detail=str(e))
