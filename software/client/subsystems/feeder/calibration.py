import time

from global_config import GlobalConfig
from irl.config import IRLInterface, IRLConfig

CALIBRATION_REVERSE_PULSES = 10


def calibrateFeederChannels(gc: GlobalConfig, irl: IRLInterface, irl_config: IRLConfig) -> None:
    gc.logger.info("Calibrating feeder channels (reverse pulse)...")
    fc = irl_config.feeder_config

    ch2_stepper = irl.c_channel_2_rotor_stepper
    ch3_stepper = irl.c_channel_3_rotor_stepper
    ch2_degrees = ch2_stepper.degrees_for_microsteps(fc.second_rotor_normal.steps_per_pulse)
    ch3_degrees = ch3_stepper.degrees_for_microsteps(fc.third_rotor_normal.steps_per_pulse)

    ch2_stepper.set_speed_limits(16, fc.second_rotor_normal.microsteps_per_second // 2)
    ch3_stepper.set_speed_limits(16, fc.third_rotor_normal.microsteps_per_second // 2)

    for i in range(CALIBRATION_REVERSE_PULSES):
        ch2_stepper.move_degrees(-ch2_degrees)
        ch3_stepper.move_degrees(-ch3_degrees)
        time.sleep(fc.second_rotor_normal.delay_between_pulse_ms / 1000.0)
        gc.logger.info(f"  reverse pulse {i + 1}/{CALIBRATION_REVERSE_PULSES}")

    ch2_stepper.set_speed_limits(16, fc.second_rotor_normal.microsteps_per_second)
    ch3_stepper.set_speed_limits(16, fc.third_rotor_normal.microsteps_per_second)
    gc.logger.info("Feeder calibration done")
