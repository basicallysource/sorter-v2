import time
import queue
from typing import Optional
import server.shared_state as shared_state
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from .chute import Chute, BinAddress
from irl.bin_layout import DistributionLayout, Bin, extractCategories
from irl.config import IRLInterface
from global_config import GlobalConfig
from sorting_profile import SortingProfile, MISC_CATEGORY
from blob_manager import setBinCategories
from defs.events import PauseCommandData, PauseCommandEvent
from defs.known_object import PieceStage
from utils.event import knownObjectToEvent


BINS_FULL_ALERT_PREFIX = "No bin available"
MISC_PASSTHROUGH_ALERT_PREFIX = "Misc passthrough"
CHUTE_JAM_ALERT_PREFIX = "Chute jam"
SERVO_BUS_ALERT_PREFIX = "Servo bus offline"
# Beyond how many ms after the estimated move time do we conclude the
# chute / servo is stuck? 3× the expected move is generous but catches
# a real jam reliably.
CHUTE_MOVE_TIMEOUT_MS = 6000
CHUTE_MOVE_TIMEOUT_MULTIPLIER = 3.0

class Positioning(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        chute: Chute,
        layout: DistributionLayout,
        sorting_profile: SortingProfile,
        event_queue: queue.Queue,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.chute = chute
        self.layout = layout
        self.sorting_profile = sorting_profile
        self.event_queue = event_queue
        self._phase: str = "init"
        self._target_address: BinAddress | None = None
        self._door_servo_index: int | None = None
        self._state_entered_at: float = 0.0
        self._moving_started_at: float = 0.0
        self._piece = None
        self._occupancy_state: str | None = None
        self._blocked_layers: set[int] = set()
        self._servo_offline_layers: set[int] = set()
        self._jam_pause_enqueued: bool = False
        self._servo_bus_pause_enqueued: bool = False
        self._chute_move_estimated_ms: int = 0

    def _setOccupancyState(self, state_name: str) -> None:
        if self._occupancy_state == state_name:
            return
        prev_state = self._occupancy_state
        self._occupancy_state = state_name
        self.gc.runtime_stats.observeStateTransition(
            "distribution.occupancy",
            prev_state,
            state_name,
        )

    def step(self) -> Optional[DistributionState]:
        now = time.monotonic()

        if self._phase == "init":
            # Fresh evaluation per piece — an earlier transient servo
            # glitch must not permanently disable a layer.
            self._blocked_layers.clear()
            self._servo_offline_layers.clear()
            self._setOccupancyState("positioning.select_target_bin")
            self._state_entered_at = now
            transport = self.shared.transport
            piece = (
                transport.getPieceForDistributionPositioning()
                if transport is not None
                else None
            )
            if piece is None:
                self.logger.warn("Positioning: no piece ready for distribution")
                self._setOccupancyState("positioning.wait_piece_for_distribution")
                return DistributionState.IDLE

            if piece.part_id is not None:
                category_id = self.sorting_profile.getCategoryIdForPart(piece.part_id, piece.color_id)
            else:
                category_id = MISC_CATEGORY
            address, _ = self._findOrAssignBinForCategory(category_id)
            if address is None and self._servo_bus_pause_enqueued:
                # Fatal: the servo bus is offline, so every layer is
                # unusable. ``_findOrAssignBinForCategory`` already set
                # the red banner and enqueued a pause — do NOT fall
                # through to the passthrough path, which would silently
                # send this piece to the discard bucket.
                return DistributionState.IDLE
            if address is None:
                # Pass-through: no bin available for this category. Open
                # every usable layer door so the piece falls straight
                # through to the bottom tray. Still move the chute back
                # to a known passthrough angle first; otherwise an
                # unknown / discard piece inherits the previous bin's
                # chute alignment and can hang half out of the exit.
                self.logger.warning(
                    f"Positioning: no bin for category {category_id} — passthrough to bottom"
                )
                self._raiseBinsFullAlert(category_id)
                self._openAllDoorsForPassthrough()
                piece.stage = PieceStage.distributing
                piece.distributing_at = time.time()
                piece.distribution_target_selected_at = piece.distributing_at
                piece.category_id = category_id
                piece.destination_bin = None
                piece.updated_at = time.time()
                self._piece = piece
                self.event_queue.put(knownObjectToEvent(piece))
                self._setOccupancyState("positioning.passthrough_no_bin")
                self._door_servo_index = None
                self._moving_started_at = now
                self._startChuteMove()
                return None

            self._clearBinsFullAlertIfOwned()
            self._clearChuteJamAlertIfOwned()
            self.logger.info(
                f"Positioning: moving to bin at layer={address.layer_index}, section={address.section_index}, bin={address.bin_index}"
            )
            if not self._selectDoor(address.layer_index):
                self.logger.warning(
                    f"Positioning: layer {address.layer_index} is unavailable for distribution, retrying with remaining layers"
                )
                # If every layer is now blocked AND the root cause is that
                # every configured servo is offline, this is the fatal
                # servo-bus case: the controller can no longer dispense
                # anything. Pause + red banner. Fall back to the generic
                # chute-jam alert only if blocks came from other causes
                # (e.g. transient close-timeouts on a live bus).
                usable_count = sum(
                    1
                    for li, layer in enumerate(self.layout.layers)
                    if getattr(layer, "enabled", True) and li not in self._blocked_layers
                )
                if usable_count == 0:
                    if self._allEnabledLayersServoOffline():
                        self._raiseServoBusOfflineAlert(
                            "no layer servo responded during door selection"
                        )
                    else:
                        self._raiseChuteJamAlert(
                            "all layer servos are offline"
                        )
                return DistributionState.IDLE

            piece.stage = PieceStage.distributing
            piece.distributing_at = time.time()
            piece.distribution_target_selected_at = piece.distributing_at
            piece.category_id = category_id
            piece.destination_bin = (
                address.layer_index,
                address.section_index,
                address.bin_index,
            )
            piece.updated_at = time.time()
            self._piece = piece
            self.event_queue.put(knownObjectToEvent(piece))

            if not self.gc.disable_servos:
                self._door_servo_index = address.layer_index
            self._target_address = address
            self._startChuteMove()
            self._moving_started_at = now
            init_ms = (now - self._state_entered_at) * 1000
            if self.gc.disable_servos:
                self.logger.info(f"Positioning: init phase took {init_ms:.0f}ms, now waiting for chute")
            else:
                self.logger.info(f"Positioning: init phase took {init_ms:.0f}ms, now waiting for servo+chute")
            return None

        if self._phase == "moving":
            self._setOccupancyState("positioning.wait_servo_and_chute_motion")
            chute_stopped = self.chute.stepper.stopped
            servo_stopped = self._isDoorServoStopped()
            if not chute_stopped or not servo_stopped:
                # Jam detection: if we've been "waiting for movement" for
                # way longer than the estimated move time, something is
                # physically stuck. Raise hard alert + pause.
                elapsed_ms = (now - self._moving_started_at) * 1000
                budget_ms = max(
                    CHUTE_MOVE_TIMEOUT_MS,
                    int(self._chute_move_estimated_ms * CHUTE_MOVE_TIMEOUT_MULTIPLIER),
                )
                if elapsed_ms > budget_ms:
                    stuck = []
                    if not chute_stopped:
                        stuck.append("chute stepper did not stop")
                    if not servo_stopped:
                        stuck.append(f"layer-{self._door_servo_index} servo flap did not close")
                    self._raiseChuteJamAlert(
                        f"{' and '.join(stuck)} after {elapsed_ms:.0f}ms (budget {budget_ms}ms)"
                    )
                    # Abort this sortation; remain in POSITIONING so the
                    # pause event handled by the coordinator can take
                    # over. Returning IDLE here would let the next piece
                    # start a new move on top of the stuck one.
                    return None
                return None
            self.shared.set_chute_motion(False, target_bin=self._target_address)
            if self._piece is not None and self._piece.distribution_positioned_at is None:
                self._piece.distribution_positioned_at = time.time()
            move_ms = (now - self._moving_started_at) * 1000
            total_ms = (now - self._state_entered_at) * 1000
            if self.gc.disable_servos:
                self.logger.info(f"Positioning: complete (chute={move_ms:.0f}ms, total={total_ms:.0f}ms)")
            else:
                self.logger.info(f"Positioning: complete (servo+chute={move_ms:.0f}ms, total={total_ms:.0f}ms)")
            return DistributionState.READY

        return None

    def _startChuteMove(self) -> None:
        self.shared.set_chute_motion(True, target_bin=self._target_address)
        if self._piece is not None and self._piece.distribution_motion_started_at is None:
            self._piece.distribution_motion_started_at = time.time()
        if self._target_address is None:
            passthrough_angle = float(getattr(self.chute, "first_bin_center", 0.0) or 0.0)
            estimated_ms = self.chute.moveToAngle(passthrough_angle)
            self.logger.info(
                "Positioning: passthrough chute move started "
                f"(angle={passthrough_angle:.2f}°, est_ms={estimated_ms})"
            )
        else:
            estimated_ms = self.chute.moveToBin(self._target_address)
            self.logger.info(
                f"Positioning: chute move started (est_ms={estimated_ms})"
            )
        self._chute_move_estimated_ms = int(estimated_ms)
        self._phase = "moving"

    def cleanup(self) -> None:
        super().cleanup()
        target_address = self._target_address
        self._phase = "init"
        self._target_address = None
        self._door_servo_index = None
        self._state_entered_at = 0.0
        self._moving_started_at = 0.0
        self._piece = None
        self.shared.set_chute_motion(False, target_bin=target_address)

    def _isLayerUsable(self, layer_index: int) -> bool:
        """Check whether this layer is currently usable for a sort move.

        Historical behavior added a layer to ``_blocked_layers`` on the
        first transient servo hiccup and *never* removed it, which in
        practice meant one flaky heartbeat permanently disabled the
        layer until a restart. Now we always check the servo's live
        ``available`` state; ``_blocked_layers`` still acts as a fast
        no-op gate but gets cleared automatically once the servo reports
        healthy again.
        """
        if self.gc.disable_servos:
            return True
        if layer_index >= len(self.irl.servos):
            self._markLayerUnavailable(layer_index, "no servo configured for this layer")
            return False
        servo_available = bool(getattr(self.irl.servos[layer_index], "available", True))
        if not servo_available:
            self._servo_offline_layers.add(layer_index)
            self._markLayerUnavailable(layer_index, "its servo backend is offline")
            return False
        if layer_index in self._blocked_layers:
            # Servo has recovered — clear the cached block so positioning
            # starts considering this layer again.
            self._blocked_layers.discard(layer_index)
            self._servo_offline_layers.discard(layer_index)
            self.logger.info(
                f"Positioning: layer {layer_index} servo is back online, re-enabling"
            )
        # A healthy servo read means the Waveshare bus is talking again, so
        # clear any stale servo-bus banner regardless of whether the layer
        # was previously in the local block list. (The block list is
        # per-step and may have just been reset at the top of ``step``.)
        self._clearServoBusOfflineAlertIfOwned()
        return True

    def _markLayerUnavailable(self, layer_index: int, reason: str) -> None:
        if layer_index in self._blocked_layers:
            return
        self._blocked_layers.add(layer_index)
        self.logger.warning(
            f"Positioning: disabling layer {layer_index} temporarily because {reason}"
        )

    def _isDoorServoStopped(self) -> bool:
        if self._door_servo_index is None:
            return True
        try:
            return self.irl.servos[self._door_servo_index].stopped
        except Exception as exc:
            self._markLayerUnavailable(
                self._door_servo_index,
                f"servo stop check failed: {exc}",
            )
            return True

    def _raiseBinsFullAlert(self, category_id: str) -> None:
        return

    def _allEnabledLayersServoOffline(self) -> bool:
        """True iff every enabled layer's servo is currently flagged as
        offline. Used to separate the fatal servo-bus case from a soft
        "one layer jammed" case.
        """
        if self.gc.disable_servos:
            return False
        enabled_indices = [
            li
            for li, layer in enumerate(self.layout.layers)
            if getattr(layer, "enabled", True)
        ]
        if not enabled_indices:
            return False
        for li in enabled_indices:
            if li >= len(self.irl.servos):
                # Treat missing entries as offline so a half-configured
                # machine trips the alert too.
                continue
            if bool(getattr(self.irl.servos[li], "available", True)):
                return False
        return True

    def _raiseServoBusOfflineAlert(self, detail: str) -> None:
        """Fatal: the Waveshare bus is unreachable so no piece can be
        routed. Sets the red banner once, records the fault timestamp in
        runtime_stats, and pauses the controller. Cleared only when a
        servo comes back online via ``_isLayerUsable``.
        """
        if self._servo_bus_pause_enqueued:
            return
        self._servo_bus_pause_enqueued = True
        message = (
            f"{SERVO_BUS_ALERT_PREFIX} — {detail}. "
            "Check Waveshare USB + power, then press Resume."
        )
        self.logger.error(message)
        try:
            self.gc.profiler.hit("distribution.servo_bus_offline")
            self.gc.runtime_stats.observeBlockedReason(
                "distribution", "servo_bus_offline"
            )
            self.gc.runtime_stats.setServoBusOffline()
        except Exception:
            pass
        try:
            with shared_state.hardware_lifecycle_lock:
                shared_state.setHardwareStatus(error=message)
        except Exception:
            pass
        try:
            if shared_state.command_queue is not None:
                shared_state.command_queue.put(
                    PauseCommandEvent(tag="pause", data=PauseCommandData())
                )
        except Exception:
            pass

    def _clearServoBusOfflineAlertIfOwned(self) -> None:
        try:
            with shared_state.hardware_lifecycle_lock:
                err = shared_state.hardware_error
                if isinstance(err, str) and err.startswith(SERVO_BUS_ALERT_PREFIX):
                    shared_state.setHardwareStatus(clear_error=True)
        except Exception:
            pass
        self._servo_bus_pause_enqueued = False
        try:
            self.gc.runtime_stats.clearServoBusOffline()
        except Exception:
            pass

    def _raiseChuteJamAlert(self, detail: str) -> None:
        """Hard alert: chute / servo can't physically move. Raises the red
        banner *and* enqueues a pause so the operator has to intervene.
        """
        if self._jam_pause_enqueued:
            return
        self._jam_pause_enqueued = True
        message = (
            f"{CHUTE_JAM_ALERT_PREFIX}: {detail}. "
            "Clear any piece stuck in the chute or on the distribution tray, "
            "make sure the servo flap can move freely, then press play."
        )
        self.logger.error(message)
        try:
            self.gc.profiler.hit("distribution.chute_jam")
            self.gc.runtime_stats.observeBlockedReason("distribution", "chute_jam")
        except Exception:
            pass
        try:
            with shared_state.hardware_lifecycle_lock:
                shared_state.setHardwareStatus(error=message)
        except Exception:
            pass
        try:
            if shared_state.command_queue is not None:
                shared_state.command_queue.put(
                    PauseCommandEvent(tag="pause", data=PauseCommandData())
                )
        except Exception:
            pass

    def _clearChuteJamAlertIfOwned(self) -> None:
        try:
            with shared_state.hardware_lifecycle_lock:
                err = shared_state.hardware_error
                if isinstance(err, str) and err.startswith(CHUTE_JAM_ALERT_PREFIX):
                    shared_state.setHardwareStatus(clear_error=True)
        except Exception:
            pass
        self._jam_pause_enqueued = False

    def _clearBinsFullAlertIfOwned(self) -> None:
        try:
            with shared_state.hardware_lifecycle_lock:
                err = shared_state.hardware_error
                if isinstance(err, str) and (
                    err.startswith(BINS_FULL_ALERT_PREFIX)
                    or err.startswith(MISC_PASSTHROUGH_ALERT_PREFIX)
                ):
                    shared_state.setHardwareStatus(clear_error=True)
        except Exception:
            pass

    def _openAllDoorsForPassthrough(self) -> None:
        """Open every usable layer door so a piece with no assigned bin
        falls straight through to the bottom tray. A follow-up
        ``_selectDoor`` on the next piece will re-close the appropriate
        layer.
        """
        if self.gc.disable_servos:
            return
        for i, servo in enumerate(self.irl.servos):
            if not self._isLayerUsable(i):
                continue
            try:
                if servo.isClosed():
                    servo.open()
            except Exception as exc:
                self._markLayerUnavailable(
                    i,
                    f"opening for passthrough failed: {exc}",
                )

    def _selectDoor(self, target_layer_index: int) -> bool:
        if self.gc.disable_servos:
            return True
        if not self._isLayerUsable(target_layer_index):
            self._markLayerUnavailable(target_layer_index, "the target servo is unavailable")
            return False

        target_servo = self.irl.servos[target_layer_index]

        # Never trust shadow state: re-issue the full door configuration
        # before every dispense. Open every other usable layer (park), then
        # command the target closed — even if we stayed on the same layer
        # or the shadow flags claim the door is already in the right spot.
        # A dropped serial write, a partial move, or a mid-flight power
        # glitch can leave the physical flap out of sync without us
        # noticing until a piece lands in the wrong bin.
        for i, servo in enumerate(self.irl.servos):
            if i == target_layer_index or not self._isLayerUsable(i):
                continue
            try:
                servo.open()
            except Exception as exc:
                self._markLayerUnavailable(
                    i,
                    f"opening parked servo failed: {exc}",
                )

        try:
            target_servo.close()
        except Exception as exc:
            self._markLayerUnavailable(
                target_layer_index,
                f"closing target servo failed: {exc}",
            )
            return False

        return True

    def _findOrAssignBinForCategory(
        self, category_id: str
    ) -> tuple[Optional[BinAddress], bool]:
        from local_state import get_current_bin_piece_counts

        piece_counts = get_current_bin_piece_counts()
        first_unassigned: Optional[tuple[BinAddress, "Bin"]] = None
        has_usable_layers = False

        # Debug trace — categorizes every bin we looked at and why it was
        # skipped. Dumped below when the whole search comes back empty.
        skipped: list[str] = []
        enabled_layers = 0
        blocked_layer_idxs: list[int] = []
        unreachable_bins = 0
        full_bins = 0
        bins_with_cats = 0

        for layer_idx, layer in enumerate(self.layout.layers):
            if not getattr(layer, "enabled", True):
                skipped.append(f"layer{layer_idx}=disabled")
                continue
            enabled_layers += 1
            if not self._isLayerUsable(layer_idx):
                blocked_layer_idxs.append(layer_idx)
                continue

            has_usable_layers = True
            max_per_bin = getattr(layer, "max_pieces_per_bin", None)
            for section_idx, section in enumerate(layer.sections):
                for bin_idx, b in enumerate(section.bins):
                    address = BinAddress(layer_idx, section_idx, bin_idx)
                    if not self.chute.isBinReachable(address):
                        unreachable_bins += 1
                        continue
                    count = piece_counts.get((layer_idx, section_idx, bin_idx), 0)
                    is_full = max_per_bin is not None and count >= max_per_bin
                    if category_id in b.category_ids and not is_full:
                        return address, False
                    if b.category_ids:
                        bins_with_cats += 1
                    if is_full:
                        full_bins += 1
                    if not b.category_ids and first_unassigned is None:
                        first_unassigned = (address, b)

        if not has_usable_layers:
            self.logger.warning(
                f"Positioning: no usable storage layers (enabled={enabled_layers}, "
                f"blocked={blocked_layer_idxs}, skipped={skipped})"
            )
            # If every enabled layer is blocked because its servo backend is
            # offline (vs. e.g. an occasional close-timeout on a live bus),
            # this is the fatal case — raise the red banner + pause. We
            # raise here rather than inside ``_selectDoor`` because this
            # path catches bin-lookup before we ever commit to a layer.
            if enabled_layers > 0 and self._allEnabledLayersServoOffline():
                self._raiseServoBusOfflineAlert(
                    "every layer servo is unreachable"
                )
            return None, False

        # MISC must never claim an unassigned bin on its own. The discard
        # bucket below the chute (rendered in the UI as the virtual
        # Discard Bin) is what catches misc passthrough — taking a real
        # slot would silently swap that behavior. A bin only carries MISC
        # if the operator explicitly tagged it that way.
        if first_unassigned is not None and category_id != MISC_CATEGORY:
            address, b = first_unassigned
            b.category_ids = [category_id]
            setBinCategories(extractCategories(self.layout))
            self.logger.info(
                f"Positioning: assigned category {category_id} to bin at layer={address.layer_index}, section={address.section_index}, bin={address.bin_index}"
            )
            return address, True

        if category_id != MISC_CATEGORY:
            # No bin slot available for this category; fall back to MISC,
            # which will only succeed if the operator pre-assigned a bin
            # to MISC. Otherwise it returns None and the piece passes
            # through to the discard bucket.
            return self._findOrAssignBinForCategory(MISC_CATEGORY)

        self.logger.info(
            f"Positioning: MISC has no assigned bin — passthrough to discard bucket "
            f"(enabled_layers={enabled_layers}, blocked={blocked_layer_idxs}, "
            f"unreachable_bins={unreachable_bins}, full_bins={full_bins}, "
            f"bins_with_cats={bins_with_cats}, skipped={skipped})"
        )
        return None, False
