import time
from typing import Optional, TYPE_CHECKING
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .analysis import ChannelAction, analyzeFeederChannels
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager
from defs.consts import LOOP_TICK_MS

CH3_PRECISE_HOLDOVER_MS = 2000

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor
    from irl.config import RotorPulseConfig


class Feeding(BaseState):
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
        self._last_ch2_action = ChannelAction.IDLE
        self._last_ch3_action = ChannelAction.IDLE
        self._busy_until: dict[str, float] = {}
        self._ch3_last_precise_at: float = 0.0

    def step(self) -> Optional[FeederState]:
        self._ensureExecutionThreadStarted()

        return None

    def _isStepperBusy(self, stepper: "StepperMotor") -> bool:
        return time.monotonic() < self._busy_until.get(stepper._name, 0.0)

    def _sendPulse(
        self,
        label: str,
        stepper: "StepperMotor",
        cfg: "RotorPulseConfig",
    ) -> bool:
        if self._isStepperBusy(stepper):
            self.gc.profiler.hit(f"feeder.skip.busy.{label}")
            return False
        prof = self.gc.profiler
        with prof.timer(f"feeder.move_cmd.{label}_ms"):
            pulse_degrees = stepper.degrees_for_microsteps(cfg.steps_per_pulse)
            stepper.move_degrees(pulse_degrees)
        exec_ms = stepper.estimateMoveDegreesMs(
            stepper.degrees_for_microsteps(cfg.steps_per_pulse)
        )
        cooldown_ms = max(exec_ms, cfg.delay_between_pulse_ms)
        self._busy_until[stepper._name] = time.monotonic() + cooldown_ms / 1000.0
        prof.observeValue(f"feeder.cooldown.{label}_ms", float(cooldown_ms))
        return True

    def _executionLoop(self) -> None:
        fc = self.irl_config.feeder_config
        prof = self.gc.profiler

        while not self._stop_event.is_set():
            prof.hit("feeder.execution_loop.calls")
            prof.mark("feeder.execution_loop.interval_ms")

            with prof.timer("feeder.execution_loop.total_ms"):
                with prof.timer("feeder.get_feeder_detections_ms"):
                    detections = self.vision.getFeederHeatmapDetections()
                prof.observeValue(
                    "feeder.object_detection_count", float(len(detections))
                )

                with prof.timer("feeder.analyze_state_ms"):
                    analysis = analyzeFeederChannels(self.gc, detections)

                ch2_action = analysis.ch2_action
                ch3_action = analysis.ch3_action

                now = time.monotonic()
                if ch3_action == ChannelAction.PULSE_PRECISE:
                    self._ch3_last_precise_at = now
                elif ch3_action == ChannelAction.PULSE_NORMAL and self._ch3_last_precise_at > 0:
                    if (now - self._ch3_last_precise_at) * 1000 < CH3_PRECISE_HOLDOVER_MS:
                        ch3_action = ChannelAction.PULSE_PRECISE

                if ch2_action != self._last_ch2_action:
                    self.gc.logger.info(f"state change: ch2 {self._last_ch2_action.value} -> {ch2_action.value}")
                    self._last_ch2_action = ch2_action
                if ch3_action != self._last_ch3_action:
                    self.gc.logger.info(f"state change: ch3 {self._last_ch3_action.value} -> {ch3_action.value}")
                    self._last_ch3_action = ch3_action

                can_run = self.gc.rotary_channel_steppers_can_operate_in_parallel or (
                    not self.shared.chute_move_in_progress
                )

                if not can_run:
                    prof.hit("feeder.skip.chute_in_progress")
                    self._stop_event.wait(LOOP_TICK_MS / 1000.0)
                    continue

                # channel 3 — hold precise pulses if carousel not ready to receive
                ch3_held = not self.shared.classification_ready and ch3_action == ChannelAction.PULSE_PRECISE
                if ch3_held:
                    prof.hit("feeder.skip.ch3_held_for_carousel")
                elif ch3_action == ChannelAction.PULSE_PRECISE:
                    prof.hit("feeder.path.ch3_precise")
                    if self._sendPulse("ch3_precise", self.irl.third_c_channel_rotor_stepper, fc.third_rotor_precision):
                        self.gc.logger.info("Feeder: ch3 precise, pulsing 3rd (precise)")
                elif ch3_action == ChannelAction.PULSE_NORMAL:
                    prof.hit("feeder.path.ch3_normal")
                    if self._sendPulse("ch3_normal", self.irl.third_c_channel_rotor_stepper, fc.third_rotor_normal):
                        self.gc.logger.info("Feeder: ch3 normal, pulsing 3rd")
                else:
                    prof.hit("feeder.path.ch3_idle")

                # channel 2 — only pulse if ch3 dropzone is clear
                if not analysis.ch3_dropzone_occupied:
                    if ch2_action == ChannelAction.PULSE_PRECISE:
                        prof.hit("feeder.path.ch2_precise")
                        if self._sendPulse("ch2_precise", self.irl.second_c_channel_rotor_stepper, fc.second_rotor_precision):
                            self.gc.logger.info("Feeder: ch2 precise, pulsing 2nd (precise)")
                    elif ch2_action == ChannelAction.PULSE_NORMAL:
                        prof.hit("feeder.path.ch2_normal")
                        if self._sendPulse("ch2_normal", self.irl.second_c_channel_rotor_stepper, fc.second_rotor_normal):
                            self.gc.logger.info("Feeder: ch2 normal, pulsing 2nd")
                    else:
                        prof.hit("feeder.path.ch2_idle")
                else:
                    prof.hit("feeder.skip.ch2_dropzone_occupied")

                # channel 1 — only pulse if ch2 dropzone is clear
                if not analysis.ch2_dropzone_occupied:
                    prof.hit("feeder.path.ch1")
                    if self._sendPulse("ch1", self.irl.first_c_channel_rotor_stepper, fc.first_rotor):
                        self.gc.logger.info("Feeder: clear, pulsing 1st")
                else:
                    prof.hit("feeder.skip.ch1_dropzone_occupied")

            self._stop_event.wait(LOOP_TICK_MS / 1000.0)

    def cleanup(self) -> None:
        super().cleanup()
