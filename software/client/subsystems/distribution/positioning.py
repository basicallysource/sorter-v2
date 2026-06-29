import time
import queue
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from .chute import Chute, BinAddress
from irl.bin_layout import DistributionLayout
from irl.config import IRLInterface
from global_config import GlobalConfig
from sorting_profile import SortingProfile
from defs.known_object import PieceStage
from utils.event import known_object_to_event
from blob_manager import add_unmapped_part_id

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
            piece = carousel.get_piece_at_intermediate() if carousel else None
            if piece is None:
                self.logger.warn("Positioning: no piece at intermediate")
                return DistributionState.IDLE

            category_id = (
                self.sorting_profile.get_category_id_for_part(piece.part_id, piece.color_id)
                if piece.part_id is not None
                else None
            )
            if (
                piece.part_id is not None
                and category_id == self.sorting_profile.default_category_id
            ):
                add_unmapped_part_id(piece.part_id)
            address = self._find_bin_for_category(category_id) if category_id is not None else None

            piece.stage = PieceStage.distributing
            piece.distributing_at = time.time()
            piece.updated_at = time.time()

            if address is None:
                self.logger.info(
                    f"Positioning: no bin for category '{category_id}', dropping piece"
                )
                piece.category_id = None
                piece.destination_bin = None
                self.event_queue.put(known_object_to_event(piece))
                self._open_all_servos()
                self._phase = "dropping"
                return None

            piece.category_id = category_id
            piece.destination_bin = (address.layer_index, address.section_index, address.bin_index)
            self.event_queue.put(known_object_to_event(piece))

            self.logger.info(
                f"Positioning: moving to bin at layer={address.layer_index}, section={address.section_index}, bin={address.bin_index}"
            )
            self._select_door(address.layer_index)
            self._door_servo_index = address.layer_index
            self._target_address = address
            self._start_chute_move()
            self._moving_started_at = now
            init_ms = (now - self._state_entered_at) * 1000
            self.logger.info(f"Positioning: init phase took {init_ms:.0f}ms, now waiting for servo+chute")
            return None

        if self._phase == "dropping":
            if not all(s.stopped for s in self.irl.servos):
                return None
            total_ms = (now - self._state_entered_at) * 1000
            self.logger.info(f"Positioning: drop ready (total={total_ms:.0f}ms)")
            return DistributionState.READY

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

    def _start_chute_move(self) -> None:
        assert self._target_address is not None
        self.shared.chute_move_in_progress = True
        estimated_ms = self.chute.move_to_bin(self._target_address)
        self.logger.info(f"Positioning: chute move started (est_ms={estimated_ms})")
        self._phase = "moving"

    def cleanup(self) -> None:
        super().cleanup()
        self._phase = "init"
        self._target_address = None
        self._door_servo_index = None
        self._state_entered_at = 0.0
        self._moving_started_at = 0.0
        self.shared.chute_move_in_progress = False

    def _open_all_servos(self) -> None:
        for servo in self.irl.servos:
            servo.open()

    def _select_door(self, target_layer_index: int) -> None:
        for i, servo in enumerate(self.irl.servos):
            if i != target_layer_index:
                servo.open()
        self.irl.servos[target_layer_index].close()

    def _find_bin_for_category(self, category_id: str) -> Optional[BinAddress]:
        for layer_idx, layer in enumerate(self.layout.layers):
            for section_idx, section in enumerate(layer.sections):
                for bin_idx, b in enumerate(section.bins):
                    address = BinAddress(layer_idx, section_idx, bin_idx)
                    if self.chute.is_bin_reachable(address) and b.category_id == category_id:
                        return address
        return None
