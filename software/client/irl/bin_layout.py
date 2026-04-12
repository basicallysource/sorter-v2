from typing import Optional, List
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class LayerConfig:
    sections: List[List[str]]


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


@dataclass
class DistributionLayout:
    layers: List[Layer] = field(default_factory=list)


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
                ["big"],
                ["big"],
                ["big"],
                ["big"],
                ["big"],
                ["big"],
            ],
        ),
    ]
)


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
        layers.append(Layer(sections=sections))
    return DistributionLayout(layers=layers)


def mkDefaultLayout() -> DistributionLayout:
    return mkLayoutFromConfig(DEFAULT_BIN_LAYOUT)


def extractCategories(layout: DistributionLayout) -> list[list[list[str | None]]]:
    # Reverse so data.json layer order matches TOML config order (bottom-to-top),
    # since mkLayoutFromConfig stores layers top-first internally.
    result = [
        [[b.category_id for b in section.bins] for section in layer.sections]
        for layer in layout.layers
    ]
    return list(reversed(result))


def applyCategories(
    layout: DistributionLayout, categories: list[list[list[str | None]]]
) -> None:
    # categories is in TOML order (bottom-to-top); reverse to match internal layout order.
    reversed_categories = list(reversed(categories))
    for layer_idx, layer in enumerate(layout.layers):
        for section_idx, section in enumerate(layer.sections):
            for bin_idx, b in enumerate(section.bins):
                b.category_id = reversed_categories[layer_idx][section_idx][bin_idx]


def layoutMatchesCategories(
    layout: DistributionLayout, categories: list[list[list[str | None]]]
) -> bool:
    # categories is in TOML order (bottom-to-top); reverse to match internal layout order.
    reversed_categories = list(reversed(categories))
    if len(reversed_categories) != len(layout.layers):
        return False
    for layer_idx, layer in enumerate(layout.layers):
        if len(reversed_categories[layer_idx]) != len(layer.sections):
            return False
        for section_idx, section in enumerate(layer.sections):
            if len(reversed_categories[layer_idx][section_idx]) != len(section.bins):
                return False
    return True
