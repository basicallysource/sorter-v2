import json
import os
from typing import List
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class LayerConfig:
    sections: List[List[str]]
    enabled: bool = True


@dataclass
class BinLayoutConfig:
    layers: List[LayerConfig]


class BinSize(Enum):
    SMALL = "small"
    MEDIUM = "medium"
    BIG = "big"


@dataclass
class Bin:
    size: BinSize
    category_ids: list[str] = field(default_factory=list)


@dataclass
class BinSection:
    bins: List[Bin] = field(default_factory=list)


@dataclass
class Layer:
    sections: List[BinSection] = field(default_factory=list)
    enabled: bool = True


@dataclass
class DistributionLayout:
    layers: List[Layer] = field(default_factory=list)


VALID_BIN_SIZES = {"small", "medium", "big"}


DEFAULT_BIN_LAYOUT = BinLayoutConfig(
    layers=[
        LayerConfig(
            sections=[
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
            ],
        ),
        LayerConfig(
            sections=[
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
            ],
        ),
        LayerConfig(
            sections=[
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
            ],
        ),
        LayerConfig(
            sections=[
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
                ["medium", "medium"],
            ],
        ),
    ]
)


def getBinLayout() -> BinLayoutConfig:
    path = os.environ.get("BIN_LAYOUT_PATH")
    if path is None:
        return DEFAULT_BIN_LAYOUT

    with open(path, "r") as f:
        data = json.load(f)

    layers = []
    for layer_idx, layer_data in enumerate(data["layers"]):
        sections = []
        for section_data in layer_data["sections"]:
            for bin_size in section_data:
                if bin_size not in VALID_BIN_SIZES:
                    raise ValueError(
                        f"Invalid bin size '{bin_size}' in layer {layer_idx}. "
                        f"Must be one of: {VALID_BIN_SIZES}"
                    )
            sections.append(section_data)
        enabled = layer_data.get("enabled", True)
        if not isinstance(enabled, bool):
            enabled = True
        layers.append(LayerConfig(sections=sections, enabled=enabled))
    return BinLayoutConfig(layers=layers)


def mkLayoutFromConfig(config: BinLayoutConfig) -> DistributionLayout:
    layers = []
    for layer_config in config.layers:
        sections = []
        for section_config in layer_config.sections:
            bins = []
            for bin_size_str in section_config:
                bin_size = BinSize(bin_size_str)
                bins.append(Bin(size=bin_size))
            sections.append(BinSection(bins=bins))
        layers.append(Layer(sections=sections, enabled=layer_config.enabled))
    return DistributionLayout(layers=layers)


def mkDefaultLayout() -> DistributionLayout:
    return mkLayoutFromConfig(DEFAULT_BIN_LAYOUT)


def extractCategories(layout: DistributionLayout) -> list[list[list[list[str]]]]:
    return [
        [[list(b.category_ids) for b in section.bins] for section in layer.sections]
        for layer in layout.layers
    ]


def applyCategories(
    layout: DistributionLayout, categories: list[list[list[list[str]]]]
) -> None:
    for layer_idx, layer in enumerate(layout.layers):
        for section_idx, section in enumerate(layer.sections):
            for bin_idx, b in enumerate(section.bins):
                bin_category_ids = categories[layer_idx][section_idx][bin_idx]
                if not isinstance(bin_category_ids, list):
                    raise ValueError("bin categories must be list[str]")
                if any(not isinstance(category_id, str) for category_id in bin_category_ids):
                    raise ValueError("bin categories must be list[str]")
                b.category_ids = list(bin_category_ids)


def layoutMatchesCategories(
    layout: DistributionLayout, categories: list[list[list[list[str]]]]
) -> bool:
    if len(categories) != len(layout.layers):
        return False
    for layer_idx, layer in enumerate(layout.layers):
        if len(categories[layer_idx]) != len(layer.sections):
            return False
        for section_idx, section in enumerate(layer.sections):
            if len(categories[layer_idx][section_idx]) != len(section.bins):
                return False
            for bin_category_ids in categories[layer_idx][section_idx]:
                if not isinstance(bin_category_ids, list):
                    return False
                if any(not isinstance(category_id, str) for category_id in bin_category_ids):
                    return False
    return True
