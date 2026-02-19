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
from defs.events import (
    KnownObjectEvent,
    KnownObjectData,
    KnownObjectStatus,
)

POSITION_DURATION_MS = 3000


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
        self.command_sent = False

    def _emitObjectEvent(self, obj) -> None:
        event = KnownObjectEvent(
            tag="known_object",
            data=KnownObjectData(
                uuid=obj.uuid,
                created_at=obj.created_at,
                updated_at=obj.updated_at,
                status=KnownObjectStatus(obj.status),
                part_id=obj.part_id,
                category_id=obj.category_id,
                confidence=obj.confidence,
                destination_bin=obj.destination_bin,
                thumbnail=obj.thumbnail,
                top_image=obj.top_image,
                bottom_image=obj.bottom_image,
            ),
        )
        self.event_queue.put(event)

    def step(self) -> Optional[DistributionState]:
        if self.start_time is None:
            self.start_time = time.time()
            piece = self.shared.pending_piece
            if piece is None:
                self.logger.warn("Positioning: no pending piece")
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

            piece.category_id = category_id
            piece.destination_bin = (
                address.layer_index,
                address.section_index,
                address.bin_index,
            )
            piece.updated_at = time.time()
            self._emitObjectEvent(piece)

            self.logger.info(
                f"Positioning: moving to bin at layer={address.layer_index}, section={address.section_index}, bin={address.bin_index}"
            )
            self.chute.moveToBin(address)
            self.command_sent = True

        elapsed_ms = (time.time() - self.start_time) * 1000
        if elapsed_ms < POSITION_DURATION_MS:
            return None

        self.logger.info("Positioning: complete, ready for drop")
        return DistributionState.READY

    def cleanup(self) -> None:
        super().cleanup()
        self.start_time = None
        self.command_sent = False

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
