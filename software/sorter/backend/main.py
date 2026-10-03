from environment_sync import retireOldUiUnits, syncEnvironment
syncEnvironment()
retireOldUiUnits()

from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from local_state import get_api_keys
_saved_api_keys = get_api_keys()
if _saved_api_keys.get("openrouter"):
    os.environ["OPENROUTER_API_KEY"] = _saved_api_keys["openrouter"]

from global_config import mkGlobalConfig, GlobalConfig
from utils.event import slimKnownObjectForSocket
from server.api import app
from server.shared_state import (
    setGlobalConfig,
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
import db
from message_queue.handler import handleServerToMainEvent
from defs.consts import BACKEND_PORT
from defs.events import RuntimeStatsEvent, RuntimeStatsData
from irl.config import (
    mkIRLConfig,
    mkIRLInterface,
)
from vision import VisionManager
from process_guard import acquire_backend_process_guard, ProcessGuardError
from hardware.bus import MCUBusError
from hardware.fault import HardwareFault
from hardware.waveshare_bus_service import close_all_waveshare_bus_services
from server.waveshare_inventory import get_waveshare_inventory_manager
import uvicorn
import functools
import threading
import queue
import time
import signal
import sys

def _mkIRLInterfaceStandby(config, gc):
    """Create a minimal IRLInterface without hardware discovery (standby mode)."""
    from irl.config import IRLInterface, BinLayoutConfig, mkLayoutFromConfig
    from irl.bin_layout import getBinLayout
    irl = IRLInterface()
    irl.servos = []
    irl.distribution_layout = mkLayoutFromConfig(config.bin_layout_config)
    return irl


FRAME_RECORD_INTERVAL_MS = 100
LIFETIME_FLUSH_INTERVAL_MS = 10000
LOOP_STALL_WARN_MS = 250.0
# The broadcaster thread builds both views of the runtime stats, never the
# control loop: the full snapshot behind GET /runtime-stats and the perf
# history, and the small live part pushed to the dashboard when it changes.
RUNTIME_STATS_SNAPSHOT_INTERVAL_S = 1.0
RUNTIME_STATS_LIVE_INTERVAL_S = 0.5

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
    any layer's servo back online, so a subsequent Resume after
    reconnecting the bus recovers without a full restart.
    """
    import server.shared_state as shared_state
    from subsystems.distribution.positioning import SERVO_BUS_OFFLINE_TITLE

    servos = list(getattr(irl, "servos", []) or [])
    if not servos:
        return
    available = [bool(getattr(s, "available", True)) for s in servos]
    if any(available):
        return

    message = (
        "No layer servo responded at boot. "
        "Check the servo bus's USB cable and power, then press Resume."
    )
    gc.logger.error(f"{SERVO_BUS_OFFLINE_TITLE}: {message}")
    try:
        gc.runtime_stats.setServoBusOffline()
    except Exception:
        pass
    try:
        with shared_state.hardware_lifecycle_lock:
            shared_state.setHardwareStatus(error=HardwareFault(SERVO_BUS_OFFLINE_TITLE, message))
    except Exception:
        pass


def _parkAfterLinkFailure(gc: GlobalConfig, controller, exc: MCUBusError) -> None:
    """A control-board link failure is a hardware fault, not a reason to end the
    process: pause, and put the machine in error so Safe Home rediscovers the board."""
    import server.shared_state as shared_state

    gc.logger.error(f"Control board link failed while sorting: {exc}")
    try:
        controller.pause()
    except MCUBusError as pause_exc:
        gc.logger.error(f"Pausing after the link failure also failed: {pause_exc}")
    with shared_state.hardware_lifecycle_lock:
        shared_state.setHardwareStatus(
            state="error",
            error=HardwareFault(
                "Control board link lost", f"{exc}. Home the machine to reconnect."
            ),
        )


def _warnIfLoopStalled(gc: GlobalConfig, marks: list[tuple[str, float]]) -> None:
    """One WARN per control-loop iteration slower than LOOP_STALL_WARN_MS,
    naming the phases that took the time. `marks` are (phase, end time) pairs
    after a ("start", iteration start) pair."""
    total_ms = (marks[-1][1] - marks[0][1]) * 1000.0
    if total_ms < LOOP_STALL_WARN_MS:
        return
    phases = sorted(
        ((name, (end - start) * 1000.0) for (_, start), (name, end) in zip(marks, marks[1:])),
        key=lambda phase: phase[1],
        reverse=True,
    )
    gc.logger.warning(
        f"main loop stall {total_ms:.0f}ms: "
        + ", ".join(f"{name} {ms:.0f}ms" for name, ms in phases if ms >= 1.0)
    )


def _noPowerModeActive(gc: GlobalConfig) -> bool:
    return bool(getattr(gc, "no_power_development_mode", False))


def _startPerception(gc: GlobalConfig, irl_config, camera_service) -> None:
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

    try:
        import channel_crop_store
        from perception.channel_crop_capture import ChannelCropCollector

        channel_crop_store.configure(gc.logger)
        collector = ChannelCropCollector(perception_service=service, logger=gc.logger)
        collector.start()
        service.channel_crop_collector = collector
        gc.logger.info("Channel-crop capture collector started.")
    except Exception as exc:
        gc.logger.warning(f"Failed to start channel-crop collector: {exc}")

    try:
        import control_data_store
        from perception.transition_capture import ControlDataCollector

        control_data_store.configure(gc.logger)
        control_data_store.recoverOrphanedSegments()
        sim_collector = ControlDataCollector(
            perception_service=service, gc=gc, irl_config=irl_config
        )
        sim_collector.start()
        service.control_data_collector = sim_collector
        gc.logger.info("Control-data (feeder dynamics) capture collector started.")
    except Exception as exc:
        gc.logger.warning(f"Failed to start control-data collector: {exc}")


def runServer(gc: GlobalConfig) -> None:
    # Bind to loopback by default. Setting SORTER_API_HOST=0.0.0.0 (or a
    # specific IP) exposes the API to the LAN — every endpoint (system reset,
    # supervisor restart, calibration, camera control) becomes reachable from
    # any host that can route to this machine, so only do that on a trusted
    # network. CORS is widened to match in server/api.py.
    host = os.getenv("SORTER_API_HOST", "127.0.0.1") or "127.0.0.1"
    from local_state import get_tailscale_hostname, set_tailscale_hostname
    from server.security import (
        compute_allowed_ui_origins,
        explicit_allowed_origins,
        allow_any_origin,
        keep_tailscale_name,
        refresh_device_identity,
        _ui_port,
    )

    keep_tailscale_name(get_tailscale_hostname(), set_tailscale_hostname)
    device_hosts = refresh_device_identity()
    gc.logger.info(
        f"[server] binding host={host!r} port={BACKEND_PORT} ui_port={_ui_port()!r} "
        f"allow_any_origin={allow_any_origin()} "
        f"SORTER_API_ALLOWED_ORIGINS_override={explicit_allowed_origins()} "
        f"effective_allowed_origins={compute_allowed_ui_origins()} "
        f"device_hosts={sorted(device_hosts)}"
    )
    # log_config=None disables uvicorn's logging.config.dictConfig() pass. This
    # backend routes everything through its own Logger, so uvicorn's logging
    # setup is unused — and it intermittently crashed the api-server thread at
    # startup ("ValueError: Unknown level: 'INFO'" out of dictConfig), leaving
    # main.py alive but port 8000 unbound so the UI couldn't connect. Skipping
    # dictConfig removes the failure mode entirely. No per-message deflate:
    # JPEG video frames do not compress, so deflating them only costs CPU.
    uvicorn.run(
        app, host=host, port=BACKEND_PORT, log_level="error", ws="wsproto", ws_per_message_deflate=False, log_config=None
    )


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

    # Stuck-piece reaper: pieces that never reach the distributed stage stop
    # emitting events and would otherwise linger in the UI forever. Once a
    # second, mark any that have gone silent past the timeout as dead and
    # broadcast a final event so the UI (and the per-piece lookup) drop them.
    from defs.consts import STUCK_PIECE_TIMEOUT_S, STUCK_PIECE_REAP_INTERVAL_S
    from server import perf_history

    last_reap_mono = 0.0
    last_snapshot_mono = 0.0
    last_live_mono = 0.0

    while True:
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

            if command.tag == "known_object":
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

        try:
            if now_mono - last_snapshot_mono >= RUNTIME_STATS_SNAPSHOT_INTERVAL_S:
                last_snapshot_mono = now_mono
                snapshot = gc.runtime_stats.snapshot()
                shared_state.runtime_stats_snapshot = snapshot
                perf_history.record(snapshot, time.time())
            if now_mono - last_live_mono >= RUNTIME_STATS_LIVE_INTERVAL_S:
                last_live_mono = now_mono
                live = gc.runtime_stats.snapshot(live=True)
                if live != shared_state.runtime_stats_live:
                    shared_state.runtime_stats_live = live
                    pending_commands.append(
                        RuntimeStatsEvent(tag="runtime_stats", data=RuntimeStatsData(payload=live))
                    )
        except Exception as exc:
            gc.logger.warning(f"runtime stats snapshot failed: {exc}")

        if pending_commands:
            gc.runtime_stats.observePerfMs("socket.queue_depth", float(queue_depth))
            gc.runtime_stats.observePerfMs("socket.batch_size", float(len(pending_commands)))

        for command in pending_commands:
            payload = command.model_dump()
            if command.tag == "known_object":
                obj_payload = command.data.model_dump()
                # Detail-page lookup keeps the FULL object (incl. the cumulative
                # recognition_image_set list) in memory, served via
                # /api/pieces/<uuid>. The live socket carries only the
                # slim form (see slimKnownObjectForSocket) so the per-piece
                # payload stays bounded instead of growing quadratically.
                try:
                    gc.runtime_stats.observeKnownObject(obj_payload)
                except Exception as exc:
                    # Never let one malformed piece kill the broadcaster thread —
                    # that would silently freeze the entire live feed for every
                    # client until a restart. Skip this observation and continue.
                    gc.logger.warning(f"observeKnownObject failed, skipping piece: {exc}")
                # Persist any newly appended recognition crops to disk (bounded
                # enqueue; a dedicated worker does the decode + file/DB writes).
                try:
                    import piece_image_store

                    piece_image_store.enqueueKnownObjectImages(obj_payload)
                    piece_image_store.enqueueKnownObjectLinkImages(obj_payload)
                except Exception:
                    pass
                event_data = payload.get("data")
                if isinstance(event_data, dict):
                    payload["data"] = slimKnownObjectForSocket(event_data)
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
            if command.tag != "runtime_stats":
                gc.logger.debug(f"broadcasting {command.tag} event")
            # Encodes the event once and hands it to the event loop; it never
            # waits for a client (each has its own sender, see WsClient).
            send_started = time.perf_counter()
            shared_state.broadcast(payload)
            gc.runtime_stats.observePerfMs(
                "socket.broadcast_event_ms",
                (time.perf_counter() - send_started) * 1000.0,
            )

        if now_mono - last_reap_mono >= STUCK_PIECE_REAP_INTERVAL_S:
            last_reap_mono = now_mono
            for full_payload in gc.runtime_stats.reapStuckPieces(
                time.time(), STUCK_PIECE_TIMEOUT_S
            ):
                slim = slimKnownObjectForSocket(full_payload)
                # Persist to the durable history so a stuck piece still shows up
                # on /records (ordered by created_at) instead of vanishing —
                # normally only distributed pieces get recorded.
                import piece_records

                db.defer(
                    "recordPiece (reaped)",
                    functools.partial(
                        piece_records.recordPiece,
                        full_payload,
                        run_id=gc.run_id,
                        machine_id=gc.machine_id,
                    ),
                )
                gc.logger.info(
                    "reaping stuck piece "
                    f"{str(full_payload.get('uuid', ''))[:8]} "
                    f"(stage={getattr(full_payload.get('stage'), 'value', full_payload.get('stage'))} "
                    f"status={getattr(full_payload.get('classification_status'), 'value', full_payload.get('classification_status'))}) "
                    "— no progress to distributed before timeout"
                )
                shared_state.broadcast({"tag": "known_object", "data": slim})

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
            port=BACKEND_PORT,
        )
    except ProcessGuardError as exc:
        print(f"[process_guard] {exc}", file=sys.stderr)
        sys.exit(1)

    gc = mkGlobalConfig()
    db.configure(gc.logger)
    gc.run_recorder = RunRecorder(gc)
    gc.lifetime_stats = LifetimeStatsTracker()
    setGlobalConfig(gc)
    setCommandQueue(server_to_main_queue)
    startup_total_start = time.time()

    irl_config = mkIRLConfig()

    # Create a minimal IRL interface (no hardware discovery yet)
    irl = _mkIRLInterfaceStandby(irl_config, gc)

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
    vision = VisionManager(gc, camera_service)
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

    # Broadcast-liveness watchdog. The WS live feed (recent pieces, stall banner)
    # is pushed only by the broadcaster on the single asyncio loop. If that loop
    # wedges (a blocking call), broadcasts stop silently and
    # the feed freezes until restart — with no error anywhere in the logs. This
    # runs on its own thread (so it survives a wedged loop) and turns that
    # invisible freeze into one loud, timestamped WARN.
    def _broadcastLivenessWatchdog() -> None:
        import server.shared_state as ss

        STALE_WARN_S = 10.0
        CHECK_INTERVAL_S = 2.0
        warned = False
        while True:
            time.sleep(CHECK_INTERVAL_S)
            try:
                last_ok = ss.last_broadcast_ok_ts
                n_clients = len(ss.ws_clients)
                if last_ok <= 0.0 or n_clients == 0:
                    warned = False
                    continue
                stale_s = time.time() - last_ok
                if stale_s > STALE_WARN_S and not warned:
                    gc.logger.warning(
                        f"[broadcast-watchdog] no websocket broadcast for {stale_s:.1f}s "
                        f"with {n_clients} client(s) connected — asyncio loop likely wedged "
                        "(a blocking call); live feed frozen until it clears"
                    )
                    warned = True
                elif stale_s <= STALE_WARN_S and warned:
                    gc.logger.info("[broadcast-watchdog] websocket broadcast recovered")
                    warned = False
            except Exception:
                pass

    threading.Thread(
        target=_broadcastLivenessWatchdog, daemon=True, name="broadcast-watchdog"
    ).start()

    # Pre-warm the piece price cache off the request path. The first
    # value/aggregates computation revalues every historical (part, color) pair
    # via one batch request to Hive (hive_metadata.getBatchMovingAvgPrices),
    # served from the persistent price cache; done here in the background so no
    # records-page request ever pays the first cold fill.
    def warmPieceValueCaches() -> None:
        try:
            import piece_records

            piece_records.getValueStats(gc)
            piece_records.getAggregates(gc)
        except Exception as exc:
            gc.logger.warn(f"piece value cache pre-warm failed: {exc}")

    threading.Thread(
        target=warmPieceValueCaches, daemon=True, name="piece-value-prewarm"
    ).start()

    try:
        import piece_image_store

        piece_image_store.configure(gc.logger)
    except Exception:
        pass

    camera_service.start()
    _startPerception(gc, irl_config, camera_service)
    # Mode-agnostic: the sample collector runs in every config, gated only by
    # its own enable toggle (persisted). Started after cameras so feeds exist.
    from sample_collector import SampleCollector
    sample_collector = SampleCollector(gc, camera_service)
    sample_collector.start()
    gc.sample_collector = sample_collector
    # Reconciles local piece history (records + crops) up to every enabled Hive,
    # watermark-based so months of backlog sync without redundant re-uploads.
    from server.hive_sync import HiveSyncWorker
    hive_sync_worker = HiveSyncWorker(gc)
    hive_sync_worker.start()
    gc.hive_sync_worker = hive_sync_worker
    vision.start()
    # A detection slot with no usable model gets Hive's default for this
    # machine's runtime, in the background (nothing happens when every slot
    # has one). See server/default_model.py.
    from server import default_model
    default_model.start(gc.logger)
    waveshare_inventory = get_waveshare_inventory_manager()
    waveshare_inventory.start()
    waveshare_inventory.refresh()

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
        if _noPowerModeActive(gc):
            gc.logger.warning(
                "NO_POWER_DEVELOPMENT_MODE=1: safe recovery will initialize runtime "
                "without spoke alignment or chute homing."
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

        if not _noPowerModeActive(gc):
            from subsystems.classification_channel.two_piece.spoke_home import (
                maybeRunSpokeHome,
            )

            shared_state.setHardwareStatus(homing_step="Aligning classification channel...")
            if not maybeRunSpokeHome(gc, irl, irl_config, vision):
                gc.logger.warning("Classification-channel rev01 spoke home did not complete")

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
            irl, irl_config, gc, vision, main_to_server_queue
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
        if not db.drain(5.0):
            gc.logger.warning("Shutting down with database writes still queued")

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

    last_frame_record = time.time()
    last_lifetime_flush = time.time()
    last_main_loop_started = time.perf_counter()
    db.watch_realtime_thread()

    try:
        while not shutdown_requested.is_set():
            loop_started = time.perf_counter()
            marks = [("start", loop_started)]
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
            marks.append(("events", time.perf_counter()))

            # Video reaches the frontend only through the video websocket
            # (/ws/video). Keep this loop for heatmap/video-recorder frame
            # capture, without sending images over the control WebSocket.
            if (
                current_time - last_frame_record
                >= FRAME_RECORD_INTERVAL_MS / 1000.0
            ):
                vision.recordFrames()
                last_frame_record = current_time
            marks.append(("frames", time.perf_counter()))

            # Lifetime powered/sorted time: handed to the database writer every
            # 10 s, so a crash loses at most that much.
            if current_time - last_lifetime_flush >= LIFETIME_FLUSH_INTERVAL_MS / 1000.0:
                gc.lifetime_stats.flush()
                last_lifetime_flush = current_time
            marks.append(("lifetime", time.perf_counter()))

            with controller_lock:
                current_controller = controller
            if current_controller is not None:
                controller_step_started = time.perf_counter()
                try:
                    current_controller.step()
                except MCUBusError as exc:
                    _parkAfterLinkFailure(gc, current_controller, exc)
                gc.runtime_stats.observePerfMs(
                    "main.loop.controller_step_ms",
                    (time.perf_counter() - controller_step_started) * 1000.0,
                )
            marks.append(("step", time.perf_counter()))

            time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)
            marks.append(("sleep", time.perf_counter()))
            _warnIfLoopStalled(gc, marks)
    except KeyboardInterrupt:
        shutdown_reason["value"] = "KeyboardInterrupt"
    finally:
        db.watch_realtime_thread(False)
        _shutdown_runtime(shutdown_reason["value"])


if __name__ == "__main__":
    main()
