import time
import queue
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from .chute import Chute, BinAddress
from irl.bin_layout import DistributionLayout, Bin, extractCategories
from irl.config import IRLInterface
from global_config import GlobalConfig
from sorting_profile import SortingProfile, MISC_CATEGORY
from blob_manager import setBinCategories
from defs.known_object import PieceStage
from utils.event import knownObjectToEvent

class Positioning(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        chute: Chute,
        layout: DistributionLayout,
        sorting_profile: SortingProfile,
        event_queue: queue.Queue,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.chute = chute
        self.layout = layout
        self.sorting_profile = sorting_profile
        self.event_queue = event_queue
        self._phase: str = "init"
        self._target_address: BinAddress | None = None
        self._door_servo_index: int | None = None
        self._state_entered_at: float = 0.0
        self._moving_started_at: float = 0.0

    def step(self) -> Optional[DistributionState]:
        now = time.monotonic()

        if self._phase == "init":
            self._state_entered_at = now
            carousel = self.shared.carousel
            piece = carousel.getPieceAtIntermediate() if carousel else None
            if piece is None:
                self.logger.warn("Positioning: no piece at intermediate")
                return DistributionState.IDLE

            if piece.part_id is not None:
                category_id = self.sorting_profile.getCategoryIdForPart(piece.part_id, piece.color_id)
            else:
                category_id = MISC_CATEGORY
            address, _ = self._findOrAssignBinForCategory(category_id)
            if address is None:
                self.logger.warn(
                    f"Positioning: no available bins for category {category_id}"
                )
                return DistributionState.IDLE

            piece.stage = PieceStage.distributing
            piece.distributing_at = time.time()
            piece.category_id = category_id
            piece.destination_bin = (
                address.layer_index,
                address.section_index,
                address.bin_index,
            )
            piece.updated_at = time.time()
            self.event_queue.put(knownObjectToEvent(piece))

            self.logger.info(
                f"Positioning: moving to bin at layer={address.layer_index}, section={address.section_index}, bin={address.bin_index}"
            )
            self._selectDoor(address.layer_index)
            self._door_servo_index = address.layer_index
            self._target_address = address
            self._startChuteMove()
            self._moving_started_at = now
            init_ms = (now - self._state_entered_at) * 1000
            self.logger.info(f"Positioning: init phase took {init_ms:.0f}ms, now waiting for servo+chute")
            return None

        if self._phase == "moving":
            chute_stopped = self.chute.stepper.stopped
            servo_stopped = self.irl.servos[self._door_servo_index].stopped if self._door_servo_index is not None else True
            if not chute_stopped or not servo_stopped:
                return None
            self.shared.chute_move_in_progress = False
            move_ms = (now - self._moving_started_at) * 1000
            total_ms = (now - self._state_entered_at) * 1000
            self.logger.info(f"Positioning: complete (servo+chute={move_ms:.0f}ms, total={total_ms:.0f}ms)")
            return DistributionState.READY

        return None

    def _startChuteMove(self) -> None:
        assert self._target_address is not None
        self.shared.chute_move_in_progress = True
        estimated_ms = self.chute.moveToBin(self._target_address)
        self.logger.info(
            f"Positioning: chute move started (est_ms={estimated_ms})"
        )
        self._phase = "moving"

    def cleanup(self) -> None:
        super().cleanup()
        self._phase = "init"
        self._target_address = None
        self._door_servo_index = None
        self._state_entered_at = 0.0
        self._moving_started_at = 0.0
        self.shared.chute_move_in_progress = False

    def _selectDoor(self, target_layer_index: int) -> None:
        target_servo = self.irl.servos[target_layer_index]
        if not target_servo.isClosed():
            for i, servo in enumerate(self.irl.servos):
                if i != target_layer_index and servo.isClosed():
                    servo.open()

        target_servo.close()

    def _findOrAssignBinForCategory(
        self, category_id: str
    ) -> tuple[Optional[BinAddress], bool]:
        first_unassigned: Optional[tuple[BinAddress, "Bin"]] = None

        for layer_idx, layer in enumerate(self.layout.layers):
            for section_idx, section in enumerate(layer.sections):
                for bin_idx, b in enumerate(section.bins):
                    if b.category_id == category_id:
                        return BinAddress(layer_idx, section_idx, bin_idx), False
                    if b.category_id is None and first_unassigned is None:
                        first_unassigned = (
                            BinAddress(layer_idx, section_idx, bin_idx),
                            b,
                        )

        if first_unassigned is not None:
            address, b = first_unassigned
            b.category_id = category_id
            setBinCategories(extractCategories(self.layout))
            self.logger.info(
                f"Positioning: assigned category {category_id} to bin at layer={address.layer_index}, section={address.section_index}, bin={address.bin_index}"
            )
            return address, True

        if category_id != MISC_CATEGORY:
            return self._findOrAssignBinForCategory(MISC_CATEGORY)

        return None, False
