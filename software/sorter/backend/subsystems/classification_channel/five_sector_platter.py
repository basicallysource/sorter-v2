from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Literal


DEFAULT_C4_SECTOR_COUNT = 5
DEFAULT_C4_GEAR_RATIO = 130.0 / 12.0
DEFAULT_C4_MOTOR_STEPS_PER_REVOLUTION = 200
DEFAULT_C4_MICROSTEPS = 8
DEFAULT_C4_MIN_SPEED_MICROSTEPS_PER_SECOND = 16
DEFAULT_C4_MAX_SPEED_MICROSTEPS_PER_SECOND = 4000
DEFAULT_C4_ACCELERATION_MICROSTEPS_PER_SECOND_SQ = 2500

C4Direction = Literal["shortest", "cw", "ccw"]


class C4SectorState(str, Enum):
    FREE = "free"
    OCCUPIED = "occupied"
    HANDOFF = "handoff"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class C4MotionProfile:
    min_speed_microsteps_per_second: int = DEFAULT_C4_MIN_SPEED_MICROSTEPS_PER_SECOND
    max_speed_microsteps_per_second: int = DEFAULT_C4_MAX_SPEED_MICROSTEPS_PER_SECOND
    acceleration_microsteps_per_second_sq: int | None = (
        DEFAULT_C4_ACCELERATION_MICROSTEPS_PER_SECOND_SQ
    )

    def __post_init__(self) -> None:
        if self.min_speed_microsteps_per_second <= 0:
            raise ValueError("min_speed_microsteps_per_second must be > 0")
        if self.max_speed_microsteps_per_second <= 0:
            raise ValueError("max_speed_microsteps_per_second must be > 0")
        if self.min_speed_microsteps_per_second > self.max_speed_microsteps_per_second:
            raise ValueError(
                "min_speed_microsteps_per_second must be <= max_speed_microsteps_per_second"
            )
        acceleration = self.acceleration_microsteps_per_second_sq
        if acceleration is not None and acceleration <= 0:
            raise ValueError("acceleration_microsteps_per_second_sq must be > 0")

    @classmethod
    def from_irl_config(cls, irl_config: Any) -> "C4MotionProfile":
        feeder_config = getattr(irl_config, "feeder_config", None)
        eject_config = getattr(feeder_config, "classification_channel_eject", None)
        stepper_config = getattr(irl_config, "c_channel_4_rotor_stepper", None) or getattr(
            irl_config,
            "carousel_stepper",
            None,
        )
        max_speed = getattr(eject_config, "microsteps_per_second", None)
        if not isinstance(max_speed, int) or max_speed <= 0:
            max_speed = getattr(
                stepper_config,
                "default_steps_per_second",
                DEFAULT_C4_MAX_SPEED_MICROSTEPS_PER_SECOND,
            )
        acceleration = getattr(
            eject_config,
            "acceleration_microsteps_per_second_sq",
            DEFAULT_C4_ACCELERATION_MICROSTEPS_PER_SECOND_SQ,
        )
        if acceleration is not None:
            acceleration = int(acceleration)
        return cls(
            max_speed_microsteps_per_second=int(max_speed),
            acceleration_microsteps_per_second_sq=acceleration,
        )

    def apply_to_stepper(self, stepper: Any) -> None:
        set_speed_limits = getattr(stepper, "set_speed_limits", None)
        if callable(set_speed_limits):
            set_speed_limits(
                int(self.min_speed_microsteps_per_second),
                int(self.max_speed_microsteps_per_second),
            )
        acceleration = self.acceleration_microsteps_per_second_sq
        set_acceleration = getattr(stepper, "set_acceleration", None)
        if acceleration is not None and callable(set_acceleration):
            set_acceleration(int(acceleration))


@dataclass(frozen=True, slots=True)
class C4SectorDetection:
    angle_deg: float
    confidence: float = 1.0
    track_id: Any | None = None
    label: str | None = None

    @classmethod
    def from_bbox(
        cls,
        bbox_xyxy: tuple[float, float, float, float],
        *,
        center_xy: tuple[float, float],
        confidence: float = 1.0,
        track_id: Any | None = None,
        label: str | None = None,
    ) -> "C4SectorDetection":
        x1, y1, x2, y2 = bbox_xyxy
        cx = (float(x1) + float(x2)) / 2.0
        cy = (float(y1) + float(y2)) / 2.0
        return cls(
            angle_deg=angle_deg_for_point(cx, cy, center_xy=center_xy),
            confidence=float(confidence),
            track_id=track_id,
            label=label,
        )


@dataclass(frozen=True, slots=True)
class C4SectorSnapshot:
    sector_index: int
    state: C4SectorState
    detection_count: int = 0
    max_confidence: float = 0.0
    track_ids: tuple[Any, ...] = ()

    @property
    def occupied(self) -> bool:
        return self.detection_count > 0 or self.state == C4SectorState.OCCUPIED

    def as_dict(self) -> dict[str, Any]:
        return {
            "sector_index": self.sector_index,
            "state": self.state.value,
            "occupied": self.occupied,
            "detection_count": self.detection_count,
            "max_confidence": self.max_confidence,
            "track_ids": list(self.track_ids),
        }


