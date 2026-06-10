from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from local_state import initialize_local_state
initialize_local_state()

from local_state import (
    get_api_keys,
    record_profiler_metric_snapshot,
    record_runtime_perf_metric_snapshot,
    remember_recent_known_object,
)
_saved_api_keys = get_api_keys()
if _saved_api_keys.get("openrouter"):
    os.environ["OPENROUTER_API_KEY"] = _saved_api_keys["openrouter"]

from global_config import mkGlobalConfig, GlobalConfig
from runtime_variables import mkRuntimeVariables
from utils.event import slimKnownObjectForSocket
from server.api import app
from server.shared_state import (
    broadcastEvent,
    setGlobalConfig,
    setRuntimeVariables,
    setCommandQueue,
    setController,
    setCameraService,
    setVisionManager,
    setHardwareInitializeFn,
    setHardwareResetFn,
    setHardwareRuntimeIRL,
    setHardwareStartFn,
)
from sorter_controller import SorterController
from stepper_stall_monitor import StepperStallMonitor
from run_recorder import RunRecorder
from lifetime_stats import LifetimeStatsTracker
from message_queue.handler import handleServerToMainEvent
from defs.events import HeartbeatEvent, HeartbeatData, MainThreadToServerCommand
from defs.events import RuntimeStatsEvent, RuntimeStatsData
from irl.config import (
    ClassificationChannelMode,
    FeederMode,
    mkIRLConfig,
    mkIRLInterface,
)
from subsystems.feeder.calibration import calibrateFeederChannels
from vision import VisionManager
from process_guard import acquire_backend_process_guard, ProcessGuardError
from hardware.waveshare_bus_service import close_all_waveshare_bus_services
from server.waveshare_inventory import get_waveshare_inventory_manager
import uvicorn
import threading
import queue
import time
import asyncio
import signal
import sys

def _mkIRLInterfaceStandby(config, gc):
    """Create a minimal IRLInterface without hardware discovery (standby mode)."""
    from irl.config import IRLInterface, BinLayoutConfig, mkLayoutFromConfig
    from irl.bin_layout import getBinLayout
    irl = IRLInterface()
    irl.servos = []
    irl.distribution_layout = mkLayoutFromConfig(config.bin_layout_config)
    irl.machine_profile = None
    return irl


FRAME_RECORD_INTERVAL_MS = 100
RUNTIME_STATS_BROADCAST_INTERVAL_MS = 1000
LIFETIME_FLUSH_INTERVAL_MS = 10000

SERVO_BUS_ALERT_PREFIX = "Servo bus offline"
CAMERA_SHUTDOWN_SETTLE_S = float(os.getenv("SORTER_CAMERA_SHUTDOWN_SETTLE_S", "1.0"))

server_to_main_queue = queue.Queue()
main_to_server_queue = queue.Queue()


def _checkServoBusHealth(gc: GlobalConfig, irl) -> None:
    """After ``servo.open()``, surface a fatal hardware banner if every
    configured layer servo reports ``available=False``. This flips the
    boot path from "warn once and silently pass pieces through" to a
    red-banner paused state that forces an operator check (USB, power,
    cabling) before the controller is allowed to accept pieces.

    The banner clears automatically the next time ``Positioning`` finds
    any layer's servo back online. Boot-time offline servos stay offline
    until the IRL is rebuilt, so the operator instruction is Home (full
    hardware recovery), not Resume.
    """
    import server.shared_state as shared_state

    servos = list(getattr(irl, "servos", []) or [])
    if not servos:
        return
    available = [bool(getattr(s, "available", True)) for s in servos]
    if any(available):
        return

    message = (
        f"{SERVO_BUS_ALERT_PREFIX} — no layer servos responded at boot. "
        "Check Waveshare USB + power, then press Home to re-initialize."
    )
    gc.logger.error(message)
    try:
        gc.runtime_stats.setServoBusOffline()
    except Exception:
        pass
    try:
        with shared_state.hardware_lifecycle_lock:
            shared_state.setHardwareStatus(error=message)
    except Exception:
        pass


def _noPowerModeActive(gc: GlobalConfig) -> bool:
    return bool(getattr(gc, "no_power_development_mode", False))


