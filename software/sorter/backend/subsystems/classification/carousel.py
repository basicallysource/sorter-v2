from typing import Optional, Dict, List
import time
import queue
from defs.known_object import KnownObject, ClassificationStatus
from utils.event import knownObjectToEvent
from logger import Logger
from piece_transport import PieceTransport, TransportAdvanceResult

NUM_PLATFORMS = 4
FEEDER_POSITION = 0
CLASSIFICATION_POSITION = 1
INTERMEDIATE_POSITION = 2
EXIT_POSITION = 3


class Carousel(PieceTransport):
    def __init__(
        self,
        logger: Logger,
        event_queue: queue.Queue,
    ):
        self.platforms: List[Optional[KnownObject]] = [None] * NUM_PLATFORMS
        self.pending_classifications: Dict[str, KnownObject] = {}
        self.logger = logger
        self.event_queue = event_queue

    def _log(self, msg: str) -> None:
        self.logger.info(f"Carousel: {msg}")

    def _platformSummary(self) -> str:
        return (
            "[" + ", ".join(p.uuid[:8] if p else "empty" for p in self.platforms) + "]"
        )

    def addPieceAtFeeder(self) -> KnownObject:
        obj = KnownObject()
        self.platforms[FEEDER_POSITION] = obj
        self._log(f"added piece {obj.uuid[:8]} at feeder -> {self._platformSummary()}")
        self.event_queue.put(knownObjectToEvent(obj))
        return obj

    def registerIncomingPiece(
        self,
        *,
        tracked_global_id: int | None = None,
    ) -> KnownObject:
        _ = tracked_global_id
        return self.addPieceAtFeeder()

    def rotate(self) -> Optional[KnownObject]:
        exiting = self.platforms[EXIT_POSITION]
        self.platforms = [None] + self.platforms[: NUM_PLATFORMS - 1]
        exit_str = exiting.uuid[:8] if exiting else "none"
        self._log(f"rotated, exiting={exit_str} -> {self._platformSummary()}")
        return exiting

    def advanceTransport(
        self,
        dropped_uuid: str | None = None,
    ) -> TransportAdvanceResult:
        _ = dropped_uuid
        exiting = self.rotate()
        return TransportAdvanceResult(
            exiting_piece=exiting,
            piece_at_classification=self.getPieceAtClassification(),
            piece_for_distribution_drop=self.getPieceForDistributionDrop(),
        )

    def getPieceAtClassification(self) -> Optional[KnownObject]:
        return self.platforms[CLASSIFICATION_POSITION]

    def getPieceAtFeeder(self) -> Optional[KnownObject]:
        return self.platforms[FEEDER_POSITION]

    def getPieceAtIntermediate(self) -> Optional[KnownObject]:
        return self.platforms[INTERMEDIATE_POSITION]

    def getPieceAtExit(self) -> Optional[KnownObject]:
        return self.platforms[EXIT_POSITION]

    def getPieceForDistributionPositioning(self) -> Optional[KnownObject]:
        return self.getPieceAtIntermediate()

    def getPieceForDistributionDrop(self) -> Optional[KnownObject]:
        return self.getPieceAtExit()

    def markPendingClassification(self, obj: KnownObject) -> None:
        self.pending_classifications[obj.uuid] = obj
        self._log(
            f"marked {obj.uuid[:8]} pending, {len(self.pending_classifications)} in flight"
        )

    def resolveClassification(
        self,
        uuid: str,
        part_id: Optional[str],
        color_id: str,
        color_name: str,
        confidence: Optional[float] = None,
        *,
        part_name: Optional[str] = None,
        part_category: Optional[str] = None,
    ) -> bool:
        if uuid not in self.pending_classifications:
            return False

        obj = self.pending_classifications[uuid]
        obj.part_id = part_id
        obj.part_name = part_name
        obj.part_category = part_category
        obj.color_id = color_id
        obj.color_name = color_name
        obj.confidence = confidence
        obj.classification_status = (
            ClassificationStatus.classified
            if part_id
            else ClassificationStatus.unknown
        )
        obj.classified_at = time.time()
        obj.updated_at = time.time()
        del self.pending_classifications[uuid]
        self._log(
            f"resolved {uuid[:8]} -> {part_id or 'unknown'} color={color_id}, {len(self.pending_classifications)} in flight"
        )
        self.event_queue.put(knownObjectToEvent(obj))
        return True

    def hasPieceAtFeeder(self) -> bool:
        return self.platforms[FEEDER_POSITION] is not None

    def getActivePieceCount(self) -> int:
        return sum(1 for piece in self.platforms if piece is not None)
