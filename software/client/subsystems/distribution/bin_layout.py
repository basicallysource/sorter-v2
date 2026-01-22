from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List


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


def mkDefaultLayout() -> DistributionLayout:
    sections = []
    for _ in range(6):
        bins = [Bin(size=BinSize.SMALL) for _ in range(3)]
        sections.append(BinSection(bins=bins))
    layer = Layer(sections=sections)
    return DistributionLayout(layers=[layer])


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