def _perceptionModeActive(irl_config) -> bool:
    """Rev04 perception stack: a perception-native feeder mode
    (GO_TO_ANGLE_REV01 or PULSE_PERCEPTION_REV01) paired with the
    SIMPLE_STATE_MACHINE_REV01 classification channel. The perception package
    owns detection for these pairs only; every other mode pair keeps using the
    legacy VisionManager paths."""
    feeder_mode = getattr(getattr(irl_config, "feeder_config", None), "mode", None)
    cc_mode = getattr(
        getattr(irl_config, "classification_channel_config", None), "mode", None
    )
    return (
        feeder_mode in (FeederMode.GO_TO_ANGLE_REV01, FeederMode.PULSE_PERCEPTION_REV01)
        and cc_mode == ClassificationChannelMode.SIMPLE_STATE_MACHINE_REV01
    )


def _maybeStartPerception(gc: GlobalConfig, irl_config, camera_service) -> None:
    if not _perceptionModeActive(irl_config):
        gc.logger.info(
            "Perception (rev04) inactive: mode pair is not "
            "(GO_TO_ANGLE_REV01, SIMPLE_STATE_MACHINE_REV01). Legacy vision owns detection."
        )
        return

    from perception import service as perception_service_mod
    from vision.detection_registry import detection_algorithm_definition

    def _lookup_model(algorithm_id: str):
        definition = detection_algorithm_definition(algorithm_id)
        if definition is None or definition.model_path is None:
            return None
        return definition.model_path, int(definition.imgsz or 320)

    service = perception_service_mod.build(
        gc=gc,
        irl_config=irl_config,
        camera_service=camera_service,
        model_path_lookup=_lookup_model,
    )
    service.start()
    gc.perception_service = service
    gc.logger.info(
        f"Perception (rev04) started: channels={sorted(service.channels().keys())} "
        f"workers={sorted(service.workers().keys())}"
    )


def runServer(gc: GlobalConfig) -> None:
    # Bind to loopback by default. Setting SORTER_API_HOST=0.0.0.0 (or a
    # specific IP) exposes the API to the LAN — every endpoint (system reset,
    # supervisor restart, calibration, camera control) becomes reachable from
    # any host that can route to this machine, so only do that on a trusted
    # network. CORS is widened to match in server/api.py.
    host = os.getenv("SORTER_API_HOST", "127.0.0.1") or "127.0.0.1"
    from server.security import (
        compute_allowed_ui_origins,
        explicit_allowed_origins,
        allow_any_origin,
        _this_device_hosts,
        _ui_port,
    )

    gc.logger.info(
        f"[server] binding host={host!r} port=8000 ui_port={_ui_port()!r} "
        f"allow_any_origin={allow_any_origin()} "
        f"SORTER_API_ALLOWED_ORIGINS_override={explicit_allowed_origins()} "
        f"effective_allowed_origins={compute_allowed_ui_origins()} "
        f"device_hosts={sorted(_this_device_hosts())}"
    )
    uvicorn.run(app, host=host, port=8000, log_level="error", ws="wsproto")


