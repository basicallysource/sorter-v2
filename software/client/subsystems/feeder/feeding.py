import time
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .analysis import ChannelAction, analyzeFeederChannels
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager


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

    def step(self) -> Optional[FeederState]:
        self._ensureExecutionThreadStarted()

        if not self.shared.classification_ready:
            return FeederState.IDLE
        return None

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

                if ch2_action != self._last_ch2_action:
                    self.gc.logger.info(f"state change: ch2 {self._last_ch2_action.value} -> {ch2_action.value}")
                    self._last_ch2_action = ch2_action
                if ch3_action != self._last_ch3_action:
                    self.gc.logger.info(f"state change: ch3 {self._last_ch3_action.value} -> {ch3_action.value}")
                    self._last_ch3_action = ch3_action

                ACTUALLY_RUN = self.gc.rotary_channel_steppers_can_operate_in_parallel or (
                    not self.shared.chute_move_in_progress
                )

                if not ACTUALLY_RUN:
                    self.gc.logger.info("Feeder: skipping rotor pulse while chute move in progress")
                    continue

                # channel 3
                if ch3_action == ChannelAction.PULSE_PRECISE:
                    prof.hit("feeder.path.ch3_precise")
                    self.gc.logger.info("Feeder: ch3 precise, pulsing 3rd (precise)")
                    cfg = fc.third_rotor_precision
                    pulse_degrees = self.irl.third_c_channel_rotor_stepper.degrees_for_microsteps(
                        cfg.steps_per_pulse
                    )
                    self.irl.third_c_channel_rotor_stepper.move_degrees(pulse_degrees)
                    if cfg.delay_between_pulse_ms > 0:
                        time.sleep(cfg.delay_between_pulse_ms / 1000.0)
                elif ch3_action == ChannelAction.PULSE_NORMAL:
                    prof.hit("feeder.path.ch3_normal")
                    self.gc.logger.info("Feeder: ch3 normal, pulsing 3rd")
                    cfg = fc.third_rotor_normal
                    pulse_degrees = self.irl.third_c_channel_rotor_stepper.degrees_for_microsteps(
                        cfg.steps_per_pulse
                    )
                    self.irl.third_c_channel_rotor_stepper.move_degrees(pulse_degrees)
                    if cfg.delay_between_pulse_ms > 0:
                        time.sleep(cfg.delay_between_pulse_ms / 1000.0)

                # channel 2 — only pulse if ch3 dropzone is clear
                if not analysis.ch3_dropzone_occupied:
                    if ch2_action == ChannelAction.PULSE_PRECISE:
                        prof.hit("feeder.path.ch2_precise")
                        self.gc.logger.info("Feeder: ch2 precise, pulsing 2nd (precise)")
                        cfg = fc.second_rotor_precision
                        pulse_degrees = self.irl.second_c_channel_rotor_stepper.degrees_for_microsteps(
                            cfg.steps_per_pulse
                        )
                        self.irl.second_c_channel_rotor_stepper.move_degrees(pulse_degrees)
                        if cfg.delay_between_pulse_ms > 0:
                            time.sleep(cfg.delay_between_pulse_ms / 1000.0)
                    elif ch2_action == ChannelAction.PULSE_NORMAL:
                        prof.hit("feeder.path.ch2_normal")
                        self.gc.logger.info("Feeder: ch2 normal, pulsing 2nd")
                        cfg = fc.second_rotor_normal
                        pulse_degrees = self.irl.second_c_channel_rotor_stepper.degrees_for_microsteps(
                            cfg.steps_per_pulse
                        )
                        self.irl.second_c_channel_rotor_stepper.move_degrees(pulse_degrees)
                        if cfg.delay_between_pulse_ms > 0:
                            time.sleep(cfg.delay_between_pulse_ms / 1000.0)

                # channel 1 — only pulse if ch2 dropzone is clear
                if not analysis.ch2_dropzone_occupied:
                    prof.hit("feeder.path.ch1")
                    self.gc.logger.info("Feeder: clear, pulsing 1st")
                    cfg = fc.first_rotor
                    pulse_degrees = self.irl.first_c_channel_rotor_stepper.degrees_for_microsteps(
                        cfg.steps_per_pulse
                    )
                    self.irl.first_c_channel_rotor_stepper.move_degrees(pulse_degrees)
                    if cfg.delay_between_pulse_ms > 0:
                        time.sleep(cfg.delay_between_pulse_ms / 1000.0)

    def cleanup(self) -> None:
        super().cleanup()
