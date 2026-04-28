from __future__ import annotations

from typing import Any

from rt.contracts.tracking import Track


class C4StartupPurgeController:
    """Own C4 startup-purge arming, mode toggles, and strategy dispatch."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def arm(self) -> None:
        rt = self._rt
        strategy = rt._startup_purge
        if strategy is None or not strategy.enabled:
            rt._startup_purge_state.armed = False
            return
        rt._startup_purge_state.arm()

    @property
    def armed(self) -> bool:
        return bool(self._rt._startup_purge_state.armed)

    def pending(self) -> bool:
        rt = self._rt
        strategy = rt._startup_purge
        return bool(
            strategy is not None
            and strategy.enabled
            and rt._startup_purge_state.armed
        )

    def enter(self) -> None:
        rt = self._rt
        state = rt._startup_purge_state
        fsm_state = type(rt._fsm)
        if not state.mode_active:
            try:
                state.mode_active = bool(rt._startup_purge_mode(True))
            except Exception:
                rt._logger.exception("RuntimeC4: enabling startup purge mode raised")
        rt._fsm = fsm_state.STARTUP_PURGE

    def exit(self) -> None:
        rt = self._rt
        state = rt._startup_purge_state
        fsm_state = type(rt._fsm)
        if state.mode_active:
            try:
                rt._startup_purge_mode(False)
            except Exception:
                rt._logger.exception("RuntimeC4: disabling startup purge mode raised")
            state.mode_active = False
        rt._fsm = fsm_state.RUNNING

    def run(
        self,
        raw_tracks: list[Track],
        owned_tracks: list[Track],
        now_mono: float,
    ) -> bool:
        rt = self._rt
        strategy = rt._startup_purge
        if strategy is None:
            return False
        return strategy.run(
            rt,
            rt._startup_purge_state,
            raw_tracks,
            owned_tracks,
            self.visible_detection_count(raw_tracks),
            now_mono,
        )

    def visible_detection_count(self, raw_tracks: list[Track]) -> int:
        rt = self._rt
        provider = rt._startup_purge_detection_count_provider
        if callable(provider):
            try:
                value = int(provider())
            except Exception:
                rt._logger.exception(
                    "RuntimeC4: startup purge detection-count provider raised"
                )
            else:
                return max(0, value)
        return len(raw_tracks)


__all__ = ["C4StartupPurgeController"]
