import time
from typing import Optional, List
from dataclasses import dataclass
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .analysis import FeederAnalysisState, analyzeFeederState
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager
from defs.consts import FEEDER_OBJECT_CLASS_ID, FEEDER_CAROUSEL_CLASS_ID


@dataclass
class LoopProfile:
    get_masks_ms: float = 0.0
    get_channels_ms: float = 0.0
    analyze_state_ms: float = 0.0
    motor_action_ms: float = 0.0
    total_ms: float = 0.0
    num_object_masks: int = 0
    num_carousel_masks: int = 0
    state_result: str = ""


class LoopProfiler:
    def __init__(self, history_size: int = 10):
        self._history: List[LoopProfile] = []
        self._history_size = history_size
        self._current: Optional[LoopProfile] = None
        self._section_start: float = 0.0
        self._loop_start: float = 0.0

    def startLoop(self) -> None:
        self._current = LoopProfile()
        self._loop_start = time.perf_counter()

    def startSection(self) -> None:
        self._section_start = time.perf_counter()

    def endSection(self, field_name: str) -> None:
        elapsed = (time.perf_counter() - self._section_start) * 1000
        if self._current:
            setattr(self._current, field_name, elapsed)

    def setField(self, field_name: str, value) -> None:
        if self._current:
            setattr(self._current, field_name, value)

    def endLoop(self) -> None:
        if self._current:
            self._current.total_ms = (time.perf_counter() - self._loop_start) * 1000
            self._history.append(self._current)
            if len(self._history) > self._history_size:
                self._history.pop(0)
            self._current = None

    def printReport(self) -> None:
        if not self._history:
            print("[Profiler] No data yet")
            return

        def avg(field: str) -> float:
            return sum(getattr(p, field) for p in self._history) / len(self._history)

        def max_val(field: str) -> float:
            return max(getattr(p, field) for p in self._history)

        latest = self._history[-1]
        print("\n" + "=" * 60)
        print("FEEDER LOOP PROFILING REPORT")
        print("=" * 60)
        print(f"Samples: {len(self._history)}")
        print("-" * 60)
        print(f"{'Section':<30} {'Latest':>10} {'Avg':>10} {'Max':>10}")
        print("-" * 60)
        fields = [
            ("get_masks_ms", "getFeederMasksByClass"),
            ("get_channels_ms", "getIdentifiedChannels"),
            ("analyze_state_ms", "analyzeFeederState"),
            ("motor_action_ms", "motor action"),
            ("total_ms", "TOTAL"),
        ]
        for field_name, label in fields:
            print(
                f"{label:<30} {getattr(latest, field_name):>9.1f}ms {avg(field_name):>9.1f}ms {max_val(field_name):>9.1f}ms"
            )
        print("-" * 60)
        print(
            f"Object masks: {latest.num_object_masks}, Carousel masks: {latest.num_carousel_masks}"
        )
        print(f"State result: {latest.state_result}")
        print("=" * 60 + "\n")


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
        self._profiler = (
            LoopProfiler(history_size=10) if gc.should_profile_feeder else None
        )

    def step(self) -> Optional[FeederState]:
        self._ensureExecutionThreadStarted()

        if not self.shared.classification_ready:
            return FeederState.IDLE
        return None

    def _executionLoop(self) -> None:
        fc = self.gc.feeder_config
        irl_cfg = self.irl_config
        prof = self._profiler

        while not self._stop_event.is_set():
            if prof:
                prof.startLoop()
                prof.startSection()

            masks_by_class = self.vision.getFeederMasksByClass()
            object_detected_masks = masks_by_class.get(FEEDER_OBJECT_CLASS_ID, [])
            carousel_detected_masks = masks_by_class.get(FEEDER_CAROUSEL_CLASS_ID, [])
            carousel_detected_mask = (
                carousel_detected_masks[0] if carousel_detected_masks else None
            )

            if prof:
                prof.endSection("get_masks_ms")
                prof.setField("num_object_masks", len(object_detected_masks))
                prof.setField("num_carousel_masks", len(carousel_detected_masks))
                prof.startSection()

            channels = self.vision.getIdentifiedChannels(
                irl_cfg.first_c_channel_aruco_tag_id,
                irl_cfg.second_c_channel_aruco_tag_id,
                irl_cfg.third_c_channel_aruco_tag_id,
            )

            if prof:
                prof.endSection("get_channels_ms")
                prof.startSection()

            state = analyzeFeederState(
                object_detected_masks, channels, carousel_detected_mask, fc
            )

            if prof:
                prof.endSection("analyze_state_ms")
                prof.setField("state_result", state.value)

            ACTUALLY_RUN = True

            if prof:
                prof.startSection()
            if state == FeederAnalysisState.OBJECT_ABOUT_TO_FALL:
                self.gc.logger.info(
                    "Feeder: object about to fall, pulsing 3rd (precise)"
                )
                cfg = fc.third_rotor_precision
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
            elif state == FeederAnalysisState.OBJECT_IN_3_2_DROPZONE:
                self.gc.logger.info("Feeder: object in 3-2 dropzone, pulsing 3rd")
                cfg = fc.third_rotor_normal
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
            elif state == FeederAnalysisState.OBJECT_IN_2_1_DROPZONE:
                self.gc.logger.info("Feeder: object in 2-1 dropzone, pulsing 2nd")
                cfg = fc.second_rotor
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
                self.gc.logger.info("Feeder: clear, pulsing 1st")
                cfg = fc.first_rotor
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
            if prof:
                prof.endSection("motor_action_ms")
                prof.endLoop()
                prof.printReport()

    def cleanup(self) -> None:
        super().cleanup()
