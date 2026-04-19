from __future__ import annotations

from abc import ABC, abstractmethod
import queue

from global_config import GlobalConfig
from irl.bin_layout import DistributionLayout
from irl.config import IRLConfig, IRLInterface
from machine_setup import MachineSetupDefinition
from piece_transport import PieceTransport
from sorting_profile import SortingProfile
from telemetry import Telemetry
from vision import VisionManager


class MachineRuntime(ABC):
    def __init__(self, setup_definition: MachineSetupDefinition):
        self.setup_definition = setup_definition

    @property
    def key(self) -> str:
        return self.setup_definition.key

    @abstractmethod
    def create_transport(
        self,
        *,
        gc: GlobalConfig,
        event_queue: queue.Queue,
    ) -> PieceTransport:
        pass

    def create_feeder(
        self,
        *,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared,
        vision: VisionManager,
    ):
        from subsystems.feeder.state_machine import FeederStateMachine

        return FeederStateMachine(irl, irl_config, gc, shared, vision)

    @abstractmethod
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
        pass

    def create_distribution(
        self,
        *,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared,
        sorting_profile: SortingProfile,
        distribution_layout: DistributionLayout,
        event_queue: queue.Queue,
    ):
        from subsystems.distribution.state_machine import DistributionStateMachine

        return DistributionStateMachine(
            irl,
            gc,
            shared,
            sorting_profile,
            distribution_layout,
            event_queue,
        )
