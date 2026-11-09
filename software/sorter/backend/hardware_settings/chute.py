"""The chute's settings, kept in [chute]: which kind of chute it is
(subsystems/distribution/chute_variants.py), its measured gear ratio, its aiming
geometry, its home sensor (input and polarity), its operating speed, its
position check (whether and how often it checks itself against its home sensor,
see subsystems/distribution/position_check.py), and the bin that takes the
pieces no other bin wants, on a chute nothing falls out of.

readChuteSettings is the only reader (start-up and the routes) and
saveChuteSettings the only writer; applyChuteSettings puts the settings on the
running Chute, which sets its operating speed on the stepper before every move.
The geometry is canonical as num_sections / section_width_deg /
first_section_offset_deg (see subsystems/distribution/chute.py). The older
first_bin_center / pillar_width_deg pair is still read when those are absent,
and is kept in step on every save so an older build aims the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import machine_toml
from subsystems.distribution.chute_variants import DEFAULT_VARIANT, VARIANTS, ChuteVariant, variantFor

CHUTE = "chute"

DEFAULT_NUM_SECTIONS = 6
DEFAULT_PILLAR_WIDTH_DEG = 8.25
DEFAULT_SECTION_WIDTH_DEG = 360.0 / DEFAULT_NUM_SECTIONS - DEFAULT_PILLAR_WIDTH_DEG
DEFAULT_FIRST_SECTION_OFFSET_DEG = 8.25
DEFAULT_OPERATING_SPEED_MICROSTEPS_PER_SEC = 3000
# The SKR Pico distribution board's E0-STOP input, which the setup wizard wires.
DEFAULT_HOME_PIN_CHANNEL = 3
# For boards whose profile names no polarity (see BoardProfile).
DEFAULT_ENDSTOP_ACTIVE_HIGH = True
DEFAULT_POSITION_CHECK = False
DEFAULT_POSITION_CHECK_EVERY = 50

GEOMETRY = ("num_sections", "section_width_deg", "first_section_offset_deg")
LEGACY_GEOMETRY = ("first_bin_center", "pillar_width_deg")
CHANGEABLE = GEOMETRY + LEGACY_GEOMETRY + (
    "variant",
    "gear_ratio",
    "discard_bin",
    "endstop_active_high",
    "operating_speed_microsteps_per_second",
    "position_check",
    "position_check_every",
)


@dataclass(frozen=True)
class ChuteSettings:
    num_sections: int
    section_width_deg: float
    first_section_offset_deg: float
    endstop_active_high: bool
    home_pin_channel: int
    operating_speed_microsteps_per_second: int
    # Check the chute's position against its home switch every this many pieces.
    position_check: bool
    position_check_every: int
    # Which kind of chute this is: a key of chute_variants.VARIANTS.
    variant_key: str = DEFAULT_VARIANT.key
    # Motor turns for one turn of the chute as measured on this machine, or
    # None to use the ratio its kind of chute is built with.
    gear_ratio: float | None = None
    # (layer, section, bin), all counted from 0: where the pieces no other bin
    # wants go. Only a chute nothing falls out of needs one.
    discard_bin: tuple[int, int, int] | None = None
    # The settings machine.toml holds; the others are defaults.
    saved: frozenset[str] = frozenset()

    @property
    def variant(self) -> ChuteVariant:
        return variantFor(self.variant_key)

    @property
    def section_pitch_deg(self) -> float:
        return 360.0 / self.num_sections

    @property
    def pillar_width_deg(self) -> float:
        return self.section_pitch_deg - self.section_width_deg

    def describe(self) -> str:
        return (
            f"{self.variant.label}, "
            f"{f'{self.gear_ratio:g} motor turns a turn (measured)' if self.gear_ratio else 'gear ratio as built'}, "
            f"discard bin {self.discard_bin if self.discard_bin else 'none'}, "
            f"{self.num_sections} sections {self.section_width_deg:.2f}° wide, the first at "
            f"{self.first_section_offset_deg:.2f}°, endstop on input {self.home_pin_channel} "
            f"active {'high' if self.endstop_active_high else 'low'}, operating speed "
            f"{self.operating_speed_microsteps_per_second} µsteps/s, position check "
            f"{f'every {self.position_check_every} pieces' if self.position_check else 'off'}; from machine.toml: "
            f"{', '.join(sorted(self.saved)) or 'none, all defaults'}"
        )


def boardDefaults(
    input_aliases: Mapping[str, int],
    endstop_active_high: bool | None,
    variant_key: str | None = None,
) -> dict[str, Any]:
    """The home input and polarity a distribution board comes with, and the kind
    of chute it is made for if it is made for one, as readChuteSettings takes them."""
    return {
        "home_pin_channel": input_aliases.get("chute_home", DEFAULT_HOME_PIN_CHANNEL),
        "endstop_active_high": (
            DEFAULT_ENDSTOP_ACTIVE_HIGH if endstop_active_high is None else endstop_active_high
        ),
        "variant_key": variant_key or DEFAULT_VARIANT.key,
    }


def readChuteSettings(
    config: Mapping[str, Any] | None = None,
    *,
    home_pin_channel: int = DEFAULT_HOME_PIN_CHANNEL,
    endstop_active_high: bool = DEFAULT_ENDSTOP_ACTIVE_HIGH,
    variant_key: str = DEFAULT_VARIANT.key,
    logger: Any = None,
) -> ChuteSettings:
    """The chute's settings. `home_pin_channel`, `endstop_active_high` and
    `variant_key` are the distribution board's own, used unless machine.toml
    sets them."""
    if config is None:
        config = machine_toml.read()
    raw = config.get(CHUTE)
    if raw is None:
        raw = {}
    elif not isinstance(raw, dict):
        _warn(logger, "[chute] must be a table; using the defaults.")
        raw = {}
    saved: set[str] = set()

    def read(key: str, default: Any, valid: Any, expects: str) -> Any:
        if key not in raw:
            return default
        value = raw[key]
        if valid(value):
            saved.add(key)
            return value
        _warn(logger, f"Ignoring chute.{key} = {value!r}: expected {expects}.")
        return default

    num_sections = read("num_sections", DEFAULT_NUM_SECTIONS, _positiveInt, "an integer of at least 1")
    pitch = 360.0 / num_sections
    pillar = float(read(
        "pillar_width_deg", DEFAULT_PILLAR_WIDTH_DEG,
        lambda value: _isNumber(value) and 0 <= value < pitch, f"0 to under {pitch:g}°",
    ))
    first_bin_center = float(read("first_bin_center", DEFAULT_FIRST_SECTION_OFFSET_DEG, _isNumber, "a number"))
    fallback_width = min(DEFAULT_SECTION_WIDTH_DEG, pitch - 0.01)
    if "section_width_deg" in raw:
        section_width = float(read(
            "section_width_deg", fallback_width,
            lambda value: _isNumber(value) and 0 < value < pitch, f"over 0 and under {pitch:g}°",
        ))
    elif 0 < pitch - pillar < pitch:
        section_width = pitch - pillar
        if "pillar_width_deg" in saved:
            saved.add("section_width_deg")
    else:
        section_width = fallback_width
    if "first_section_offset_deg" in raw:
        offset = float(read("first_section_offset_deg", first_bin_center, _isNumber, "a number"))
    else:
        offset = first_bin_center
        if "first_bin_center" in saved:
            saved.add("first_section_offset_deg")
    saved -= set(LEGACY_GEOMETRY)
    variant = variantFor(read("variant", variant_key, _isVariant, f"one of {', '.join(VARIANTS)}"))
    return ChuteSettings(
        num_sections=num_sections,
        section_width_deg=section_width,
        first_section_offset_deg=offset,
        endstop_active_high=read("endstop_active_high", endstop_active_high, _isBool, "true or false"),
        home_pin_channel=read("home_pin_channel", home_pin_channel, _nonNegativeInt, "an input number"),
        operating_speed_microsteps_per_second=read(
            "operating_speed_microsteps_per_second", DEFAULT_OPERATING_SPEED_MICROSTEPS_PER_SEC,
            _positiveInt, "a whole number of µsteps/s above 0",
        ),
        # A chute that turns without limit never comes back to a stop, so
        # whatever its position is off by stays: it checks itself unless told not to.
        position_check=read(
            "position_check", DEFAULT_POSITION_CHECK or variant.turns_freely, _isBool, "true or false"
        ),
        position_check_every=read(
            "position_check_every", DEFAULT_POSITION_CHECK_EVERY, _positiveInt, "a whole number of pieces above 0",
        ),
        variant_key=variant.key,
        gear_ratio=_floatOrNone(read("gear_ratio", None, _isGearRatio, "a number of motor turns above 0")),
        discard_bin=_binOrNone(read("discard_bin", None, _isBin, "[layer, section, bin], counted from 0")),
        saved=frozenset(saved),
    )


def saveChuteSettings(
    changes: Mapping[str, Any],
    *,
    home_pin_channel: int = DEFAULT_HOME_PIN_CHANNEL,
    endstop_active_high: bool = DEFAULT_ENDSTOP_ACTIVE_HIGH,
    variant_key: str = DEFAULT_VARIANT.key,
) -> ChuteSettings:
    """Save some of the chute's settings; raises ValueError naming a bad one,
    saving none. The geometry can be given the aiming way (GEOMETRY) or the
    legacy way (LEGACY_GEOMETRY), and both are written in step. `gear_ratio`
    and `discard_bin` given as None are taken out again."""
    for key in changes:
        if key not in CHANGEABLE:
            raise ValueError(f"There is no chute setting '{key}'.")
    with machine_toml.edit() as config:
        current = readChuteSettings(config)
        num_sections = changes.get("num_sections", current.num_sections)
        if not _positiveInt(num_sections):
            raise ValueError("num_sections must be an integer of at least 1.")
        pitch = 360.0 / num_sections
        width, offset = current.section_width_deg, current.first_section_offset_deg
        if any(key in changes for key in GEOMETRY):
            width = changes.get("section_width_deg", width)
            offset = changes.get("first_section_offset_deg", offset)
        elif any(key in changes for key in LEGACY_GEOMETRY):
            pillar = changes.get("pillar_width_deg", current.pillar_width_deg)
            if not (_isNumber(pillar) and 0 <= pillar < pitch):
                raise ValueError(f"pillar_width_deg must be from 0 to under the section pitch, {pitch:g}°.")
            width = pitch - pillar
            offset = changes.get("first_bin_center", offset)
        if not (_isNumber(width) and 0 < width < pitch):
            raise ValueError(f"section_width_deg must be over 0 and under the section pitch, {pitch:g}°.")
        if not _isNumber(offset):
            raise ValueError("The first section's offset must be a number of degrees.")
        speed = changes.get("operating_speed_microsteps_per_second")
        if speed is not None and not _positiveInt(speed):
            raise ValueError("operating_speed_microsteps_per_second must be a whole number above 0.")
        polarity = changes.get("endstop_active_high")
        if polarity is not None and not _isBool(polarity):
            raise ValueError("endstop_active_high must be true or false.")
        check = changes.get("position_check")
        if check is not None and not _isBool(check):
            raise ValueError("position_check must be true or false.")
        every = changes.get("position_check_every")
        if every is not None and not _positiveInt(every):
            raise ValueError("position_check_every must be a whole number of pieces above 0.")
        variant = changes.get("variant")
        if variant is not None and not _isVariant(variant):
            raise ValueError(f"variant must be one of {', '.join(VARIANTS)}.")
        gear_ratio = changes.get("gear_ratio")
        if gear_ratio is not None and not _isGearRatio(gear_ratio):
            raise ValueError("gear_ratio must be a number of motor turns above 0.")
        discard_bin = changes.get("discard_bin")
        if discard_bin is not None and not _isBin(discard_bin):
            raise ValueError("discard_bin must be [layer, section, bin], counted from 0.")

        chute = config.get(CHUTE)
        if not isinstance(chute, dict):
            chute = {}
            config[CHUTE] = chute
        if any(key in changes for key in GEOMETRY + LEGACY_GEOMETRY):
            chute.update(
                num_sections=num_sections,
                section_width_deg=round(float(width), 4),
                first_section_offset_deg=round(float(offset), 4),
                pillar_width_deg=round(pitch - float(width), 4),
                first_bin_center=round(float(offset), 4),
            )
        if polarity is not None:
            chute["endstop_active_high"] = polarity
        if speed is not None:
            chute["operating_speed_microsteps_per_second"] = speed
        if check is not None:
            chute["position_check"] = check
        if every is not None:
            chute["position_check_every"] = every
        if variant is not None:
            chute["variant"] = variant
        if "gear_ratio" in changes:
            if gear_ratio is None:
                chute.pop("gear_ratio", None)
            else:
                chute["gear_ratio"] = round(float(gear_ratio), 5)
        if "discard_bin" in changes:
            if discard_bin is None:
                chute.pop("discard_bin", None)
            else:
                chute["discard_bin"] = [int(index) for index in discard_bin]
    return readChuteSettings(
        config,
        home_pin_channel=home_pin_channel,
        endstop_active_high=endstop_active_high,
        variant_key=variant_key,
    )


def applyChuteSettings(chute: Any, settings: ChuteSettings) -> None:
    """Put the settings on a running Chute. Its home input and which kind of
    chute it is are fixed when the hardware starts; the rest takes effect on
    its next move."""
    chute.setGearRatio(settings.gear_ratio)
    chute.setDiscardBin(settings.discard_bin)
    chute.setAimingCalibration(
        settings.num_sections,
        settings.section_width_deg,
        settings.first_section_offset_deg,
        settings.endstop_active_high,
    )
    chute.setOperatingSpeed(settings.operating_speed_microsteps_per_second)
    chute.setPositionCheck(settings.position_check, settings.position_check_every)


def _isNumber(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _isBool(value: Any) -> bool:
    return isinstance(value, bool)


def _positiveInt(value: Any) -> bool:
    return type(value) is int and value >= 1


def _isVariant(value: Any) -> bool:
    return isinstance(value, str) and value in VARIANTS


def _isGearRatio(value: Any) -> bool:
    return _isNumber(value) and value > 0


def _isBin(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(_nonNegativeInt(index) for index in value)
    )


def _floatOrNone(value: Any) -> float | None:
    return None if value is None else float(value)


def _binOrNone(value: Any) -> tuple[int, int, int] | None:
    return None if value is None else (int(value[0]), int(value[1]), int(value[2]))


def _nonNegativeInt(value: Any) -> bool:
    return type(value) is int and value >= 0


def _warn(logger: Any, message: str) -> None:
    if logger is not None:
        logger.warning(message)
