import time
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .analysis import ChannelAction, FeederAnalysis, analyzeFeederChannels
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig, RotorPulseConfig
from vision import VisionManager

DROPOFF_PAUSE_MS = 1000
TIMEOUT_BEFORE_BACKSPIN_MS = 30000
BACKSPIN_STEPS = 500


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
        self._was_in_3_precise = False
        self._ch3_pause_until: float = 0
        self._ch2_state_since: float = 0
        self._ch3_state_since: float = 0
        self._ch2_backspun = False
        self._ch3_backspun = False
        # per-stepper busy-until timestamps (time.time() when we expect the move to finish)
        self._busy_until: dict[str, float] = {}

    def _isStepperBusy(self, stepper) -> bool:
        return time.time() < self._busy_until.get(stepper.name, 0)

    def _markStepperBusy(self, stepper, wait_ms: float) -> None:
        self._busy_until[stepper.name] = time.time() + wait_ms / 1000.0

    def _sendBackspin(self, stepper, cfg: RotorPulseConfig) -> bool:
        if self._isStepperBusy(stepper):
            return False
        self.gc.logger.info(f"feeder backspin: sending {BACKSPIN_STEPS} steps to {stepper.name}")
        stepper.moveSteps(
            BACKSPIN_STEPS,
            cfg.delay_us,
            cfg.accel_start_delay_us,
            cfg.accel_steps,
            cfg.decel_steps,
        )
        exec_ms = stepper.estimateMoveStepsMs(
            BACKSPIN_STEPS,
            cfg.delay_us,
            cfg.accel_start_delay_us,
            cfg.accel_steps,
            cfg.decel_steps,
        )
        self._markStepperBusy(stepper, max(exec_ms, cfg.delay_between_pulse_ms))
        return True

    def _sendPulse(self, stepper, cfg: RotorPulseConfig) -> bool:
        if self._isStepperBusy(stepper):
            return False
        self.gc.logger.info(
            f"feeder pulse: sending {cfg.steps_per_pulse} steps to {stepper.name}"
        )
        stepper.moveSteps(
            -cfg.steps_per_pulse,
            cfg.delay_us,
            cfg.accel_start_delay_us,
            cfg.accel_steps,
            cfg.decel_steps,
        )
        exec_ms = stepper.estimateMoveStepsMs(
            -cfg.steps_per_pulse,
            cfg.delay_us,
            cfg.accel_start_delay_us,
            cfg.accel_steps,
            cfg.decel_steps,
        )
        self._markStepperBusy(stepper, max(exec_ms, cfg.delay_between_pulse_ms))
        return True

    def step(self) -> Optional[FeederState]:
        self._ensureExecutionThreadStarted()
        return None

    def _executionLoop(self) -> None:
        fc = self.gc.feeder_config
        prof = self.gc.profiler

        while not self._stop_event.is_set():
            prof.hit("feeder.execution_loop.calls")
            prof.mark("feeder.execution_loop.interval_ms")

            with prof.timer("feeder.execution_loop.total_ms"):
                with prof.timer("feeder.get_feeder_detections_ms"):
                    object_detections = self.vision.getFeederHeatmapDetections()
                prof.observeValue(
                    "feeder.object_detection_count", float(len(object_detections))
                )

                with prof.timer("feeder.analyze_state_ms"):
                    analysis = analyzeFeederChannels(self.gc, object_detections)
                ch2_action = analysis.ch2_action
                ch3_action = analysis.ch3_action

                now = time.time()
                if ch2_action != self._last_ch2_action:
                    self.gc.logger.info(f"state change: ch2 {self._last_ch2_action.value} -> {ch2_action.value}")
                    self._last_ch2_action = ch2_action
                    self._ch2_state_since = now
                    self._ch2_backspun = False
                if ch3_action != self._last_ch3_action:
                    self.gc.logger.info(f"state change: ch3 {self._last_ch3_action.value} -> {ch3_action.value}")
                    self._last_ch3_action = ch3_action
                    self._ch3_state_since = now
                    self._ch3_backspun = False

                can_run = self.gc.rotary_channel_steppers_can_operate_in_parallel or (
                    not self.shared.chute_move_in_progress
                )
                if not can_run:
                    self.gc.logger.info("Feeder: skipping, chute move in progress")
                    continue

                # ch3 dropoff pause: freeze ch3 briefly after piece leaves precise zone
                if ch3_action == ChannelAction.PULSE_PRECISE:
                    self._was_in_3_precise = True
                elif self._was_in_3_precise:
                    self._was_in_3_precise = False
                    self._ch3_pause_until = time.time() + DROPOFF_PAUSE_MS / 1000.0
                    self.gc.logger.info(
                        f"Feeder: piece left ch3 precise zone, pausing ch3 {DROPOFF_PAUSE_MS}ms"
                    )

                ch3_paused = time.time() < self._ch3_pause_until

                # channel 3 — only pulse if classification platform is ready and not paused
                ch3_stuck = (
                    ch3_action != ChannelAction.IDLE
                    and not self._ch3_backspun
                    and self._ch3_state_since > 0
                    and (now - self._ch3_state_since) * 1000 > TIMEOUT_BEFORE_BACKSPIN_MS
                )
                if not self.shared.classification_ready or ch3_paused:
                    pass
                elif ch3_stuck:
                    self.gc.logger.info(f"Feeder: ch3 stuck in {ch3_action.value}, backspinning")
                    self._ch3_backspun = True
                    cfg = fc.third_rotor_precision if ch3_action == ChannelAction.PULSE_PRECISE else fc.third_rotor_normal
                    self._sendBackspin(self.irl.third_c_channel_rotor_stepper, cfg)
                elif ch3_action == ChannelAction.PULSE_PRECISE:
                    prof.hit("feeder.path.ch3_precise")
                    self._sendPulse(self.irl.third_c_channel_rotor_stepper, fc.third_rotor_precision)
                elif ch3_action == ChannelAction.PULSE_NORMAL:
                    prof.hit("feeder.path.ch3_normal")
                    self._sendPulse(self.irl.third_c_channel_rotor_stepper, fc.third_rotor_normal)

                # channel 2 — only pulse if ch3 dropzone is clear
                ch2_stuck = (
                    ch2_action != ChannelAction.IDLE
                    and not self._ch2_backspun
                    and self._ch2_state_since > 0
                    and (now - self._ch2_state_since) * 1000 > TIMEOUT_BEFORE_BACKSPIN_MS
                )
                if ch2_stuck:
                    self.gc.logger.info(f"Feeder: ch2 stuck in {ch2_action.value}, backspinning")
                    self._ch2_backspun = True
                    cfg = fc.second_rotor_precision if ch2_action == ChannelAction.PULSE_PRECISE else fc.second_rotor_normal
                    self._sendBackspin(self.irl.second_c_channel_rotor_stepper, cfg)
                elif not analysis.ch3_dropzone_occupied:
                    if ch2_action == ChannelAction.PULSE_PRECISE:
                        prof.hit("feeder.path.ch2_precise")
                        self._sendPulse(self.irl.second_c_channel_rotor_stepper, fc.second_rotor_precision)
                    elif ch2_action == ChannelAction.PULSE_NORMAL:
                        prof.hit("feeder.path.ch2_normal")
                        self._sendPulse(self.irl.second_c_channel_rotor_stepper, fc.second_rotor_normal)

                # channel 1 — only pulse if ch2 dropzone is clear
                if not analysis.ch2_dropzone_occupied:
                    prof.hit("feeder.path.ch1")
                    self._sendPulse(self.irl.first_c_channel_rotor_stepper, fc.first_rotor)

        self.gc.logger.info("feeder execution loop: exited, stop_event was set")

    def cleanup(self) -> None:
        super().cleanup()
