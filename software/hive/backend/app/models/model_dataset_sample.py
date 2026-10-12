from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base

SPLIT_TRAIN = "train"
SPLIT_VAL = "val"
DATASET_SPLITS = (SPLIT_TRAIN, SPLIT_VAL)


class ModelDatasetSample(Base):
    """One row per Hive sample that went into a published model's dataset.

    The structured counterpart to the free-form ``training_metadata`` blob: it
    records exactly which samples a model trained on, so machine composition,
    diversity, and sample-level provenance are queryable joins instead of
    prose. Rows cascade away with either side — a deleted sample shrinks the
    recorded dataset rather than leaving a dangling reference, which is why
    aggregate counts in ``training_metadata`` remain the historical record.
    """

    __tablename__ = "model_dataset_samples"

    model_id = Column(
        UUID(as_uuid=True),
        ForeignKey("detection_models.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sample_id = Column(
        UUID(as_uuid=True),
        ForeignKey("samples.id", ondelete="CASCADE"),
        primary_key=True,
    )
    split = Column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("split IN ('train', 'val')", name="ck_model_dataset_samples_split"),
        Index("ix_model_dataset_samples_sample_id", "sample_id"),
    )


class ModelDatasetMachineCount(Base):
    """How many of a model's recorded dataset samples came from each machine,
    per split: the dataset's composition, kept as samples are recorded (and
    recounted by the stats worker, which also sees samples deleted since), so
    showing it does not join the whole dataset to the samples table."""

    __tablename__ = "model_dataset_machines"

    model_id = Column(
        UUID(as_uuid=True),
        ForeignKey("detection_models.id", ondelete="CASCADE"),
        primary_key=True,
    )
    machine_id = Column(
        UUID(as_uuid=True),
        ForeignKey("machines.id", ondelete="CASCADE"),
        primary_key=True,
    )
    train = Column(Integer, nullable=False, default=0)
    val = Column(Integer, nullable=False, default=0)
