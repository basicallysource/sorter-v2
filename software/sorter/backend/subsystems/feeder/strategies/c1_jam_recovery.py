from __future__ import annotations

import time


class C1JamRecoveryStrategy:
    def __init__(
        self,
        *,
        stepper,
        logger,
        profiler,
        runtime_stats,
        feeder_config,
        busy_until: dict[str, float],
        gear_ratio: float,
        push_output_degrees: tuple[float, ...],
    ) -> None:
        self._stepper = stepper
        self._logger = logger
        self._profiler = profiler
        self._runtime_stats = runtime_stats
        self._feeder_config = feeder_config
        self._busy_until = busy_until
        self._gear_ratio = float(gear_ratio)
        self._push_output_degrees = tuple(push_output_degrees)
        self._cooldown_until: float = 0.0
        self._level: int = 0
        self._attempts: int = 0
        self._phase: str = "shake"
        self._last_level_used: int = 0
        self._last_phase_used: str = "shake"

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def cooldown_until(self) -> float:
        return self._cooldown_until

    @property
    def state_name(self) -> str:
        return f"{self._last_phase_used}_l{self._last_level_used + 1}"

    def reset(self) -> None:
        self._level = 0
        self._attempts = 0
        self._phase = "shake"
        self._cooldown_until = 0.0

    def is_ready(self, now_mono: float) -> bool:
        return float(now_mono) >= self._cooldown_until

    def exhausted(self, max_levels: int) -> bool:
        return self._attempts >= max(1, int(max_levels))

    def run(self, cfg, now_mono: float) -> bool:
        if self._phase == "push":
            return self._run_push(cfg, now_mono)
        return self._run_shake(cfg, now_mono)

    def _is_stepper_busy(self) -> bool:
        return time.monotonic() < self._busy_until.get(self._stepper._name, 0.0)

    def _recovery_degrees(self) -> float:
        base_output_degrees = float(
            self._feeder_config.first_rotor_jam_backtrack_output_degrees
        )
        max_output_degrees = float(
            self._feeder_config.first_rotor_jam_max_output_degrees
        )
        output_degrees = min(max_output_degrees, base_output_degrees + self._level * 6.0)
        return max(15.0, min(30.0, output_degrees))

    def _recovery_cycles(self) -> int:
        max_cycles = max(1, int(self._feeder_config.first_rotor_jam_max_cycles))
        return max(1, min(max_cycles, 1 + self._level))

    def _recovery_push_degrees(self) -> float:
        if not self._push_output_degrees:
            return 0.0
        idx = max(0, min(self._level, len(self._push_output_degrees) - 1))
        return float(self._push_output_degrees[idx])

    def _settle_after_recovery(self, cfg) -> None:
        now_after = time.monotonic()
        self._busy_until[self._stepper._name] = max(
            self._busy_until.get(self._stepper._name, 0.0),
            now_after + max(0.25, cfg.delay_between_pulse_ms / 1000.0),
        )
        self._cooldown_until = (
            now_after + self._feeder_config.first_rotor_jam_retry_cooldown_s
        )

    def _recovery_level(self) -> int:
        max_cycles = max(1, int(self._feeder_config.first_rotor_jam_max_cycles))
        return min(self._level, max(0, max_cycles - 1))

    def _run_shake(self, cfg, now_mono: float) -> bool:
        if self._is_stepper_busy():
            return False

        recovery_level = self._recovery_level()
        self._last_level_used = recovery_level
        self._last_phase_used = "shake"
        recovery_degrees = self._recovery_degrees()
        recovery_cycles = self._recovery_cycles()
        recovery_label = f"ch1_jam_recovery_shake_l{recovery_level + 1}"
        self._logger.warning(
            "Feeder: bulk bucket appears stuck before C-Channel 2; "
            f"running ch1 jam recovery shake level {recovery_level + 1} "
            f"({recovery_cycles}x {recovery_degrees:.1f}° back/forward)"
        )

        self._profiler.hit("feeder.path.ch1_jam_recovery_shake")
        self._runtime_stats.observePulse(recovery_label, "sent", now_mono)

        motor_recovery_degrees = recovery_degrees * self._gear_ratio
        move_timeout_ms = max(2500, int(recovery_degrees * 90))
        reverse_ok = True
        forward_ok = True
        for cycle_index in range(recovery_cycles):
            reverse_ok = self._stepper.move_degrees_blocking(
                -motor_recovery_degrees,
                timeout_ms=move_timeout_ms,
            )
            if not reverse_ok:
                self._profiler.hit("feeder.jam_recovery.reverse_failed")
                self._logger.warning(
                    f"Feeder: ch1 jam recovery reverse move failed on cycle {cycle_index + 1}/{recovery_cycles}"
                )
                break

            forward_ok = self._stepper.move_degrees_blocking(
                motor_recovery_degrees,
                timeout_ms=move_timeout_ms,
            )
            if not forward_ok:
                self._profiler.hit("feeder.jam_recovery.forward_failed")
                self._logger.warning(
                    f"Feeder: ch1 jam recovery forward move failed on cycle {cycle_index + 1}/{recovery_cycles}"
                )
                break

        if reverse_ok and forward_ok:
            self._logger.info(
                f"Feeder: ch1 jam recovery shake level {recovery_level + 1} completed"
            )

        self._settle_after_recovery(cfg)
        self._phase = "push"
        return reverse_ok and forward_ok

    def _run_push(self, cfg, now_mono: float) -> bool:
        if self._is_stepper_busy():
            return False

        max_cycles = max(1, int(self._feeder_config.first_rotor_jam_max_cycles))
        recovery_level = self._recovery_level()
        self._last_level_used = recovery_level
        self._last_phase_used = "push"
        push_degrees = self._recovery_push_degrees()
        recovery_label = f"ch1_jam_recovery_push_l{recovery_level + 1}"
        self._logger.warning(
            "Feeder: shake didn't free a piece; pushing bulk rotor forward "
            f"at recovery level {recovery_level + 1} ({push_degrees:.0f}° output)"
        )
        self._profiler.hit("feeder.path.ch1_jam_recovery_push")
        self._runtime_stats.observePulse(recovery_label, "sent", now_mono)

        motor_push_degrees = push_degrees * self._gear_ratio
        move_timeout_ms = max(2500, int(push_degrees * 90))
        push_ok = True
        if push_degrees > 0.0:
            push_ok = self._stepper.move_degrees_blocking(
                motor_push_degrees,
                timeout_ms=move_timeout_ms,
            )
            if not push_ok:
                self._profiler.hit("feeder.jam_recovery.push_failed")
                self._logger.warning(
                    f"Feeder: ch1 jam recovery forward push failed at level {recovery_level + 1}"
                )
            else:
                self._logger.info(
                    f"Feeder: ch1 jam recovery push level {recovery_level + 1} completed"
                )

        self._settle_after_recovery(cfg)
        self._attempts += 1
        self._level = min(
            self._level + 1,
            max(0, max_cycles - 1),
        )
        self._phase = "shake"
        return push_ok


__all__ = ["C1JamRecoveryStrategy"]
