from typing import Optional, Dict, List
import time
import queue
from .known_object import KnownObject
from defs.events import KnownObjectEvent, KnownObjectData, KnownObjectStatus
from logger import Logger

NUM_PLATFORMS = 4
FEEDER_POSITION = 0
CLASSIFICATION_POSITION = 1
INTERMEDIATE_POSITION = 2
EXIT_POSITION = 3


class Carousel:
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

    def _emitObjectEvent(self, obj: KnownObject) -> None:
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

    def addPieceAtFeeder(self) -> KnownObject:
        obj = KnownObject()
        self.platforms[FEEDER_POSITION] = obj
        self._log(f"added piece {obj.uuid[:8]} at feeder -> {self._platformSummary()}")
        self._emitObjectEvent(obj)
        return obj

    def rotate(self) -> Optional[KnownObject]:
        exiting = self.platforms[EXIT_POSITION]
        self.platforms = [None] + self.platforms[: NUM_PLATFORMS - 1]
        exit_str = exiting.uuid[:8] if exiting else "none"
        self._log(f"rotated, exiting={exit_str} -> {self._platformSummary()}")
        return exiting

    def getPieceAtClassification(self) -> Optional[KnownObject]:
        return self.platforms[CLASSIFICATION_POSITION]

    def getPieceAtIntermediate(self) -> Optional[KnownObject]:
        return self.platforms[INTERMEDIATE_POSITION]

    def getPieceAtExit(self) -> Optional[KnownObject]:
        return self.platforms[EXIT_POSITION]

    def markPendingClassification(self, obj: KnownObject) -> None:
        self.pending_classifications[obj.uuid] = obj
        self._log(
            f"marked {obj.uuid[:8]} pending, {len(self.pending_classifications)} in flight"
        )

    def resolveClassification(
        self, uuid: str, part_id: Optional[str], confidence: Optional[float] = None
    ) -> None:
        if uuid in self.pending_classifications:
            obj = self.pending_classifications[uuid]
            obj.part_id = part_id
            obj.confidence = confidence
            obj.status = "classified" if part_id else "unknown"
            obj.updated_at = time.time()
            del self.pending_classifications[uuid]
            self._log(
                f"resolved {uuid[:8]} -> {part_id or 'unknown'}, {len(self.pending_classifications)} in flight"
            )
            self._emitObjectEvent(obj)

    def hasPieceAtFeeder(self) -> bool:
        return self.platforms[FEEDER_POSITION] is not None

    def exitPieceReady(self) -> bool:
        piece = self.platforms[EXIT_POSITION]
        return piece is not None and piece.part_id is not None
