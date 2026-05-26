from __future__ import annotations

import inspect
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from subsystems.classification.carousel import Carousel
    from piece_transport import PieceTransport
    from global_config import GlobalConfig
    from subsystems.bus import TickBus

from subsystems.bus import (
    ChuteMotion,
    PieceDelivered,
    PieceRequest,
    StationGate,
    StationId,
)


class SharedVariables:
    def __init__(
        self,
        gc: "GlobalConfig" | None = None,
        bus: "TickBus" | None = None,
    ):
        self._gc = gc
        self._bus = bus
        self._classification_ready: bool = False
        self._distribution_ready: bool = True
        self.transport: Optional["PieceTransport"] = None
        self.carousel: Optional["Carousel"] = None
        self._chute_move_in_progress: bool = False
        # Sample-collection maintenance mode. When True, the feeder ignores
        # downstream gates (ch3_held / classification_channel_block) so C2/C3
        # keep advancing pieces past the cameras regardless of whether the
        # classification channel is ready. Use during training-sample drives
        # so the pipeline doesn't stall on ghost detections in C4. Toggled
        # via the /api/sample-collection-mode endpoint.
        self._sample_collection_mode: bool = False
        self._ignored_classification_dropzone_track_ids: set[int] = set()

    @property
    def classification_ready(self) -> bool:
        return self.get_classification_ready()

    @classification_ready.setter
    def classification_ready(self, value: bool) -> None:
        self.set_classification_gate(
            bool(value),
            reason=None if value else "compat_flag_false",
        )

    @property
    def distribution_ready(self) -> bool:
        return self.get_distribution_ready()

    @distribution_ready.setter
    def distribution_ready(self, value: bool) -> None:
        self.set_distribution_gate(
            bool(value),
            reason=None if value else "compat_flag_false",
        )

    @property
    def chute_move_in_progress(self) -> bool:
        return self.get_chute_move_in_progress()

    @chute_move_in_progress.setter
    def chute_move_in_progress(self, value: bool) -> None:
        self.set_chute_motion(bool(value), target_bin=None)

    @property
    def sample_collection_mode(self) -> bool:
        return self._sample_collection_mode

    @sample_collection_mode.setter
    def sample_collection_mode(self, value: bool) -> None:
        self._sample_collection_mode = bool(value)

    def set_classification_gate(
        self,
        open: bool,
        *,
        reason: str | None = None,
    ) -> None:
        next_value = bool(open)
        prev_value = self._classification_ready
        # DEV-LOG: remove before merge
        self._log_gate_write("classification", prev_value, next_value, reason)
        if prev_value == next_value and not self._bus_enabled():
            return
        self._classification_ready = next_value
        self._publish_station_gate(
            StationId.CLASSIFICATION,
            open=next_value,
            reason=reason,
        )

    def set_distribution_gate(
        self,
        open: bool,
        *,
        reason: str | None = None,
    ) -> None:
        next_value = bool(open)
        if self._distribution_ready == next_value and not self._bus_enabled():
            return
        self._distribution_ready = next_value
        self._publish_station_gate(
            StationId.DISTRIBUTION,
            open=next_value,
            reason=reason,
        )

    def set_chute_motion(
        self,
        in_progress: bool,
        *,
        target_bin: object | None,
    ) -> None:
        next_value = bool(in_progress)
        if self._chute_move_in_progress == next_value and not self._bus_enabled():
            return
        self._chute_move_in_progress = next_value
        if not self._bus_enabled():
            return
        self._bus.publish(
            ChuteMotion(
                in_progress=next_value,
                target_bin=target_bin,
                updated_at_mono=time.monotonic(),
            )
        )

    def publish_piece_request(
        self,
        *,
        source: StationId,
        target: StationId,
        sent_at_mono: float | None = None,
    ) -> None:
        if not self._bus_enabled():
            return
        self._bus.publish(
            PieceRequest(
                source=source,
                target=target,
                sent_at_mono=time.monotonic() if sent_at_mono is None else float(sent_at_mono),
            )
        )

    def publish_piece_delivered(
        self,
        *,
        source: StationId,
        target: StationId,
        delivered_at_mono: float | None = None,
    ) -> None:
        if not self._bus_enabled():
            return
        self._bus.publish(
            PieceDelivered(
                source=source,
                target=target,
                delivered_at_mono=time.monotonic() if delivered_at_mono is None else float(delivered_at_mono),
            )
        )

    def has_pending_piece_request(
        self,
        *,
        source: StationId,
        target: StationId,
        now_mono: float | None = None,
        timeout_s: float | None = None,
    ) -> bool:
        if not self._bus_enabled() or self._bus is None:
            return False
        if not hasattr(self._bus, "has_pending_piece_request"):
            return False
        return bool(
            self._bus.has_pending_piece_request(
                source=source,
                target=target,
                now_mono=now_mono,
                timeout_s=timeout_s,
            )
        )

    def get_classification_ready(self) -> bool:
        if self._bus_enabled() and self._bus is not None:
            gate = self._bus.station_gate(StationId.CLASSIFICATION)
            if gate is not None:
                return bool(gate.open)
        return self._classification_ready

    def get_distribution_ready(self) -> bool:
        if self._bus_enabled() and self._bus is not None:
            gate = self._bus.station_gate(StationId.DISTRIBUTION)
            if gate is not None:
                return bool(gate.open)
        return self._distribution_ready

    def get_chute_move_in_progress(self) -> bool:
        if self._bus_enabled() and self._bus is not None:
            motion = self._bus.chute_motion()
            if motion is not None:
                return bool(motion.in_progress)
        return self._chute_move_in_progress

    def set_classification_dropzone_track_ignored(
        self,
        global_id: int,
        ignored: bool,
    ) -> None:
        track_id = int(global_id)
        if ignored:
            self._ignored_classification_dropzone_track_ids.add(track_id)
        else:
            self._ignored_classification_dropzone_track_ids.discard(track_id)

    def ignored_classification_dropzone_track_ids(self) -> set[int]:
        return set(self._ignored_classification_dropzone_track_ids)

    def is_classification_dropzone_track_ignored(self, global_id: int) -> bool:
        return int(global_id) in self._ignored_classification_dropzone_track_ids

    # DEV-LOG: remove before merge — instruments every gate write (incl. no-ops)
    # with caller frame, used to track down rev01 gate regression. Drop along
    # with the call in set_classification_gate.
    def _log_gate_write(
        self,
        gate: str,
        prev: bool,
        next_value: bool,
        reason: str | None,
    ) -> None:
        logger = getattr(self._gc, "logger", None) if self._gc is not None else None
        if logger is None:
            return
        frame = inspect.stack()[2] if len(inspect.stack()) > 2 else None
        caller = f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}" if frame else "?"
        changed = "CHANGE" if prev != next_value else "noop"
        logger.info(
            f"[GATE] {gate} {prev}->{next_value} {changed} reason={reason} from={caller}"
        )

    def _publish_station_gate(
        self,
        station: StationId,
        *,
        open: bool,
        reason: str | None,
    ) -> None:
        if not self._bus_enabled():
            return
        self._bus.publish(
            StationGate(
                station=station,
                open=open,
                reason=reason,
                updated_at_mono=time.monotonic(),
            )
        )

    def _bus_enabled(self) -> bool:
        return bool(
            self._gc is not None
            and getattr(self._gc, "use_channel_bus", False)
            and self._bus is not None
        )
