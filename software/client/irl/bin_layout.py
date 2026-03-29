import json
import os
from typing import Optional, List
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
    category_id: Optional[str] = None


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
    # reversed so that the config is setup the same as it is in real life
    # bottom most is bottom in real life
    # but the top most layers are "first" for the rest of the code
    reversedLayers = list(reversed(config.layers))
    for layer_config in reversedLayers:
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


def extractCategories(layout: DistributionLayout) -> list[list[list[str | None]]]:
    return [
        [[b.category_id for b in section.bins] for section in layer.sections]
        for layer in layout.layers
    ]


def applyCategories(
    layout: DistributionLayout, categories: list[list[list[str | None]]]
) -> None:
    for layer_idx, layer in enumerate(layout.layers):
        for section_idx, section in enumerate(layer.sections):
            for bin_idx, b in enumerate(section.bins):
                b.category_id = categories[layer_idx][section_idx][bin_idx]


def layoutMatchesCategories(
    layout: DistributionLayout, categories: list[list[list[str | None]]]
) -> bool:
    if len(categories) != len(layout.layers):
        return False
    for layer_idx, layer in enumerate(layout.layers):
        if len(categories[layer_idx]) != len(layer.sections):
            return False
        for section_idx, section in enumerate(layer.sections):
            if len(categories[layer_idx][section_idx]) != len(section.bins):
                return False
    return True
