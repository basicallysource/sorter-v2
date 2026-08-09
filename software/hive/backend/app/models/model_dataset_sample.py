from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, String
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
