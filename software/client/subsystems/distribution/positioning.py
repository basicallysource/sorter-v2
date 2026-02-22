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

POSITION_BUFFER_MS = 5000
SLEEP_AFTER_CLOSE_DOOR_MS = 1500
SLEEP_BEFORE_CHUTE_MOVE_MS = 5000


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
        self.start_time: Optional[float] = None
        self.position_duration_ms = 0
        self.command_sent = False

    def step(self) -> Optional[DistributionState]:
        if self.start_time is None:
            carousel = self.shared.carousel
            piece = carousel.getPieceAtIntermediate() if carousel else None
            if piece is None:
                self.logger.warn("Positioning: no piece at intermediate")
                return DistributionState.IDLE

            if piece.part_id is not None:
                category_id = self.sorting_profile.getCategoryIdForPart(piece.part_id)
            else:
                category_id = MISC_CATEGORY
            address, _ = self._findOrAssignBinForCategory(category_id)
            if address is None:
                self.logger.warn(
                    f"Positioning: no available bins for category {category_id}"
                )
                return DistributionState.IDLE

            piece.stage = PieceStage.distributing
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
            if SLEEP_BEFORE_CHUTE_MOVE_MS > 0:
                self.logger.info(
                    f"Positioning: extra wait before chute move {SLEEP_BEFORE_CHUTE_MOVE_MS}ms"
                )
                time.sleep(SLEEP_BEFORE_CHUTE_MOVE_MS / 1000.0)
            self.shared.chute_move_in_progress = True
            chute_move_ms = self.chute.moveToBinBlocking(
                address, timeout_buffer_ms=POSITION_BUFFER_MS
            )
            self.shared.chute_move_in_progress = False
            self.position_duration_ms = 0
            self.logger.info(
                f"Positioning: chute move confirmed (chute_move_ms={chute_move_ms}, timeout_buffer_ms={POSITION_BUFFER_MS})"
            )
            self.start_time = time.time()
            self.command_sent = True

        elapsed_ms = (time.time() - self.start_time) * 1000
        if elapsed_ms < self.position_duration_ms:
            return None

        self.logger.info("Positioning: complete, ready for drop")
        return DistributionState.READY

    def cleanup(self) -> None:
        super().cleanup()
        self.start_time = None
        self.position_duration_ms = 0
        self.command_sent = False
        self.shared.chute_move_in_progress = False

    def _selectDoor(self, target_layer_index: int) -> None:
        target_servo = self.irl.servos[target_layer_index]
        if not target_servo.isClosed():
            for i, servo in enumerate(self.irl.servos):
                if i != target_layer_index and servo.isClosed():
                    servo.open()

        target_servo.close()
        time.sleep(SLEEP_AFTER_CLOSE_DOOR_MS / 1000.0)

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
