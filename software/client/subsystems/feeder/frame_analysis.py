from typing import Optional, Dict, List
import numpy as np
from .states import (
    FeederState,
    OBJECT_CLASS_ID,
    THIRD_V_CHANNEL_CLASS_ID,
    SECOND_V_CHANNEL_CLASS_ID,
    FIRST_V_CHANNEL_CLASS_ID,
)
from vision.utils import maskEdgeProximity, masksWithinDistance
from global_config import GlobalConfig

TREAT_1_AND_2_AS_ONE = True


def getNextFeederState(
    masks_by_class: Dict[int, List[np.ndarray]],
    gc: GlobalConfig,
    current_state: FeederState,
) -> Optional[FeederState]:
    proximity_threshold = gc.vision_mask_proximity_threshold
    dropzone_distance_px = gc.feeder_config.proximity_threshold_px
    object_masks = masks_by_class.get(OBJECT_CLASS_ID, [])
    third_v_masks = masks_by_class.get(THIRD_V_CHANNEL_CLASS_ID, [])
    second_v_masks = masks_by_class.get(SECOND_V_CHANNEL_CLASS_ID, [])
    first_v_masks = masks_by_class.get(FIRST_V_CHANNEL_CLASS_ID, [])

    v3_mask = third_v_masks[0] if third_v_masks else None
    v2_mask = second_v_masks[0] if second_v_masks else None
    v1_mask = first_v_masks[0] if first_v_masks else None

    objects_on_v1 = []
    objects_on_v2 = []
    objects_on_v3 = []

    for obj_mask in object_masks:
        on_v3 = (
            v3_mask is not None
            and maskEdgeProximity(obj_mask, v3_mask) > proximity_threshold
        )
        on_v2 = (
            v2_mask is not None
            and maskEdgeProximity(obj_mask, v2_mask) > proximity_threshold
        )
        on_v1 = (
            v1_mask is not None
            and maskEdgeProximity(obj_mask, v1_mask) > proximity_threshold
        )

        # priority: v3 > v2 > v1 (downstream wins)
        if on_v3:
            objects_on_v3.append(obj_mask)
        elif on_v2:
            objects_on_v2.append(obj_mask)
        elif on_v1:
            objects_on_v1.append(obj_mask)

        print("objects", len(objects_on_v3), len(objects_on_v2), len(objects_on_v1))

    if TREAT_1_AND_2_AS_ONE:
        # treat v1, v2, and v3 as feeding into v2 together
        # check if v3 dropzone is clear (no v3 objects within distance of v2)
        v3_dropzone_clear = True
        for obj_mask in objects_on_v3:
            if v2_mask is not None and masksWithinDistance(
                obj_mask, v2_mask, dropzone_distance_px
            ):
                v3_dropzone_clear = False
                break

        # if any objects on v1, v2, or v3
        if objects_on_v1 or objects_on_v2 or objects_on_v3:
            if v3_dropzone_clear:
                # run v2 (which runs both v1 and v2)
                return (
                    None
                    if current_state == FeederState.V2_LOADING
                    else FeederState.V2_LOADING
                )
            else:
                # v3 dropzone blocked, need to clear v3 first
                return (
                    None
                    if current_state == FeederState.V3_DISPENSING
                    else FeederState.V3_DISPENSING
                )

        return FeederState.IDLE

    else:
        # separate v1 and v2, check both dropzones
        # check if v2 dropzone is clear (no v2 objects within distance of v1)
        v2_dropzone_clear = True
        for obj_mask in objects_on_v2:
            if v1_mask is not None and masksWithinDistance(
                obj_mask, v1_mask, dropzone_distance_px
            ):
                v2_dropzone_clear = False
                break

        # check if v3 dropzone is clear (no v3 objects within distance of v2)
        v3_dropzone_clear = True
        for obj_mask in objects_on_v3:
            if v2_mask is not None and masksWithinDistance(
                obj_mask, v2_mask, dropzone_distance_px
            ):
                v3_dropzone_clear = False
                break

        # if object on v1, try to run v1 if dropzone clear
        if objects_on_v1:
            if v2_dropzone_clear:
                return (
                    None
                    if current_state == FeederState.V1_LOADING
                    else FeederState.V1_LOADING
                )
            # dropzone blocked, need to clear v2 first
            if objects_on_v2:
                if v3_dropzone_clear:
                    return (
                        None
                        if current_state == FeederState.V2_LOADING
                        else FeederState.V2_LOADING
                    )
                # v3 dropzone blocked, run v3
                if objects_on_v3:
                    return (
                        None
                        if current_state == FeederState.V3_DISPENSING
                        else FeederState.V3_DISPENSING
                    )

        # no object on v1, check v2
        if objects_on_v2:
            if v3_dropzone_clear:
                return (
                    None
                    if current_state == FeederState.V2_LOADING
                    else FeederState.V2_LOADING
                )
            # v3 dropzone blocked, run v3
            if objects_on_v3:
                return (
                    None
                    if current_state == FeederState.V3_DISPENSING
                    else FeederState.V3_DISPENSING
                )

        # no object on v1 or v2, check v3
        if objects_on_v3:
            return (
                None
                if current_state == FeederState.V3_DISPENSING
                else FeederState.V3_DISPENSING
            )

        return FeederState.IDLE