@dataclass(frozen=True, slots=True)
class C4SectorMove:
    from_sector: int
    to_sector: int
    sector_delta: int
    output_delta_deg: float
    motor_delta_deg: float
    motor_microsteps: int
    direction: C4Direction
    motion_profile: C4MotionProfile

    def as_dict(self) -> dict[str, Any]:
        return {
            "from_sector": self.from_sector,
            "to_sector": self.to_sector,
            "sector_delta": self.sector_delta,
            "output_delta_deg": self.output_delta_deg,
            "motor_delta_deg": self.motor_delta_deg,
            "motor_microsteps": self.motor_microsteps,
            "direction": self.direction,
            "min_speed_microsteps_per_second": (
                self.motion_profile.min_speed_microsteps_per_second
            ),
            "max_speed_microsteps_per_second": (
                self.motion_profile.max_speed_microsteps_per_second
            ),
            "acceleration_microsteps_per_second_sq": (
                self.motion_profile.acceleration_microsteps_per_second_sq
            ),
        }

    def apply_to_stepper(self, stepper: Any) -> bool:
        if self.motor_microsteps == 0:
            return True
        self.motion_profile.apply_to_stepper(stepper)
        move_steps = getattr(stepper, "move_steps", None)
        if callable(move_steps):
            return bool(move_steps(int(self.motor_microsteps)))
        move_degrees = getattr(stepper, "move_degrees", None)
        if callable(move_degrees):
            return bool(move_degrees(float(self.motor_delta_deg)))
        raise AttributeError("stepper must provide move_steps or move_degrees")


