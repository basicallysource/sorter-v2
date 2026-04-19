from __future__ import annotations

import queue

from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from machine_runtime.base import MachineRuntime
from piece_transport import PieceTransport
from subsystems.classification.carousel import Carousel
from telemetry import Telemetry
from vision import VisionManager


class StandardCarouselRuntime(MachineRuntime):
    def create_transport(
        self,
        *,
        gc: GlobalConfig,
        event_queue: queue.Queue,
    ) -> PieceTransport:
        return Carousel(gc.logger, event_queue)

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
        from subsystems.classification.state_machine import ClassificationStateMachine
        from subsystems.classification.carousel import Carousel

        if not isinstance(transport, Carousel):
            raise TypeError("StandardCarouselRuntime requires a Carousel transport.")
        return ClassificationStateMachine(
            irl,
            gc,
            shared,
            vision,
            event_queue,
            telemetry,
            transport,
        )
