"""A model's recorded dataset, by machine: kept as samples are recorded.

``model_dataset_samples`` lists every sample a published model trained on; the
model page shows how many came from each machine. Counting that per view
joined the whole dataset (tens of thousands of rows) to the samples table.
Instead the counts are kept in ``model_dataset_machines``: added to as the
publisher records samples (``count_in``), and recounted by the stats worker
(``recount``), which also catches samples deleted since.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.model_dataset_sample import SPLIT_TRAIN, SPLIT_VAL, ModelDatasetMachineCount, ModelDatasetSample
from app.models.sample import Sample


def count_in(db: Session, model_id: UUID, recorded: Iterable[tuple[Any, str]]) -> None:
    """Add newly recorded samples, as (machine_id, split) pairs, to the
    model's counts. The caller commits."""
    added = Counter(recorded)
    if not added:
        return
    machines = {machine_id for machine_id, _ in added}
    rows = {
        row.machine_id: row
        for row in db.query(ModelDatasetMachineCount).filter(
            ModelDatasetMachineCount.model_id == model_id, ModelDatasetMachineCount.machine_id.in_(machines)
        )
    }
    for machine_id in machines:
        row = rows.get(machine_id)
        if row is None:
            row = ModelDatasetMachineCount(model_id=model_id, machine_id=machine_id, train=0, val=0)
            db.add(row)
        row.train = (row.train or 0) + added.get((machine_id, SPLIT_TRAIN), 0)
        row.val = (row.val or 0) + added.get((machine_id, SPLIT_VAL), 0)


def reset(db: Session, model_id: UUID) -> None:
    db.query(ModelDatasetMachineCount).filter(ModelDatasetMachineCount.model_id == model_id).delete(
        synchronize_session=False
    )


def total(db: Session, model_id: UUID) -> int:
    return int(
        db.query(func.coalesce(func.sum(ModelDatasetMachineCount.train + ModelDatasetMachineCount.val), 0))
        .filter(ModelDatasetMachineCount.model_id == model_id)
        .scalar()
        or 0
    )


def recount(db: Session) -> int:
    """Rebuild every model's counts from the recorded samples (the stats
    worker's pass). Returns rows written; commits."""
    db.query(ModelDatasetMachineCount).delete(synchronize_session=False)
    rows = (
        db.query(
            ModelDatasetSample.model_id,
            Sample.machine_id,
            func.count().filter(ModelDatasetSample.split != SPLIT_VAL),
            func.count().filter(ModelDatasetSample.split == SPLIT_VAL),
        )
        .join(Sample, Sample.id == ModelDatasetSample.sample_id)
        .group_by(ModelDatasetSample.model_id, Sample.machine_id)
        .all()
    )
    db.add_all(
        ModelDatasetMachineCount(model_id=model_id, machine_id=machine_id, train=int(train), val=int(val))
        for model_id, machine_id, train, val in rows
    )
    db.commit()
    return len(rows)
