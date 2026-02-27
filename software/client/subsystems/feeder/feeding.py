import time
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .analysis import ChannelAction, analyzeFeederChannels
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig, RotorPulseConfig
from vision import VisionManager

DROPOFF_PAUSE_MS = 500
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
        self._pause_until: float = 0
        # backspin tracking: per-channel (ch2, ch3) state entry time and whether we've already backspun
        self._ch2_state_since: float = 0
        self._ch3_state_since: float = 0
        self._ch2_backspun = False
        self._ch3_backspun = False

    def _backspin(self, stepper, cfg: RotorPulseConfig) -> None:
        mcu = stepper.mcu
        if mcu.outstanding_t_count > 0:
            mcu.outstanding_t_drained.wait()
            return
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
        time.sleep(max(exec_ms, cfg.delay_between_pulse_ms) / 1000.0)

    def _pulseAndWait(self, stepper, cfg: RotorPulseConfig) -> None:
        mcu = stepper.mcu
        if mcu.outstanding_t_count > 0:
            self.gc.logger.info(
                f"feeder _pulseAndWait: skipping, {mcu.outstanding_t_count} commands still outstanding"
            )
            # wait for the outstanding commands to drain before trying again
            mcu.outstanding_t_drained.wait()
            return

        self.gc.logger.info(
            f"feeder _pulseAndWait: sending {cfg.steps_per_pulse} steps to {stepper.name}"
        )
        stepper.moveSteps(
            -cfg.steps_per_pulse,
            cfg.delay_us,
            cfg.accel_start_delay_us,
            cfg.accel_steps,
            cfg.decel_steps,
        )
        # wait at least the estimated execution time so we don't flood the MCU
        exec_ms = stepper.estimateMoveStepsMs(
            -cfg.steps_per_pulse,
            cfg.delay_us,
            cfg.accel_start_delay_us,
            cfg.accel_steps,
            cfg.decel_steps,
        )
        wait_ms = max(exec_ms, cfg.delay_between_pulse_ms)
        self.gc.logger.info(
            f"feeder _pulseAndWait: sleeping {wait_ms}ms (exec_ms={exec_ms}, delay_between={cfg.delay_between_pulse_ms})"
        )
        time.sleep(wait_ms / 1000.0)
        self.gc.logger.info("feeder _pulseAndWait: sleep done")

    def step(self) -> Optional[FeederState]:
        self._ensureExecutionThreadStarted()

        if not self.shared.classification_ready:
            self.gc.logger.info("Feeding.step: classification_ready=False, transitioning to IDLE")
            return FeederState.IDLE
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
                    ch2_action, ch3_action = analyzeFeederChannels(self.gc, object_detections)

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

                # ch3 dropoff pause tracking
                if ch3_action == ChannelAction.PULSE_PRECISE:
                    self._was_in_3_precise = True
                elif self._was_in_3_precise:
                    self._was_in_3_precise = False
                    self._pause_until = time.time() + DROPOFF_PAUSE_MS / 1000.0
                    self.gc.logger.info(
                        f"Feeder: piece left ch3 precise zone, pausing ch3 {DROPOFF_PAUSE_MS}ms"
                    )

                ch3_paused = (self._pause_until - time.time()) > 0

                # channel 3
                ch3_stuck = (
                    ch3_action != ChannelAction.IDLE
                    and not self._ch3_backspun
                    and self._ch3_state_since > 0
                    and (now - self._ch3_state_since) * 1000 > TIMEOUT_BEFORE_BACKSPIN_MS
                )
                if ch3_stuck:
                    self.gc.logger.info(f"Feeder: ch3 stuck in {ch3_action.value}, backspinning")
                    self._ch3_backspun = True
                    cfg = fc.third_rotor_precision if ch3_action == ChannelAction.PULSE_PRECISE else fc.third_rotor_normal
                    self._backspin(self.irl.third_c_channel_rotor_stepper, cfg)
                elif ch3_paused:
                    remaining_ms = (self._pause_until - time.time()) * 1000
                    self.gc.logger.info(f"Feeder: ch3 paused ({remaining_ms:.0f}ms remaining)")
                elif ch3_action == ChannelAction.PULSE_PRECISE:
                    prof.hit("feeder.path.ch3_precise")
                    self._pulseAndWait(self.irl.third_c_channel_rotor_stepper, fc.third_rotor_precision)
                elif ch3_action == ChannelAction.PULSE_NORMAL:
                    prof.hit("feeder.path.ch3_normal")
                    self._pulseAndWait(self.irl.third_c_channel_rotor_stepper, fc.third_rotor_normal)

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
                    self._backspin(self.irl.second_c_channel_rotor_stepper, cfg)
                elif ch3_action == ChannelAction.IDLE:
                    if ch2_action == ChannelAction.PULSE_PRECISE:
                        prof.hit("feeder.path.ch2_precise")
                        self._pulseAndWait(self.irl.second_c_channel_rotor_stepper, fc.second_rotor_precision)
                    elif ch2_action == ChannelAction.PULSE_NORMAL:
                        prof.hit("feeder.path.ch2_normal")
                        self._pulseAndWait(self.irl.second_c_channel_rotor_stepper, fc.second_rotor_normal)

                # channel 1 — only pulse if ch2 dropzone is clear
                if ch2_action == ChannelAction.IDLE:
                    prof.hit("feeder.path.ch1")
                    self._pulseAndWait(self.irl.first_c_channel_rotor_stepper, fc.first_rotor)

        self.gc.logger.info("feeder execution loop: exited, stop_event was set")

    def cleanup(self) -> None:
        super().cleanup()
