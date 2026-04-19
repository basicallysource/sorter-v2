from __future__ import annotations

import queue

from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from machine_runtime.base import MachineRuntime
from piece_transport import ClassificationChannelTransport, PieceTransport
from telemetry import Telemetry
from vision import VisionManager


class ClassificationChannelRuntime(MachineRuntime):
    def create_transport(
        self,
        *,
        gc: GlobalConfig,
        event_queue: queue.Queue,
    ) -> PieceTransport:
        _ = gc, event_queue
        return ClassificationChannelTransport()

    def create_classification(
        self,
        *,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared,
        vision: VisionManager,
        event_queue: queue.Queue,
        telemetry: Telemetry,
        transport: PieceTransport,
    ):
        from subsystems.classification_channel.state_machine import (
            ClassificationChannelStateMachine,
        )

        if not isinstance(transport, ClassificationChannelTransport):
            raise TypeError(
                "ClassificationChannelRuntime requires a ClassificationChannelTransport."
            )
        return ClassificationChannelStateMachine(
            irl=irl,
            irl_config=irl_config,
            gc=gc,
            shared=shared,
            vision=vision,
            event_queue=event_queue,
            telemetry=telemetry,
            transport=transport,
        )
