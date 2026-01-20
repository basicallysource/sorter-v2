from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List
from pathlib import Path
import uuid

from defs.events import IdentityEvent, MachineIdentityData

app = FastAPI(title="Sorter API", version="0.0.1")

active_connections: List[WebSocket] = []

MACHINE_ID_FILE = Path.home() / ".sorter_machine_id"


def getMachineId() -> str:
    if MACHINE_ID_FILE.exists():
        return MACHINE_ID_FILE.read_text().strip()
    machine_id = str(uuid.uuid4())
    MACHINE_ID_FILE.write_text(machine_id)
    return machine_id


MACHINE_ID = getMachineId()


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    active_connections.append(websocket)

    identity_event = IdentityEvent(
        tag="identity", data=MachineIdentityData(machine_id=MACHINE_ID, nickname=None)
    )
    await websocket.send_json(identity_event.model_dump())

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)


async def broadcastEvent(event: dict) -> None:
    for connection in active_connections:
        await connection.send_json(event)
