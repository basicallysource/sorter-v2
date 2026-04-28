from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ZoneConfig(BaseModel):
    """Zone descriptor: kind tag + kind-specific params dict."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["rect", "polygon", "polar"]
    params: dict[str, Any]


class FeedConfig(BaseModel):
    """One logical feed fed by one camera (1:1 target, SplitFeed shim otherwise)."""

    model_config = ConfigDict(extra="forbid")

    feed_id: str
    camera_id: str
    purpose: Literal["c2_feed", "c3_feed", "c4_feed", "aux"]
    zone: ZoneConfig
    picture_settings: dict[str, Any] | None = None
    fps_target: float = 10.0


class FilterConfig(BaseModel):
    """One filter entry in a pipeline's filter chain."""

    model_config = ConfigDict(extra="forbid")

    key: str
    params: dict[str, Any] = Field(default_factory=dict)


class PipelineConfig(BaseModel):
    """Perception pipeline wiring for one feed."""

    model_config = ConfigDict(extra="forbid")

    feed_id: str
    detector: dict[str, Any]
    tracker: dict[str, Any]
    filters: list[FilterConfig] = Field(default_factory=list)
    calibration: dict[str, Any] | None = None


class RuntimeConfig(BaseModel):
    """One hardware-component runtime, including pull-coupling wiring."""

    model_config = ConfigDict(extra="forbid")

    runtime_id: Literal["c1", "c2", "c3", "c4", "distributor"]
    feeds: list[str] = Field(default_factory=list)
    downstream: str | None = None
    capacity_to_downstream: int = 1
    admission: dict[str, Any] = Field(default_factory=dict)
    ejection_timing: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)


class ClassificationConfig(BaseModel):
    """Global classifier selection for RuntimeC4."""

    model_config = ConfigDict(extra="forbid")

    classifier: dict[str, Any]


class DistributionConfig(BaseModel):
    """Global rules-engine selection for RuntimeDistributor."""

    model_config = ConfigDict(extra="forbid")

    rules_engine: dict[str, Any]


class SorterConfig(BaseModel):
    """Top-level, fully validated runtime configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cameras: list[dict[str, Any]] = Field(default_factory=list)
    feeds: list[FeedConfig] = Field(default_factory=list)
    pipelines: list[PipelineConfig] = Field(default_factory=list)
    runtimes: list[RuntimeConfig] = Field(default_factory=list)
    classification: ClassificationConfig
    distribution: DistributionConfig


__all__ = [
    "ClassificationConfig",
    "DistributionConfig",
    "FeedConfig",
    "FilterConfig",
    "PipelineConfig",
    "RuntimeConfig",
    "SorterConfig",
    "ZoneConfig",
]
