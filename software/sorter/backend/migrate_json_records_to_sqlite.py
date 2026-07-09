import json
import sys

import piece_records
import runtime_stat_records
from run_recorder import RECORDS_DIR


def main() -> int:
    if not RECORDS_DIR.exists():
        print(f"no records dir at {RECORDS_DIR}")
        return 0

    files = sorted(RECORDS_DIR.glob("*.json"))
    imported_pieces = 0
    imported_runs = 0
    skipped_files = 0
    for path in files:
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as e:
            print(f"skip {path.name}: {e}")
            skipped_files += 1
            continue
        run_id = data.get("run_id")
        machine_id = data.get("machine_id")

        raw_pieces = data.get("pieces")
        if isinstance(raw_pieces, list):
            for p in raw_pieces:
                if not isinstance(p, dict):
                    continue
                piece_records.recordPiece(
                    p,
                    run_id=run_id if isinstance(run_id, str) else None,
                    machine_id=machine_id if isinstance(machine_id, str) else None,
                )
                imported_pieces += 1

        runtime_stats = data.get("runtime_stats_final")
        if isinstance(run_id, str) and isinstance(runtime_stats, dict):
            runtime_stat_records.saveRun(
                run_id,
                runtime_stats,
                machine_id=machine_id if isinstance(machine_id, str) else None,
                sorting_profile_path=data.get("sorting_profile_path"),
                started_at=data.get("started_at"),
                ended_at=data.get("ended_at"),
                total_pieces=data.get("total_pieces"),
            )
            imported_runs += 1

    piece_total = piece_records.listPieces(None, limit=1)["total"]
    run_total = len(runtime_stat_records.listRuns(limit=2000))
    print(
        f"scanned {len(files)} files ({skipped_files} unreadable), "
        f"imported {imported_pieces} pieces -> table holds {piece_total}, "
        f"imported {imported_runs} runtime-stat runs -> table holds {run_total}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
