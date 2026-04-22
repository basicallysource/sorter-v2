from __future__ import annotations


SYSTEM_HARDWARE_STATE = "system.hardware_state"
SYSTEM_SORTER_STATE = "system.sorter_state"

PIECE_REGISTERED = "piece.registered"
PIECE_CLASSIFIED = "piece.classified"
PIECE_DISTRIBUTED = "piece.distributed"

PERCEPTION_TRACKS = "perception.tracks"
PERCEPTION_FRAME = "perception.frame"

HARDWARE_ERROR = "hardware.error"
RUNTIME_STATS = "runtime.stats"

# Shadow-mode parity metric: emitted by rt.shadow.iou.RollingIouTracker
# whenever the shadow pipeline wants to push its latest rolling-IoU snapshot
# to listeners (UI, log sinks, etc.).
RT_SHADOW_IOU = "rt.shadow.iou"


__all__ = [
    "HARDWARE_ERROR",
    "PERCEPTION_FRAME",
    "PERCEPTION_TRACKS",
    "PIECE_CLASSIFIED",
    "PIECE_DISTRIBUTED",
    "PIECE_REGISTERED",
    "RT_SHADOW_IOU",
    "RUNTIME_STATS",
    "SYSTEM_HARDWARE_STATE",
    "SYSTEM_SORTER_STATE",
]
