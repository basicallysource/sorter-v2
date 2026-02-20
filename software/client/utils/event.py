from defs.known_object import KnownObject
from defs.events import (
    KnownObjectEvent,
    KnownObjectData,
    PieceStage,
    ClassificationStatus,
)


def knownObjectToEvent(obj: KnownObject) -> KnownObjectEvent:
    return KnownObjectEvent(
        tag="known_object",
        data=KnownObjectData(
            uuid=obj.uuid,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            stage=PieceStage(obj.stage),
            classification_status=ClassificationStatus(obj.classification_status),
            part_id=obj.part_id,
            category_id=obj.category_id,
            confidence=obj.confidence,
            destination_bin=obj.destination_bin,
            thumbnail=obj.thumbnail,
            top_image=obj.top_image,
            bottom_image=obj.bottom_image,
        ),
    )
