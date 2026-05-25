"""One-shot: compute pHash for every Sample row that doesn't have one yet.

Run after the migration that added ``samples.phash``. Subsequent uploads
populate the column at insert time; this script catches the historical
backlog. Safe to re-run — it's idempotent.

Usage (from software/hive/backend):
  uv run python -m scripts.backfill_phash [--batch-size 200] [--limit N]
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Iterable

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.sample import Sample
from app.services.image_hashing import compute_phash_bytes
from app.services.storage_backend import get_backend


logger = logging.getLogger("backfill_phash")


def _iter_missing(db: Session, *, batch_size: int) -> Iterable[Sample]:
    last_id: str | None = None
    while True:
        q = db.query(Sample).filter(Sample.phash.is_(None)).order_by(Sample.id)
        if last_id is not None:
            q = q.filter(Sample.id > last_id)
        rows = q.limit(batch_size).all()
        if not rows:
            return
        for sample in rows:
            yield sample
        last_id = rows[-1].id


def run(*, batch_size: int = 200, limit: int | None = None) -> dict[str, int]:
    backend = get_backend()
    processed = 0
    hashed = 0
    skipped_missing_file = 0
    skipped_bad_image = 0

    db = SessionLocal()
    try:
        for sample in _iter_missing(db, batch_size=batch_size):
            if limit is not None and processed >= limit:
                break
            processed += 1
            try:
                data = backend.read_bytes(sample.image_path)
            except FileNotFoundError:
                skipped_missing_file += 1
                continue
            ph = compute_phash_bytes(data)
            if ph is None:
                skipped_bad_image += 1
                continue
            sample.phash = ph
            hashed += 1
            if processed % batch_size == 0:
                db.commit()
                logger.info(
                    "Progress: %d processed (%d hashed, %d missing, %d undecodable)",
                    processed, hashed, skipped_missing_file, skipped_bad_image,
                )
        db.commit()
    finally:
        db.close()

    return {
        "processed": processed,
        "hashed": hashed,
        "skipped_missing_file": skipped_missing_file,
        "skipped_bad_image": skipped_bad_image,
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--limit", type=int, default=None, help="Stop after N samples (debug)")
    args = parser.parse_args(argv)

    summary = run(batch_size=args.batch_size, limit=args.limit)
    logger.info("Done: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
