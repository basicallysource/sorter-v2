from typing import Optional, Dict, List
import time
import queue
from defs.known_object import KnownObject, ClassificationStatus
from utils.event import known_object_to_event
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

    def _platform_summary(self) -> str:
        return (
            "[" + ", ".join(p.uuid[:8] if p else "empty" for p in self.platforms) + "]"
        )

    def add_piece_at_feeder(self) -> KnownObject:
        obj = KnownObject()
        self.platforms[FEEDER_POSITION] = obj
        self._log(f"added piece {obj.uuid[:8]} at feeder -> {self._platform_summary()}")
        self.event_queue.put(known_object_to_event(obj))
        return obj

    def rotate(self) -> Optional[KnownObject]:
        exiting = self.platforms[EXIT_POSITION]
        self.platforms = [None] + self.platforms[: NUM_PLATFORMS - 1]
        exit_str = exiting.uuid[:8] if exiting else "none"
        self._log(f"rotated, exiting={exit_str} -> {self._platform_summary()}")
        return exiting

    def get_piece_at_classification(self) -> Optional[KnownObject]:
        return self.platforms[CLASSIFICATION_POSITION]

    def get_piece_at_intermediate(self) -> Optional[KnownObject]:
        return self.platforms[INTERMEDIATE_POSITION]

    def get_piece_at_exit(self) -> Optional[KnownObject]:
        return self.platforms[EXIT_POSITION]

    def mark_pending_classification(self, obj: KnownObject) -> None:
        self.pending_classifications[obj.uuid] = obj
        self._log(
            f"marked {obj.uuid[:8]} pending, {len(self.pending_classifications)} in flight"
        )

    def resolve_classification(
        self, uuid: str, part_id: Optional[str], color_id: str, color_name: str, confidence: Optional[float] = None
    ) -> None:
        if uuid in self.pending_classifications:
            obj = self.pending_classifications[uuid]
            obj.part_id = part_id
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
            msg = f"Carousel: resolved {uuid[:8]} -> {part_id or 'unknown'} color={color_id}, {len(self.pending_classifications)} in flight"
            if part_id is None:
                self.logger.notice(msg)
            else:
                self.logger.info(msg)
            self.event_queue.put(known_object_to_event(obj))

    def has_piece_at_feeder(self) -> bool:
        return self.platforms[FEEDER_POSITION] is not None