@dataclass(frozen=True, slots=True)
class C4FiveSectorPlatter:
    """Physical C-channel axis with a logical five-sector classification plate.

    Positive sector movement means increasing logical sector index. The live
    stepper direction inversion still owns the physical motor polarity.
    """

    sector_count: int = DEFAULT_C4_SECTOR_COUNT
    gear_ratio: float = DEFAULT_C4_GEAR_RATIO
    motor_steps_per_revolution: int = DEFAULT_C4_MOTOR_STEPS_PER_REVOLUTION
    microsteps: int = DEFAULT_C4_MICROSTEPS
    wall_offset_deg: float = 0.0
    motion_profile: C4MotionProfile = field(default_factory=C4MotionProfile)

    def __post_init__(self) -> None:
        if self.sector_count <= 0:
            raise ValueError("sector_count must be > 0")
        if self.motor_steps_per_revolution <= 0:
            raise ValueError("motor_steps_per_revolution must be > 0")
        if self.microsteps <= 0:
            raise ValueError("microsteps must be > 0")
        if not math.isfinite(self.gear_ratio) or self.gear_ratio <= 0.0:
            raise ValueError("gear_ratio must be finite and > 0")
        if not math.isfinite(self.wall_offset_deg):
            raise ValueError("wall_offset_deg must be finite")

    @classmethod
    def from_irl_config(
        cls,
        irl_config: Any,
        *,
        wall_offset_deg: float = 0.0,
    ) -> "C4FiveSectorPlatter":
        classification_config = getattr(irl_config, "classification_channel_config", None)
        stepper_config = getattr(irl_config, "c_channel_4_rotor_stepper", None) or getattr(
            irl_config,
            "carousel_stepper",
            None,
        )
        return cls(
            sector_count=int(
                getattr(
                    classification_config,
                    "c4_sector_count",
                    DEFAULT_C4_SECTOR_COUNT,
                )
            ),
            gear_ratio=float(
                getattr(
                    classification_config,
                    "c4_gear_ratio",
                    DEFAULT_C4_GEAR_RATIO,
                )
            ),
            motor_steps_per_revolution=int(
                getattr(
                    classification_config,
                    "c4_motor_steps_per_revolution",
                    DEFAULT_C4_MOTOR_STEPS_PER_REVOLUTION,
                )
            ),
            microsteps=int(
                getattr(stepper_config, "microsteps", DEFAULT_C4_MICROSTEPS)
            ),
            wall_offset_deg=float(wall_offset_deg),
            motion_profile=C4MotionProfile.from_irl_config(irl_config),
        )

    @property
    def sector_size_deg(self) -> float:
        return 360.0 / float(self.sector_count)

    @property
    def motor_microsteps_per_output_revolution(self) -> float:
        return (
            float(self.motor_steps_per_revolution)
            * float(self.microsteps)
            * float(self.gear_ratio)
        )

    @property
    def rounded_motor_microsteps_per_output_revolution(self) -> int:
        return int(round(self.motor_microsteps_per_output_revolution))

    def output_degrees_to_motor_microsteps(self, output_degrees: float) -> int:
        return int(
            round(
                (float(output_degrees) / 360.0)
                * self.motor_microsteps_per_output_revolution
            )
        )

    def motor_microsteps_to_motor_degrees(self, motor_microsteps: int) -> float:
        return (
            float(motor_microsteps)
            / (float(self.motor_steps_per_revolution) * float(self.microsteps))
        ) * 360.0

    def motor_microsteps_to_output_degrees(self, motor_microsteps: int) -> float:
        return self.motor_microsteps_to_motor_degrees(motor_microsteps) / float(
            self.gear_ratio
        )

    def output_degrees_to_motor_degrees(self, output_degrees: float) -> float:
        return float(output_degrees) * float(self.gear_ratio)

    def sector_position_microsteps(self, unwrapped_sector_index: int) -> int:
        sector_index = int(unwrapped_sector_index)
        turns, sector = divmod(sector_index, self.sector_count)
        return (
            int(turns) * self.rounded_motor_microsteps_per_output_revolution
            + self.output_degrees_to_motor_microsteps(
                float(sector) * self.sector_size_deg
            )
        )

    def sector_delta_count(
        self,
        from_sector: int,
        to_sector: int,
        *,
        direction: C4Direction = "shortest",
    ) -> int:
        if direction not in ("shortest", "cw", "ccw"):
            raise ValueError("direction must be one of: shortest, cw, ccw")
        start = int(from_sector) % self.sector_count
        target = int(to_sector) % self.sector_count
        forward = (target - start) % self.sector_count
        reverse = -((start - target) % self.sector_count)
        if direction == "cw":
            return int(forward)
        if direction == "ccw":
            return int(reverse)
        return int(forward if abs(forward) <= abs(reverse) else reverse)

    def sector_delta_microsteps(
        self,
        from_sector: int,
        to_sector: int,
        *,
        direction: C4Direction = "shortest",
    ) -> int:
        start = int(from_sector) % self.sector_count
        sector_delta = self.sector_delta_count(
            start,
            to_sector,
            direction=direction,
        )
        return self.sector_position_microsteps(
            start + sector_delta
        ) - self.sector_position_microsteps(start)

    def sector_move_plan(
        self,
        from_sector: int,
        to_sector: int,
        *,
        direction: C4Direction = "shortest",
    ) -> C4SectorMove:
        start = int(from_sector) % self.sector_count
        target = int(to_sector) % self.sector_count
        sector_delta = self.sector_delta_count(start, target, direction=direction)
        motor_microsteps = self.sector_delta_microsteps(
            start,
            target,
            direction=direction,
        )
        return C4SectorMove(
            from_sector=start,
            to_sector=target,
            sector_delta=sector_delta,
            output_delta_deg=float(sector_delta) * self.sector_size_deg,
            motor_delta_deg=self.motor_microsteps_to_motor_degrees(motor_microsteps),
            motor_microsteps=motor_microsteps,
            direction=direction,
            motion_profile=self.motion_profile,
        )

    def sector_for_angle(
        self,
        angle_deg: float,
        *,
        wall_offset_deg: float | None = None,
    ) -> int:
        offset = self.wall_offset_deg if wall_offset_deg is None else float(wall_offset_deg)
        relative = (float(angle_deg) - offset) % 360.0
        return int(relative / self.sector_size_deg) % self.sector_count

    def sector_center_angle_deg(
        self,
        sector_index: int,
        *,
        wall_offset_deg: float | None = None,
    ) -> float:
        offset = self.wall_offset_deg if wall_offset_deg is None else float(wall_offset_deg)
        return (
            offset
            + (float(int(sector_index) % self.sector_count) + 0.5)
            * self.sector_size_deg
        ) % 360.0

    def occupancy_from_detections(
        self,
        detections: Iterable[C4SectorDetection],
        *,
        wall_offset_deg: float | None = None,
        min_confidence: float = 0.0,
        handoff_sector: int | None = None,
        exit_sector: int | None = None,
    ) -> tuple[C4SectorSnapshot, ...]:
        states = [C4SectorState.FREE for _ in range(self.sector_count)]
        if handoff_sector is not None:
            states[int(handoff_sector) % self.sector_count] = C4SectorState.HANDOFF
        if exit_sector is not None:
            states[int(exit_sector) % self.sector_count] = C4SectorState.EXIT

        counts = [0 for _ in range(self.sector_count)]
        confidences = [0.0 for _ in range(self.sector_count)]
        track_ids: list[list[Any]] = [[] for _ in range(self.sector_count)]

        for detection in detections:
            confidence = float(detection.confidence)
            if confidence < min_confidence:
                continue
            sector = self.sector_for_angle(
                detection.angle_deg,
                wall_offset_deg=wall_offset_deg,
            )
            counts[sector] += 1
            confidences[sector] = max(confidences[sector], confidence)
            if detection.track_id is not None and detection.track_id not in track_ids[sector]:
                track_ids[sector].append(detection.track_id)
            if states[sector] == C4SectorState.FREE:
                states[sector] = C4SectorState.OCCUPIED

        return tuple(
            C4SectorSnapshot(
                sector_index=idx,
                state=states[idx],
                detection_count=counts[idx],
                max_confidence=confidences[idx],
                track_ids=tuple(track_ids[idx]),
            )
            for idx in range(self.sector_count)
        )


def angle_deg_for_point(
    x: float,
    y: float,
    *,
    center_xy: tuple[float, float],
) -> float:
    cx, cy = center_xy
    return math.degrees(math.atan2(float(y) - float(cy), float(x) - float(cx))) % 360.0
