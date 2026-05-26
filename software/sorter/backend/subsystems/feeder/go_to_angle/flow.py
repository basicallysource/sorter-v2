import time
from typing import Optional, TYPE_CHECKING

from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from subsystems.bus import StationId
from defs.channel import ChannelDetection
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager

from ..states import FeederState
from ..analysis import analyzeFeederChannels
from .config import GoToAngleConfig
from . import geometry

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor

# Motor-shaft to channel-output gear ratio. One output (LEGO wheel) degree
# requires this many motor degrees. Matches the reactive flow's constant.
CHANNEL_OUTPUT_GEAR_RATIO = 130.0 / 12.0

# Re-read the tuning config from disk at most this often so the tuning page
# takes effect live without a restart, without hammering the filesystem.
_CONFIG_TTL_S = 1.0

# After a C3 exit dispense, keep C3 blocked this long so the in-flight piece
# can register downstream before we consider another move.
CLASSIFICATION_PENDING_ADMISSION_MS = 1500


class GoToAngleFeeding(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        vision: VisionManager,
    ):
        super().__init__(irl, gc)
        self.irl_config = irl_config
        self.shared = shared
        self.vision = vision
        self._busy_until: dict[str, float] = {}
        self._config: GoToAngleConfig = GoToAngleConfig()
        self._config_loaded_at: float = 0.0
        self._classification_pending_until: float = 0.0
        machine_setup = getattr(irl_config, "machine_setup", None)
        self._classification_setup = bool(
            machine_setup is not None
            and getattr(machine_setup, "uses_classification_channel", False)
        )

    def _cfg(self) -> GoToAngleConfig:
        now = time.monotonic()
        if now - self._config_loaded_at >= _CONFIG_TTL_S:
            try:
                from toml_config import getGoToAngleConfig
                from .config import configFromDict
                self._config = configFromDict(getGoToAngleConfig())
            except Exception as exc:
                self.gc.logger.warning(f"GoToAngle: config load failed: {exc}")
            self._config_loaded_at = now
        return self._config

    def _busy(self, stepper: "StepperMotor") -> bool:
        return time.monotonic() < self._busy_until.get(stepper._name, 0.0)

    def _move(
        self,
        label: str,
        stepper: "StepperMotor",
        output_deg: float,
        settle_ms: int,
        cfg: GoToAngleConfig,
    ) -> bool:
        if self._busy(stepper):
            return False
        output_deg = max(
            cfg.min_move_output_deg, min(cfg.max_move_output_deg, abs(output_deg))
        )
        sign = 1 if cfg.forward_direction_sign >= 0 else -1
        motor_deg = sign * output_deg * CHANNEL_OUTPUT_GEAR_RATIO
        try:
            stepper.set_speed_limits(0, int(cfg.move_speed_usteps_per_s))
            stepper.set_acceleration(int(cfg.move_acceleration_usteps_per_s2))
        except Exception as exc:
            self.gc.logger.warning(f"GoToAngle: {label} speed/accel set failed: {exc}")
        success = stepper.move_degrees(motor_deg)
        exec_ms = stepper.estimateMoveDegreesMs(
            abs(motor_deg), max_speed=int(cfg.move_speed_usteps_per_s) or 5000
        )
        cooldown_ms = (max(0, exec_ms) + max(0, settle_ms)) if success else 500
        self._busy_until[stepper._name] = time.monotonic() + cooldown_ms / 1000.0
        self.gc.logger.info(
            f"GoToAngle: {label} move output={output_deg:.1f}° motor={motor_deg:.1f}° "
            f"success={success} exec_ms={exec_ms} settle_ms={settle_ms}"
        )
        return success

    def _pieces_for_channel(
        self, detections: list[ChannelDetection], channel_id: int
    ) -> list[tuple[float, ChannelDetection]]:
        out: list[tuple[float, ChannelDetection]] = []
        for det in detections:
            if det.channel_id != channel_id:
                continue
            rel = geometry.pieceRelativeAngle(det.bbox, det.channel)
            out.append((rel, det))
        return out

    def _service_channel(
        self,
        label: str,
        channel_id: int,
        stepper: "StepperMotor",
        detections: list[ChannelDetection],
        gate_open: bool,
        cfg: GoToAngleConfig,
    ) -> bool:
        if not gate_open or self._busy(stepper):
            return False
        pieces = self._pieces_for_channel(detections, channel_id)
        if not pieces:
            return False
        channel = pieces[0][1].channel
        exit_sections = channel.exit_sections
        exit_edge = geometry.sectionSetForwardEdge(exit_sections)

        # Is any piece sitting in the exit zone? If so, precisely dispense the
        # leading one (closest to the exit edge) just past the edge.
        at_exit = [
            (rel, det)
            for (rel, det) in pieces
            if geometry.sectionForRelativeAngle(rel) in exit_sections
        ]
        if at_exit and exit_edge is not None:
            leading_rel = min(
                (rel for rel, _ in at_exit),
                key=lambda r: geometry.forwardDistance(r, exit_edge),
            )
            move_deg = geometry.forwardDistance(leading_rel, exit_edge) + cfg.exit_overshoot_deg
            moved = self._move(
                f"{label}_exit", stepper, move_deg, cfg.precise_settle_after_move_ms, cfg
            )
            if moved and channel_id == 3:
                self._on_ch3_dispense()
            return moved

        # Otherwise advance the train toward the exit by the normal step.
        return self._move(
            f"{label}_advance", stepper, cfg.advance_output_deg, cfg.settle_after_move_ms, cfg
        )

    def _on_ch3_dispense(self) -> None:
        if hasattr(self.shared, "publish_piece_delivered"):
            try:
                self.shared.publish_piece_delivered(
                    source=StationId.C3,
                    target=StationId.CLASSIFICATION,
                    delivered_at_mono=time.monotonic(),
                )
            except Exception:
                pass
        self._classification_pending_until = (
            time.monotonic() + CLASSIFICATION_PENDING_ADMISSION_MS / 1000.0
        )

    def _classification_ready(self, cfg: GoToAngleConfig) -> bool:
        if not cfg.gate_ch3_on_classification_ready or not self._classification_setup:
            return True
        if time.monotonic() < self._classification_pending_until:
            return False
        return bool(self.shared.classification_ready)

    def step(self) -> Optional[FeederState]:
        cfg = self._cfg()

        can_run = self.gc.rotary_channel_steppers_can_operate_in_parallel or (
            not self.shared.chute_move_in_progress
        )
        if not can_run:
            return FeederState.FEEDING

        detections = self.vision.getFeederHeatmapDetections()
        detection_available, _reason = self.vision.getFeederDetectionAvailability()
        if not detection_available:
            return FeederState.FEEDING

        analysis = analyzeFeederChannels(self.gc, detections)

        # Downstream-first so a channel never advances onto an occupied next
        # drop zone: C3 -> C4 (classification), C2 -> C3, C1 -> C2.
        if cfg.enable_ch3:
            self._service_channel(
                "ch3",
                3,
                self.irl.c_channel_3_rotor_stepper,
                detections,
                gate_open=self._classification_ready(cfg),
                cfg=cfg,
            )
        if cfg.enable_ch2:
            self._service_channel(
                "ch2",
                2,
                self.irl.c_channel_2_rotor_stepper,
                detections,
                gate_open=not analysis.ch3_dropzone_occupied,
                cfg=cfg,
            )
        if cfg.enable_ch1:
            stepper = self.irl.c_channel_1_rotor_stepper
            if not analysis.ch2_dropzone_occupied and not self._busy(stepper):
                self._move(
                    "ch1", stepper, cfg.ch1_advance_output_deg, cfg.ch1_settle_after_move_ms, cfg
                )

        return FeederState.FEEDING

    def cleanup(self) -> None:
        super().cleanup()
