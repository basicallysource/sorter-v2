import time
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .analysis import FeederAnalysisState, analyzeFeederState
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager
from defs.consts import FEEDER_OBJECT_CLASS_ID


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
        self.last_analysis_state = None

    def step(self) -> Optional[FeederState]:
        self._ensureExecutionThreadStarted()

        if not self.shared.classification_ready:
            return FeederState.IDLE
        return None

    def _executionLoop(self) -> None:
        fc = self.gc.feeder_config
        irl_cfg = self.irl_config
        prof = self.gc.profiler

        while not self._stop_event.is_set():
            prof.hit("feeder.execution_loop.calls")
            prof.mark("feeder.execution_loop.interval_ms")

            with prof.timer("feeder.execution_loop.total_ms"):
                with prof.timer("feeder.get_feeder_masks_ms"):
                    masks_by_class = self.vision.getFeederMasksByClass()
                object_detected_masks = masks_by_class.get(FEEDER_OBJECT_CLASS_ID, [])
                prof.observeValue(
                    "feeder.object_mask_count", float(len(object_detected_masks))
                )

                with prof.timer("feeder.get_channel_geometry_ms"):
                    geometry = self.vision.getChannelGeometry(irl_cfg.aruco_tags)

                with prof.timer("feeder.analyze_state_ms"):
                    state = analyzeFeederState(object_detected_masks, geometry)

                if state != self.last_analysis_state:
                    self.gc.logger.info(
                        f"state change: feeder_analysis {self.last_analysis_state} -> {state}"
                    )
                    self.last_analysis_state = state
                    prof.hit(f"feeder.analysis_state_change.{state.value}")

                ACTUALLY_RUN = True

                if state == FeederAnalysisState.OBJECT_IN_3_DROPZONE_PRECISE:
                    prof.hit("feeder.path.object_in_3_dropzone_precise")
                    self.gc.logger.info(
                        "Feeder: object in channel 3 quadrant 3, pulsing 3rd (precise)"
                    )
                    cfg = fc.third_rotor_precision
                    with prof.timer("feeder.motor_action_ms"):
                        if ACTUALLY_RUN:
                            self.irl.third_c_channel_rotor_stepper.moveSteps(
                                -cfg.steps_per_pulse,
                                cfg.delay_us,
                                cfg.accel_start_delay_us,
                                cfg.accel_steps,
                                cfg.decel_steps,
                            )
                        if cfg.delay_between_pulse_ms > 0:
                            time.sleep(cfg.delay_between_pulse_ms / 1000.0)
                elif state == FeederAnalysisState.OBJECT_IN_3_DROPZONE:
                    prof.hit("feeder.path.object_in_3_dropzone")
                    self.gc.logger.info(
                        "Feeder: object in channel 3 dropzone, pulsing 3rd"
                    )
                    cfg = fc.third_rotor_normal
                    with prof.timer("feeder.motor_action_ms"):
                        if ACTUALLY_RUN:
                            self.irl.third_c_channel_rotor_stepper.moveSteps(
                                -cfg.steps_per_pulse,
                                cfg.delay_us,
                                cfg.accel_start_delay_us,
                                cfg.accel_steps,
                                cfg.decel_steps,
                            )
                        if cfg.delay_between_pulse_ms > 0:
                            time.sleep(cfg.delay_between_pulse_ms / 1000.0)
                elif state == FeederAnalysisState.OBJECT_IN_2_DROPZONE_PRECISE:
                    prof.hit("feeder.path.object_in_2_dropzone_precise")
                    self.gc.logger.info(
                        "Feeder: object in channel 2 quadrant 3, pulsing 2nd (precise)"
                    )
                    cfg = fc.second_rotor_precision
                    with prof.timer("feeder.motor_action_ms"):
                        if ACTUALLY_RUN:
                            self.irl.second_c_channel_rotor_stepper.moveSteps(
                                -cfg.steps_per_pulse,
                                cfg.delay_us,
                                cfg.accel_start_delay_us,
                                cfg.accel_steps,
                                cfg.decel_steps,
                            )
                        if cfg.delay_between_pulse_ms > 0:
                            time.sleep(cfg.delay_between_pulse_ms / 1000.0)
                elif state == FeederAnalysisState.OBJECT_IN_2_DROPZONE:
                    prof.hit("feeder.path.object_in_2_dropzone")
                    self.gc.logger.info(
                        "Feeder: object in channel 2 dropzone, pulsing 2nd"
                    )
                    cfg = fc.second_rotor_normal
                    with prof.timer("feeder.motor_action_ms"):
                        if ACTUALLY_RUN:
                            self.irl.second_c_channel_rotor_stepper.moveSteps(
                                -cfg.steps_per_pulse,
                                cfg.delay_us,
                                cfg.accel_start_delay_us,
                                cfg.accel_steps,
                                cfg.decel_steps,
                            )
                        if cfg.delay_between_pulse_ms > 0:
                            time.sleep(cfg.delay_between_pulse_ms / 1000.0)
                else:
                    prof.hit("feeder.path.clear")
                    self.gc.logger.info("Feeder: clear, pulsing 1st")
                    cfg = fc.first_rotor
                    with prof.timer("feeder.motor_action_ms"):
                        if ACTUALLY_RUN:
                            self.irl.first_c_channel_rotor_stepper.moveSteps(
                                -cfg.steps_per_pulse,
                                cfg.delay_us,
                                cfg.accel_start_delay_us,
                                cfg.accel_steps,
                                cfg.decel_steps,
                            )
                        if cfg.delay_between_pulse_ms > 0:
                            time.sleep(cfg.delay_between_pulse_ms / 1000.0)

    def cleanup(self) -> None:
        super().cleanup()
