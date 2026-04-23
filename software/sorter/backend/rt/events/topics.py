from __future__ import annotations


SYSTEM_HARDWARE_STATE = "system.hardware_state"
SYSTEM_SORTER_STATE = "system.sorter_state"

PIECE_REGISTERED = "piece.registered"
PIECE_CLASSIFIED = "piece.classified"
PIECE_DISTRIBUTED = "piece.distributed"

PERCEPTION_TRACKS = "perception.tracks"
PERCEPTION_FRAME = "perception.frame"
PERCEPTION_ROTATION = "perception.rotation"

HARDWARE_ERROR = "hardware.error"
RUNTIME_STATS = "runtime.stats"


__all__ = [
    "HARDWARE_ERROR",
    "PERCEPTION_FRAME",
    "PERCEPTION_ROTATION",
    "PERCEPTION_TRACKS",
    "PIECE_CLASSIFIED",
    "PIECE_DISTRIBUTED",
    "PIECE_REGISTERED",
    "RUNTIME_STATS",
    "SYSTEM_HARDWARE_STATE",
    "SYSTEM_SORTER_STATE",
]
