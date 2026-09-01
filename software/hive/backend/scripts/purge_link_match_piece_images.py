"""Remove piece-link model guesses that were wrongly synced as piece images.

The sorter's link matcher briefly attached its guesses to the same recognition
set as the C4 burst, so they synced into machine_piece_images and appeared in
labeling galleries as "this IS the piece" — poisoning training data with crops
of entirely different pieces.

Deletes those rows AND their storage files, then validates the CHECK
constraint (added NOT VALID by migration c3e5a7b9d1f4) so the table is
provably clean and such rows can never be inserted again.

Run inside the hive backend container:
    docker compose --env-file .env.prod -f docker-compose.prod.yml \
        run --rm backend python scripts/purge_link_match_piece_images.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

sys.path.insert(0, ".")

from app.database import SessionLocal  # noqa: E402
from app.services.storage_backend import get_backend  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    backend = get_backend()
    try:
        rows = db.execute(
            text(
                "SELECT id, image_key FROM machine_piece_images "
                "WHERE source = 'link_match'"
            )
        ).fetchall()
        print(f"{len(rows)} link_match rows in machine_piece_images")
        if args.dry_run:
            for r in rows[:10]:
                print("  would delete:", r.image_key)
            return 0

        deleted_files = 0
        for r in rows:
            if r.image_key:
                try:
                    backend.delete(r.image_key)
                    deleted_files += 1
                except Exception as exc:
                    print(f"  file delete failed ({r.image_key}): {exc}")
        result = db.execute(
            text("DELETE FROM machine_piece_images WHERE source = 'link_match'")
        )
        db.commit()
        print(f"deleted {result.rowcount} rows, {deleted_files} storage files")

        db.execute(
            text(
                "ALTER TABLE machine_piece_images "
                "VALIDATE CONSTRAINT ck_machine_piece_images_no_link_match"
            )
        )
        db.commit()
        print("constraint validated — table is provably link_match-free")

        remaining = db.execute(
            text("SELECT source, count(*) FROM machine_piece_images GROUP BY 1")
        ).fetchall()
        print("remaining sources:", [(r[0], r[1]) for r in remaining])
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