def runBroadcaster(gc: GlobalConfig) -> None:
    import server.shared_state as shared_state

    while shared_state.server_loop is None:
        time.sleep(0.01)

    # Per-piece rate limit for known_object events on the live socket. A piece in
    # the rotate/capture phase emits one known_object PER CAMERA FRAME (hundreds
    # per second across a run); the broadcaster and the browser can't keep up and
    # fall many seconds behind. The UI only needs the latest state a few times a
    # second, so we coalesce per piece and sample at this interval — but always
    # send IMMEDIATELY on a stage/classification_status change so transitions stay
    # instant. uuid -> (last_send_mono, stage, status).
    KNOWN_OBJECT_THROTTLE_S = 0.1
    ko_last_broadcast: dict = {}

    while True:
        latest_frame_commands = {}
        pending_commands = []
        ko_latest: dict = {}

        # Backlog gauge: how deep the queue is BEFORE we drain it. A persistently
        # large value means the broadcaster can't keep up with producers and
        # frontend state is arriving late. ~0 means the pipeline is keeping pace.
        queue_depth = main_to_server_queue.qsize()

        while True:
            try:
                command = main_to_server_queue.get(block=False)
            except queue.Empty:
                break

            if command.tag == "frame":
                latest_frame_commands[command.data.camera] = command
            elif command.tag == "known_object":
                # Coalesce per piece (latest wins) using cheap attribute access;
                # we only model_dump() the events we actually send below, so a
                # piece emitting at camera-frame rate with a growing image list
                # doesn't cost a full serialization per frame.
                ko_latest[command.data.uuid] = command
            else:
                pending_commands.append(command)

        # Pick which coalesced known_objects actually reach the socket.
        now_mono = time.monotonic()
        for uuid, command in ko_latest.items():
            stage = command.data.stage
            status = command.data.classification_status
            last = ko_last_broadcast.get(uuid)
            changed = last is None or last[1] != stage or last[2] != status
            due = last is None or (now_mono - last[0]) >= KNOWN_OBJECT_THROTTLE_S
            if changed or due:
                ko_last_broadcast[uuid] = (now_mono, stage, status)
                pending_commands.append(command)
        if len(ko_last_broadcast) > 256:
            cutoff = now_mono - 30.0
            for uuid in [u for u, v in ko_last_broadcast.items() if v[0] < cutoff]:
                del ko_last_broadcast[uuid]

        pending_commands.extend(latest_frame_commands.values())

        if pending_commands:
            gc.runtime_stats.observePerfMs("socket.queue_depth", float(queue_depth))
            gc.runtime_stats.observePerfMs("socket.batch_size", float(len(pending_commands)))

        for command in pending_commands:
            payload = command.model_dump()
            if command.tag == "known_object":
                obj_payload = command.data.model_dump()
                # Detail-page lookup keeps the FULL object (incl. the cumulative
                # recognition_images list) in memory, served via
                # /api/known-objects/<uuid>. The live socket and the recent ring
                # carry only the slim form (see slimKnownObjectForSocket) so the
                # per-piece payload stays bounded instead of growing quadratically.
                gc.runtime_stats.observeKnownObject(obj_payload)
                event_data = payload.get("data")
                if isinstance(event_data, dict):
                    payload["data"] = slimKnownObjectForSocket(event_data)
                remember_recent_known_object(slimKnownObjectForSocket(obj_payload))
                # End-to-end backend latency for a piece update: wall-clock now
                # minus when the piece was stamped (updated_at, set right before
                # emit). This is the number that must be near-zero for the UI to
                # feel realtime — it captures queue wait + broadcaster time.
                updated_at = obj_payload.get("updated_at")
                if isinstance(updated_at, (int, float)):
                    gc.runtime_stats.observePerfMs(
                        "socket.known_object_send_age_ms",
                        max(0.0, (time.time() - float(updated_at)) * 1000.0),
                    )
            if (
                command.tag != "frame"
                and command.tag != "heartbeat"
                and command.tag != "runtime_stats"
            ):
                gc.logger.info(f"broadcasting {command.tag} event")
            send_started = time.perf_counter()
            future = asyncio.run_coroutine_threadsafe(
                broadcastEvent(payload), shared_state.server_loop
            )
            try:
                future.result(timeout=1.0)
            except Exception:
                pass
            # Time to push ONE event to all clients. Large here (with depth ~0)
            # points at a slow client or a saturated asyncio loop (e.g. MJPEG),
            # not a producer backlog.
            gc.runtime_stats.observePerfMs(
                "socket.broadcast_event_ms",
                (time.perf_counter() - send_started) * 1000.0,
            )

        time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)



