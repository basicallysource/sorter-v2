import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from blob_manager import BLOB_DIR
from defs.known_object import KnownObject
from global_config import GlobalConfig

RECORDS_DIR = BLOB_DIR / "records"


class RunRecorder:
    def __init__(self, gc: GlobalConfig):
        self.gc = gc
        self.run_id = gc.run_id
        self.machine_id = gc.machine_id
        self.sorting_profile_path = gc.sorting_profile_path
        self.started_at = time.time()
        self.pieces: list[KnownObject] = []
        self.active_periods: list[dict[str, float]] = []
        self._current_active_start: Optional[float] = None

    def markRunning(self) -> None:
        if self._current_active_start is None:
            self._current_active_start = time.time()

    def markPaused(self) -> None:
        if self._current_active_start is not None:
            self.active_periods.append({
                "start": self._current_active_start,
                "end": time.time(),
            })
            self._current_active_start = None

    def recordPiece(self, piece: KnownObject) -> None:
        self.pieces.append(piece)

    def save(self) -> Path:
        self.markPaused()
        ended_at = time.time()

        pieces_data = []
        for p in self.pieces:
            pieces_data.append({
                "uuid": p.uuid,
                "created_at": p.created_at,
                "classified_at": p.classified_at,
                "distributing_at": p.distributing_at,
                "distributed_at": p.distributed_at,
                "classification_status": p.classification_status.value,
                "part_id": p.part_id,
                "category_id": p.category_id,
                "confidence": p.confidence,
                "destination_bin": list(p.destination_bin) if p.destination_bin else None,
            })

        record = {
            "run_id": self.run_id,
            "machine_id": self.machine_id,
            "sorting_profile_path": self.sorting_profile_path,
            "started_at": self.started_at,
            "ended_at": ended_at,
            "active_periods": self.active_periods,
            "total_pieces": len(self.pieces),
            "pieces": pieces_data,
        }

        RECORDS_DIR.mkdir(parents=True, exist_ok=True)
        dt_str = datetime.fromtimestamp(self.started_at).strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{dt_str}_{self.run_id}.json"
        path = RECORDS_DIR / filename
        with open(path, "w") as f:
            json.dump(record, f, indent=2)
        self.gc.logger.info(f"RunRecorder: saved {len(self.pieces)} pieces to {path}")
        return path
