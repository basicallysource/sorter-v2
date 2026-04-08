from typing import List
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class LayerConfig:
    sections: List[List[str]]
    enabled: bool = True
    servo_open_angle: int | None = None
    servo_closed_angle: int | None = None


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


def _parseLayersDict(data: dict) -> BinLayoutConfig | None:
    raw_layers = data.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        return None

    layers = []
    for layer_idx, layer_data in enumerate(raw_layers):
        if not isinstance(layer_data, dict):
            continue
        sections_raw = layer_data.get("sections")
        if not isinstance(sections_raw, list):
            continue
        sections = []
        for section_data in sections_raw:
            if not isinstance(section_data, list):
                continue
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
        servo_open = layer_data.get("servo_open_angle")
        servo_close = layer_data.get("servo_closed_angle")
        layers.append(LayerConfig(
            sections=sections,
            enabled=enabled,
            servo_open_angle=servo_open if isinstance(servo_open, int) else None,
            servo_closed_angle=servo_close if isinstance(servo_close, int) else None,
        ))
    return BinLayoutConfig(layers=layers) if layers else None


def _loadFromToml() -> BinLayoutConfig | None:
    import os
    import tomllib

    path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            config = tomllib.load(f)
    except Exception:
        return None

    layers_table = config.get("layers")
    if not isinstance(layers_table, dict):
        return None

    raw_sections = layers_table.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        return None

    open_angles = layers_table.get("servo_open_angles", {})
    if not isinstance(open_angles, dict):
        open_angles = {}
    closed_angles = layers_table.get("servo_closed_angles", {})
    if not isinstance(closed_angles, dict):
        closed_angles = {}

    layers = []
    for i, sections in enumerate(raw_sections):
        if not isinstance(sections, list):
            continue
        valid = True
        for section in sections:
            if not isinstance(section, list):
                valid = False
                break
            for bin_size in section:
                if bin_size not in VALID_BIN_SIZES:
                    valid = False
                    break
            if not valid:
                break
        if not valid:
            continue
        open_val = open_angles.get(str(i))
        closed_val = closed_angles.get(str(i))
        layers.append(LayerConfig(
            sections=sections,
            servo_open_angle=open_val if isinstance(open_val, int) else None,
            servo_closed_angle=closed_val if isinstance(closed_val, int) else None,
        ))

    return BinLayoutConfig(layers=layers) if layers else None


def getBinLayout() -> BinLayoutConfig:
    from local_state import get_bin_layout

    data = get_bin_layout()
    if isinstance(data, dict):
        result = _parseLayersDict(data)
        if result is not None:
            return result

    toml_result = _loadFromToml()
    if toml_result is not None:
        return toml_result

    return DEFAULT_BIN_LAYOUT


def saveBinLayout(config: BinLayoutConfig) -> None:
    from local_state import set_bin_layout

    data = {
        "layers": [
            {
                "sections": layer.sections,
                "enabled": layer.enabled,
                "servo_open_angle": layer.servo_open_angle,
                "servo_closed_angle": layer.servo_closed_angle,
            }
            for layer in config.layers
        ]
    }
    set_bin_layout(data)


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