def main() -> None:
    import server.shared_state as shared_state

    shutdown_requested = threading.Event()
    shutdown_reason = {"value": "process shutdown"}

    def _request_shutdown(signum, _frame) -> None:
        try:
            shutdown_reason["value"] = signal.Signals(signum).name
        except Exception:
            shutdown_reason["value"] = "signal shutdown"
        shutdown_requested.set()

    # SIGTERM is used by the supervisor/system service for "hard restart".
    # Release AVFoundation/OpenCV camera handles before exiting so the next
    # process can reopen every USB camera instead of racing stale handles.
    signal.signal(signal.SIGTERM, _request_shutdown)

    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[2]
    try:
        backend_process_guard = acquire_backend_process_guard(
            script_path=script_path,
            repo_root=repo_root,
            port=8000,
        )
    except ProcessGuardError as exc:
        print(f"[process_guard] {exc}", file=sys.stderr)
        sys.exit(1)

    gc = mkGlobalConfig()
    gc.run_recorder = RunRecorder(gc)
    gc.lifetime_stats = LifetimeStatsTracker(gc)
    setGlobalConfig(gc)
    rv = mkRuntimeVariables(gc)
    setRuntimeVariables(rv)
    setCommandQueue(server_to_main_queue)
    startup_total_start = time.time()

    with gc.profiler.timer("startup.irl_config_ms"):
        irl_config = mkIRLConfig()

    # Create a minimal IRL interface (no hardware discovery yet)
    irl = _mkIRLInterfaceStandby(irl_config, gc)

    with gc.profiler.timer("startup.camera_service_init_ms"):
        from vision.camera_service import CameraService
        from defs.events import CameraHealthEvent, CameraHealthData
        camera_service = CameraService(irl_config, gc)
        setCameraService(camera_service)

        def _on_camera_health_change(health_map: dict[str, str]) -> None:
            event = CameraHealthEvent(
                tag="camera_health",
                data=CameraHealthData(cameras=health_map),
            )
            main_to_server_queue.put(event)

        camera_service.set_health_event_callback(_on_camera_health_change)
    with gc.profiler.timer("startup.vision_init_ms"):
        vision = VisionManager(irl_config, gc, irl, camera_service)
        setVisionManager(vision)
    # Controller is deferred until hardware is started
    controller = None
    controller_lock = threading.RLock()
    gc.logger.info("client starting in standby mode (hardware not initialized)...")

    # Bring up the API/broadcast threads before the heavier camera + vision
    # startup steps. That way the backend stays reachable even if a camera or
    # inventory subsystem stalls during initialization.
    server_thread = threading.Thread(target=runServer, args=(gc,), daemon=True, name="api-server")
    server_thread.start()

    broadcaster_thread = threading.Thread(
        target=runBroadcaster, args=(gc,), daemon=True, name="ws-broadcaster"
    )
    broadcaster_thread.start()

    with gc.profiler.timer("startup.camera_service_start_ms"):
        camera_service.start()
    # Rev04: build the perception service BEFORE vision.start() so the
    # VisionManager's start path can see gc.perception_service and skip
    # legacy detection startup in the new mode pair. The build() helper
    # waits briefly for camera frames so the channel masks can be sized
    # against the real camera resolution.
    with gc.profiler.timer("startup.perception_start_ms"):
        _maybeStartPerception(gc, irl_config, camera_service)
    # Mode-agnostic: the sample collector runs in every config, gated only by
    # its own enable toggle (persisted). Started after cameras so feeds exist.
    from sample_collector import SampleCollector
    sample_collector = SampleCollector(gc, camera_service)
    sample_collector.start()
    gc.sample_collector = sample_collector
    with gc.profiler.timer("startup.vision_start_ms"):
        vision.start()
    with gc.profiler.timer("startup.waveshare_inventory_ms"):
        waveshare_inventory = get_waveshare_inventory_manager()
        waveshare_inventory.start()
        waveshare_inventory.refresh()

    # Versioned settings backup to Hive: pushes a snapshot whenever the local
    # config hash changes (Hive dedups), so backups version on real changes only.
    try:
        from server.config_backup import get_config_backup_sync
        get_config_backup_sync().start()
    except Exception as exc:
        gc.logger.warning(f"config-backup sync not started: {exc}")

    startup_total_ms = (time.time() - startup_total_start) * 1000
    gc.logger.info(f"standby startup complete in {startup_total_ms:.0f}ms")
    def _replace_irl(next_irl) -> None:
        nonlocal irl
        with controller_lock:
            irl.__dict__.clear()
            irl.__dict__.update(next_irl.__dict__)

    def _drain_runtime_commands(reason: str) -> None:
        dropped = 0
        while True:
            try:
                server_to_main_queue.get(block=False)
                dropped += 1
            except queue.Empty:
                break
        if dropped:
            gc.logger.info(f"Dropped {dropped} queued runtime command(s) during {reason}")

    def _cleanup_runtime_hardware(reason: str) -> None:
        nonlocal irl, controller

        gc.logger.info(f"Cleaning up hardware runtime: {reason}")
        _drain_runtime_commands(reason)
        setHardwareRuntimeIRL(None)

        with controller_lock:
            old_controller = controller
            controller = None
            setController(None)
            if old_controller is not None:
                try:
                    old_controller.stop()
                except Exception as exc:
                    gc.logger.warning(f"Failed to stop controller cleanly: {exc}")

        for servo in list(getattr(irl, "servos", [])):
            try:
                if hasattr(servo, "stop"):
                    servo.stop()
            except Exception as exc:
                gc.logger.warning(f"Failed to stop servo during cleanup: {exc}")

        try:
            irl.disableSteppers()
        except Exception as exc:
            gc.logger.warning(f"Failed to disable steppers during cleanup: {exc}")

        try:
            irl.shutdown()
        except Exception as exc:
            gc.logger.warning(f"Failed to shut down hardware interfaces cleanly: {exc}")

        try:
            close_all_waveshare_bus_services()
        except Exception as exc:
            gc.logger.warning(f"Failed to close Waveshare bus services cleanly: {exc}")
        try:
            get_waveshare_inventory_manager().trigger_refresh()
        except Exception:
            pass

        standby_irl = _mkIRLInterfaceStandby(irl_config, gc)
        _replace_irl(standby_irl)
        setHardwareRuntimeIRL(None)

    # Register the safe recovery function for /api/system/recover and its
    # backwards-compatible /api/system/home alias. This path owns the motors
    # exclusively until all homing is done and the runtime is published in a
    # paused state.
    def _home_hardware() -> None:
        nonlocal irl, controller

        _drain_runtime_commands("safe recovery start")
        with controller_lock:
            current_controller = controller
        active_irl = shared_state.getActiveIRL()
        if current_controller is not None or active_irl is not None and getattr(active_irl, "interfaces", {}):
            _cleanup_runtime_hardware("preparing for homing")

        shared_state.setHardwareStatus(homing_step="Discovering hardware...")
        gc.logger.info("Starting hardware initialization...")
        real_irl = mkIRLInterface(irl_config, gc)
        _replace_irl(real_irl)
        setHardwareRuntimeIRL(irl)
        machine_setup = getattr(irl_config, "machine_setup", None)
        manual_feed_mode = bool(
            getattr(machine_setup, "manual_feed_mode", False)
            if machine_setup is not None
            else getattr(irl_config, "feeding_mode", "auto_channels") == "manual_carousel"
        )

        if machine_setup is not None:
            gc.logger.info(
                f"Machine setup selected: {machine_setup.key} "
                f"(auto_feeder={machine_setup.automatic_feeder}, "
                f"carousel_transport={machine_setup.uses_carousel_transport})"
            )
        if _noPowerModeActive(gc):
            gc.logger.warning(
                "NO_POWER_DEVELOPMENT_MODE=1: safe recovery will initialize runtime "
                "without feeder calibration, spoke alignment, carousel homing, or chute homing."
            )
        if manual_feed_mode:
            gc.logger.info(
                "Manual carousel feed mode enabled: automatic C-channel feeding and feeder calibration are disabled."
            )
        elif machine_setup is not None and not machine_setup.runtime_supported:
            gc.logger.warning(
                "Machine setup %r is experimental. Homing rules are applied, but the "
                "runtime is not implemented yet."
                % machine_setup.key
            )

        if gc.disable_servos:
            gc.logger.info("Servo control disabled via --disable servos")
        else:
            shared_state.setHardwareStatus(homing_step="Opening servos...")
            gc.logger.info("Opening all layer servos...")
            for servo in irl.servos:
                try:
                    if getattr(servo, "is_calibrated", True):
                        if hasattr(servo, "apply_homing_speed"):
                            servo.apply_homing_speed()
                        servo.open()
                    else:
                        # An uncalibrated servo must never be driven or held. A prior
                        # calibrator jog leaves the channel energized at a stale angle
                        # (move_to never releases PWM) and that hold survives a backend
                        # restart, so a plain open() no-op would leave the servo hunting
                        # and twitching through homing. Disabling cuts PWM (duty=0) so it
                        # goes slack and physically cannot move.
                        servo.enabled = False
                        gc.logger.info(
                            f"Servo ch{getattr(servo, 'channel', '?')} uncalibrated — "
                            "released (PWM off) instead of opening."
                        )
                except Exception as e:
                    gc.logger.warning(f"Failed to open servo: {e}. Continuing without initialization.")
            _checkServoBusHealth(gc, irl)

        feeder_detection_ready = vision.initFeederDetection(manual_feed_mode=manual_feed_mode)
        if manual_feed_mode:
            if not feeder_detection_ready:
                gc.logger.warning(
                    "Manual carousel feed mode is enabled, but carousel trigger detection is not fully configured."
                )
        elif feeder_detection_ready and not _noPowerModeActive(gc) and bool(
            getattr(machine_setup, "runs_reverse_pulse_calibration", True)
        ):
            # Reverse-pulse calibration seeds background-subtraction models
            # (MOG2 / heatmap) with an empty-ring view. The feeder may have
            # moved to Hive/Gemini and no longer need it, but the CAROUSEL
            # heatmap still relies on this warm-up window unless it's also
            # been switched to gemini_sam. Run the pulses whenever either
            # subsystem still uses a baseline.
            feeder_algorithms = (
                vision.getFeederDetectionAlgorithms()
                if hasattr(vision, "getFeederDetectionAlgorithms")
                else {"feeder": vision.getFeederDetectionAlgorithm()}
            )
            feeder_mog2_roles = sorted(
                role for role, algorithm in feeder_algorithms.items() if algorithm == "mog2"
            )
            feeder_needs_baseline = bool(feeder_mog2_roles)
            carousel_needs_baseline = bool(
                getattr(machine_setup, "uses_carousel_transport", True)
            ) and vision.usesCarouselBaseline()
            if feeder_needs_baseline or carousel_needs_baseline:
                reason = []
                if feeder_needs_baseline:
                    reason.append(f"feeder(mog2)={','.join(feeder_mog2_roles)}")
                if carousel_needs_baseline:
                    reason.append("carousel=baseline")
                shared_state.setHardwareStatus(homing_step="Calibrating feeder channels...")
                gc.logger.info(
                    f"Running feeder reverse-pulse calibration ({', '.join(reason)})"
                )
                calibrateFeederChannels(gc, irl, irl_config)
            else:
                gc.logger.info(
                    f"Skipping feeder reverse-pulse calibration — "
                    f"feeder_roles={feeder_algorithms!r}, carousel uses dynamic detection"
                )
        elif feeder_detection_ready:
            gc.logger.info(
                "Skipping feeder reverse-pulse calibration for machine setup %r."
                % getattr(machine_setup, "key", "unknown")
            )
        else:
            gc.logger.warning("Feeder channel polygons not found — continuing without feeder detection")

        if irl_config.camera_layout == "split_feeder":
            has_classification = (
                vision._classification_top_capture is not None
                or vision._classification_bottom_capture is not None
            )
            if has_classification and vision.usesClassificationBaseline():
                if not vision.loadClassificationBaseline():
                    gc.logger.warning("Classification baseline not found — continuing without classification")
        elif vision.usesClassificationBaseline() and not vision.loadClassificationBaseline():
            gc.logger.warning("Classification baseline not found — continuing without classification")

        classification_mode = getattr(
            getattr(irl_config, "classification_channel_config", None),
            "mode",
            None,
        )
        if (
            classification_mode == ClassificationChannelMode.SIMPLE_STATE_MACHINE_REV01
            and not _noPowerModeActive(gc)
        ):
            from subsystems.classification_channel.simple_state_machine_rev01.spoke_home import (
                maybeRunSpokeHome,
            )

            shared_state.setHardwareStatus(homing_step="Aligning classification channel...")
            if not maybeRunSpokeHome(gc, irl, irl_config, vision):
                gc.logger.warning("Classification-channel rev01 spoke home did not complete")

        if _noPowerModeActive(gc):
            gc.logger.info("Skipping carousel homing in no-power development mode.")
        elif bool(getattr(machine_setup, "homes_carousel", True)):
            shared_state.setHardwareStatus(homing_step="Homing carousel...")
            carousel_hw = getattr(irl, "carousel_hw", None)
            if carousel_hw is not None:
                gc.logger.info("Homing carousel...")
                if carousel_hw.home():
                    gc.logger.info("Carousel homed successfully.")
                else:
                    raise RuntimeError("Carousel homing failed.")
            else:
                raise RuntimeError("Carousel hardware not initialized.")
        else:
            gc.logger.info(
                "Skipping carousel homing for machine setup %r."
                % getattr(machine_setup, "key", "unknown")
            )

        # Build the coordinator while it is still private. The controller is
        # not published and not started until all homing is finished, so a
        # queued/resubmitted Resume cannot make the runtime fight the homing
        # sequence.
        if _noPowerModeActive(gc):
            shared_state.setHardwareStatus(
                homing_step="Initializing distributor without homing..."
            )
        else:
            shared_state.setHardwareStatus(homing_step="Homing distributor...")

        next_controller = SorterController(
            irl, irl_config, gc, vision, main_to_server_queue, rv
        )

        chute = getattr(next_controller.coordinator.distribution, "chute", None) if hasattr(next_controller, "coordinator") else None
        if chute is not None and not _noPowerModeActive(gc):
            gc.logger.info("Homing chute...")
            try:
                if chute.home():
                    gc.logger.info("Chute homed successfully.")
                else:
                    raise RuntimeError("Chute homing failed.")
            except Exception as e:
                next_controller.coordinator.cleanup()
                raise RuntimeError(f"Chute homing failed: {e}") from e
        elif chute is not None:
            gc.logger.info("Skipping chute homing in no-power development mode.")

        _drain_runtime_commands("safe recovery finish")
        with controller_lock:
            controller = next_controller
        setController(next_controller)
        next_controller.start()
        try:
            get_waveshare_inventory_manager().trigger_refresh()
        except Exception:
            pass

        shared_state.setHardwareStatus(clear_homing_step=True)
        gc.logger.info("Safe hardware recovery complete; runtime is paused.")

    def _initialize_hardware() -> None:
        """Bring up the IRL and enable steppers without homing carousel/chute.

        Used by the setup wizard's Motion Direction Check step so the operator
        can jog each stepper before endstops have been verified.
        """
        nonlocal irl, controller

        with controller_lock:
            current_controller = controller
        active_irl = shared_state.getActiveIRL()
        if current_controller is not None or active_irl is not None and getattr(active_irl, "interfaces", {}):
            _cleanup_runtime_hardware("preparing for stepper jog")

        shared_state.setHardwareStatus(homing_step="Discovering hardware...")
        gc.logger.info("Initializing hardware (no homing)...")
        real_irl = mkIRLInterface(irl_config, gc)
        _replace_irl(real_irl)
        setHardwareRuntimeIRL(irl)

        if gc.disable_servos:
            gc.logger.info("Servo control disabled via --disable servos")
        else:
            shared_state.setHardwareStatus(homing_step="Opening servos...")
            for servo in irl.servos:
                try:
                    if hasattr(servo, "apply_homing_speed"):
                        servo.apply_homing_speed()
                    servo.open()
                except Exception as e:
                    gc.logger.warning(f"Failed to open servo: {e}. Continuing without initialization.")
            _checkServoBusHealth(gc, irl)

        shared_state.setHardwareStatus(clear_homing_step=True)
        gc.logger.info("Hardware initialized (steppers ready, no homing performed).")

    setHardwareStartFn(_home_hardware)
    setHardwareInitializeFn(_initialize_hardware)
    setHardwareResetFn(lambda: _cleanup_runtime_hardware("system reset"))

    def _shutdown_runtime(reason: str) -> None:
        gc.logger.info(f"Shutting down ({reason})...")

        try:
            gc.lifetime_stats.flush()
        except Exception as exc:
            gc.logger.warning(f"Failed to flush lifetime stats during shutdown: {exc}")

        try:
            gc.run_recorder.save()
        except Exception as exc:
            gc.logger.warning(f"Failed to save run recorder during shutdown: {exc}")

        try:
            vision.stop()
        except Exception as exc:
            gc.logger.warning(f"Failed to stop vision during shutdown: {exc}")

        try:
            camera_service.stop()
        except Exception as exc:
            gc.logger.warning(f"Failed to stop camera service during shutdown: {exc}")

        if CAMERA_SHUTDOWN_SETTLE_S > 0:
            time.sleep(CAMERA_SHUTDOWN_SETTLE_S)

        gc.logger.info("Stopping all motors...")
        try:
            _cleanup_runtime_hardware("process shutdown")
        except Exception as exc:
            gc.logger.warning(f"Failed to clean up hardware runtime during shutdown: {exc}")

        gc.logger.info("Cleanup complete")
        try:
            gc.logger.flushLogs()
        finally:
            backend_process_guard.release()

    # StallGuard stall detection: a daemon thread polls the firmware DIAG latch
    # for every stepper that has an enabled threshold and raises a blocking
    # `stepper_stall` incident on a stall. Detection is on for all moves (armed at
    # hardware init), so this watcher needs no machine-state gating. Off the main
    # loop so the UART reads never hitch operation.
    from hardware.sorter_interface import DISABLE_STALLGUARD

    if not _noPowerModeActive(gc) and not DISABLE_STALLGUARD:
        stall_monitor = StepperStallMonitor(gc)
        threading.Thread(
            target=stall_monitor.run,
            daemon=True,
            name="stall-monitor",
        ).start()
    elif DISABLE_STALLGUARD:
        gc.logger.info("StallGuard monitor not started (DISABLE_STALLGUARD=1).")

    last_heartbeat = time.time()
    last_frame_record = time.time()
    last_runtime_stats_broadcast = time.time()
    last_lifetime_flush = time.time()
    last_runtime_perf_snapshot = time.time()
    last_profiler_snapshot = time.time()
    last_main_loop_started = time.perf_counter()

    try:
        while not shutdown_requested.is_set():
            loop_started = time.perf_counter()
            gc.profiler.hit("main.loop.calls")
            gc.profiler.mark("main.loop.interval_ms")
            gc.runtime_stats.observePerfMs(
                "main.loop.interval_ms",
                (loop_started - last_main_loop_started) * 1000.0,
            )
            last_main_loop_started = loop_started
            try:
                event = server_to_main_queue.get(block=False)
                with controller_lock:
                    current_controller = controller
                if current_controller is not None:
                    handleServerToMainEvent(gc, current_controller, event)
            except queue.Empty:
                pass

            current_time = time.time()

            # send periodic heartbeat
            # can probably remove this later, just helps debug web sockets from time to time
            if (
                current_time - last_heartbeat
                >= gc.timeouts.heartbeat_interval_ms / 1000.0
            ):
                heartbeat = HeartbeatEvent(
                    tag="heartbeat", data=HeartbeatData(timestamp=current_time)
                )
                main_to_server_queue.put(heartbeat)
                last_heartbeat = current_time

            # Video reaches the frontend only through MJPEG camera feeds. Keep
            # this loop for heatmap/video-recorder frame capture, without
            # broadcasting Base64 image payloads over the control WebSocket.
            if (
                current_time - last_frame_record
                >= FRAME_RECORD_INTERVAL_MS / 1000.0
            ):
                with gc.profiler.timer("main.loop.record_frames_ms"):
                    vision.recordFrames()
                last_frame_record = current_time

            if (
                current_time - last_runtime_stats_broadcast
                >= RUNTIME_STATS_BROADCAST_INTERVAL_MS / 1000.0
            ):
                runtime_stats = RuntimeStatsEvent(
                    tag="runtime_stats",
                    data=RuntimeStatsData(payload=gc.runtime_stats.snapshot()),
                )
                main_to_server_queue.put(runtime_stats)
                last_runtime_stats_broadcast = current_time

            # Durable lifetime accumulator — periodic flush so powered/sorted
            # time survives the soft-restart (os._exit) that skips save().
            if current_time - last_lifetime_flush >= LIFETIME_FLUSH_INTERVAL_MS / 1000.0:
                gc.lifetime_stats.flush()
                last_lifetime_flush = current_time

            if (
                current_time - last_runtime_perf_snapshot
                >= RUNTIME_STATS_BROADCAST_INTERVAL_MS / 1000.0
            ):
                record_runtime_perf_metric_snapshot(
                    gc.run_id,
                    current_time,
                    gc.runtime_stats.perfSnapshotRows(),
                )
                last_runtime_perf_snapshot = current_time

            if (
                gc.profiler.enabled
                and current_time - last_profiler_snapshot >= gc.profiler.report_interval_s
            ):
                record_profiler_metric_snapshot(
                    gc.run_id,
                    current_time,
                    gc.profiler.snapshotRows(),
                )
                last_profiler_snapshot = current_time

            with controller_lock:
                current_controller = controller
            if current_controller is not None:
                with gc.profiler.timer("main.loop.controller_step_ms"):
                    controller_step_started = time.perf_counter()
                    current_controller.step()
                    gc.runtime_stats.observePerfMs(
                        "main.loop.controller_step_ms",
                        (time.perf_counter() - controller_step_started) * 1000.0,
                    )

            time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)
    except KeyboardInterrupt:
        shutdown_reason["value"] = "KeyboardInterrupt"
    finally:
        _shutdown_runtime(shutdown_reason["value"])


if __name__ == "__main__":
    main()
