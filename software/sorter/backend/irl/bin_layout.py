from typing import List
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class LayerConfig:
    sections: List[List[str]]
    enabled: bool = True
    servo_open_angle: int | None = None
    servo_closed_angle: int | None = None
    max_pieces_per_bin: int | None = None
    # Largest piece (max single physical dimension, mm) this layer will accept.
    # None disables the check for the layer — pieces of any size may be sent
    # here. A piece exceeding this is rerouted to the misc bottom bin.
    max_dimension_mm: float | None = None
    # Per-section on/off, one bool per section (parallel to ``sections``). A
    # disabled section is skipped during assignment exactly like a disabled
    # layer. None / wrong length is normalized to all-enabled in __post_init__.
    section_enabled: List[bool] | None = None

    def __post_init__(self) -> None:
        n = len(self.sections)
        if self.section_enabled is None:
            self.section_enabled = [True] * n
            return
        normalized = [bool(flag) for flag in self.section_enabled][:n]
        if len(normalized) < n:
            normalized += [True] * (n - len(normalized))
        self.section_enabled = normalized


# Per-layer oversize-limit defaults, keyed by the layer's total bin count.
# Denser layers (more, smaller bins) get a tighter limit. A bin count not
# listed here defaults to None (no per-layer size check). 5 is included per
# spec even though it is not currently an allowed bin count; 30 (the densest
# allowed layer) mirrors that tight limit.
_LAYER_MAX_DIMENSION_DEFAULTS_MM: dict[int, float] = {
    5: 40.0,
    6: 80.0,
    12: 80.0,
    18: 50.0,
    30: 40.0,
}


def defaultMaxDimensionForBinCount(bin_count: int) -> float | None:
    return _LAYER_MAX_DIMENSION_DEFAULTS_MM.get(bin_count)


def _binCountOf(sections: List[List[str]]) -> int:
    return sum(len(section) for section in sections)


_MISSING = object()


def _parseMaxDimension(raw: object, sections: List[List[str]]) -> float | None:
    # Missing key (legacy layout) -> bin-count default. Explicit null -> no
    # check. A number -> that limit.
    if raw is _MISSING:
        return defaultMaxDimensionForBinCount(_binCountOf(sections))
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
        return float(raw)
    return None


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
    # "Not in inventory" mode: when True this bin is part of the parallel pool
    # that only receives pieces absent from the active .bsx inventory. Such bins
    # are excluded from normal routing and vice-versa. See positioning.py.
    not_in_inventory: bool = False


@dataclass
class BinSection:
    bins: List[Bin] = field(default_factory=list)
    enabled: bool = True


@dataclass
class Layer:
    sections: List[BinSection] = field(default_factory=list)
    enabled: bool = True
    max_pieces_per_bin: int | None = None
    max_dimension_mm: float | None = None


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


# The default layout has 12-bin layers, so give each the 12-bin size limit.
for _default_layer in DEFAULT_BIN_LAYOUT.layers:
    if _default_layer.max_dimension_mm is None:
        _default_layer.max_dimension_mm = defaultMaxDimensionForBinCount(
            _binCountOf(_default_layer.sections)
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
        max_per_bin = layer_data.get("max_pieces_per_bin")
        max_dimension = _parseMaxDimension(layer_data.get("max_dimension_mm", _MISSING), sections)
        section_enabled_raw = layer_data.get("section_enabled")
        section_enabled = (
            [bool(flag) for flag in section_enabled_raw]
            if isinstance(section_enabled_raw, list)
            else None
        )
        layers.append(LayerConfig(
            sections=sections,
            enabled=enabled,
            servo_open_angle=servo_open if isinstance(servo_open, int) else None,
            servo_closed_angle=servo_close if isinstance(servo_close, int) else None,
            max_pieces_per_bin=max_per_bin if isinstance(max_per_bin, int) and max_per_bin > 0 else None,
            max_dimension_mm=max_dimension,
            section_enabled=section_enabled,
        ))
    return BinLayoutConfig(layers=layers) if layers else None


def _loadFromToml() -> BinLayoutConfig | None:
    import os
    from toml_config import loadTomlFile

    path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if not path or not os.path.exists(path):
        return None
    config = loadTomlFile(path)

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
    section_enabled_all = layers_table.get("section_enabled")
    if not isinstance(section_enabled_all, list):
        section_enabled_all = []

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
        section_enabled_raw = section_enabled_all[i] if i < len(section_enabled_all) else None
        section_enabled = (
            [bool(flag) for flag in section_enabled_raw]
            if isinstance(section_enabled_raw, list)
            else None
        )
        layers.append(LayerConfig(
            sections=sections,
            servo_open_angle=open_val if isinstance(open_val, int) else None,
            servo_closed_angle=closed_val if isinstance(closed_val, int) else None,
            max_dimension_mm=defaultMaxDimensionForBinCount(_binCountOf(sections)),
            section_enabled=section_enabled,
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
                "max_pieces_per_bin": layer.max_pieces_per_bin,
                "max_dimension_mm": layer.max_dimension_mm,
                "section_enabled": layer.section_enabled,
            }
            for layer in config.layers
        ]
    }
    set_bin_layout(data)


def mkLayoutFromConfig(config: BinLayoutConfig) -> DistributionLayout:
    layers = []
    for layer_config in config.layers:
        sections = []
        section_flags = layer_config.section_enabled or []
        for section_idx, section_config in enumerate(layer_config.sections):
            bins = []
            for bin_size_str in section_config:
                bin_size = BinSize(bin_size_str)
                bins.append(Bin(size=bin_size))
            section_enabled = section_flags[section_idx] if section_idx < len(section_flags) else True
            sections.append(BinSection(bins=bins, enabled=section_enabled))
        layers.append(Layer(
            sections=sections,
            enabled=layer_config.enabled,
            max_pieces_per_bin=layer_config.max_pieces_per_bin,
            max_dimension_mm=layer_config.max_dimension_mm,
        ))
    return DistributionLayout(layers=layers)


def mkDefaultLayout() -> DistributionLayout:
    return mkLayoutFromConfig(DEFAULT_BIN_LAYOUT)


def extractCategories(layout: DistributionLayout) -> list[list[list[list[str]]]]:
    return [
        [[list(b.category_ids) for b in section.bins] for section in layer.sections]
        for layer in layout.layers
    ]


def extractNotInInventory(layout: DistributionLayout) -> list[list[list[bool]]]:
    return [
        [[bool(b.not_in_inventory) for b in section.bins] for section in layer.sections]
        for layer in layout.layers
    ]


def applyNotInInventory(
    layout: DistributionLayout, flags: list[list[list[bool]]]
) -> None:
    for layer_idx, layer in enumerate(layout.layers):
        for section_idx, section in enumerate(layer.sections):
            for bin_idx, b in enumerate(section.bins):
                b.not_in_inventory = bool(flags[layer_idx][section_idx][bin_idx])


def emptyNotInInventory(layout: DistributionLayout) -> list[list[list[bool]]]:
    return [
        [[False for _ in section.bins] for section in layer.sections]
        for layer in layout.layers
    ]


def notInInventoryMatchesLayout(
    layout: DistributionLayout, flags: list[list[list[bool]]]
) -> bool:
    if len(flags) != len(layout.layers):
        return False
    for layer_idx, layer in enumerate(layout.layers):
        if len(flags[layer_idx]) != len(layer.sections):
            return False
        for section_idx, section in enumerate(layer.sections):
            if len(flags[layer_idx][section_idx]) != len(section.bins):
                return False
    return True


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
