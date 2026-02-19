import os
import json
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class LayerConfig:
    servo_pin: int
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
    servo_pin: int
    sections: List[BinSection] = field(default_factory=list)


@dataclass
class DistributionLayout:
    layers: List[Layer] = field(default_factory=list)


VALID_BIN_SIZES = {"small", "medium", "big"}

DEFAULT_BIN_LAYOUT = BinLayoutConfig(
    layers=[
        LayerConfig(
            servo_pin=4,
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
            servo_pin=5,
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
            servo_pin=6,
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
            servo_pin=11,
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


def getBinLayout(path: Optional[str] = None) -> BinLayoutConfig:
    if path is None:
        path = os.environ.get("BIN_LAYOUT_PATH")

    if path is None:
        return DEFAULT_BIN_LAYOUT

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Bin layout config not found: {path}")

    with open(config_path, "r") as f:
        data = json.load(f)

    if "layers" not in data:
        raise ValueError("Bin layout config must have 'layers' key")

    layers = []
    for layer_idx, layer_data in enumerate(data["layers"]):
        if "servo_pin" not in layer_data:
            raise ValueError(f"Layer {layer_idx} must have 'servo_pin' key")
        if "sections" not in layer_data:
            raise ValueError(f"Layer {layer_idx} must have 'sections' key")

        servo_pin = layer_data["servo_pin"]
        if not isinstance(servo_pin, int):
            raise ValueError(f"Layer {layer_idx} servo_pin must be an integer")

        sections = []
        for section_idx, section_data in enumerate(layer_data["sections"]):
            if not isinstance(section_data, list):
                raise ValueError(
                    f"Layer {layer_idx}, section {section_idx} must be a list of bin sizes"
                )

            for bin_idx, bin_size in enumerate(section_data):
                if bin_size not in VALID_BIN_SIZES:
                    raise ValueError(
                        f"Invalid bin size '{bin_size}' at layer {layer_idx}, section {section_idx}, bin {bin_idx}. "
                        f"Must be one of: {VALID_BIN_SIZES}"
                    )

            sections.append(section_data)
        layers.append(LayerConfig(servo_pin=servo_pin, sections=sections))

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
        layers.append(Layer(servo_pin=layer_config.servo_pin, sections=sections))
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
