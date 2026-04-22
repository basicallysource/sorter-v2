---
title: Runtime Current-State Map
date: 2026-04-22
scope: software/sorter/backend/
purpose: Input for runtime rearchitecture design. Point-in-time snapshot of revision on branch `sorthive`.
status: LEGACY (pre-rearchitecture, 2026-04-22)
---

> ## ⚠ LEGACY — THIS IS THE OLD ARCHITECTURE
>
> This document maps the runtime state **before** the rearchitecture that started 2026-04-22 on the `sorthive` branch. It exists **only** as a migration reference — to understand what was being replaced, and to cross-check that the new runtime preserves required behavior.
>
> **Do not read this as target architecture.** The target lives in:
> - `runtime-architecture.html` (canonical visual vision)
> - `docs/lab/runtime-rebuild-design.md` (engineering companion with contracts, phases, effort)
>
> If you find yourself implementing against patterns described here (the 4963-line god-class, the 27-globals `shared_state.py`, the dual classification pipelines, the `_home_hardware()` `__dict__` mutation, the unbounded Brickognize daemon threads): **stop and consult the new docs.** You have drifted.
>
> *Banner added 2026-04-22 as part of the rebuild kickoff.*

# LegoSorter Backend Runtime — Complete Architecture Map

**Scope:** `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/`
**Date surveyed:** 2026-04-22
**Revision analyzed:** branch `sorthive`

---

## 1. Module Inventory

### Entry / Config

| File | Role |
|------|------|
| `main.py` | Single entry point. Builds the process: gc→rv→irl→camera_service→vision→server thread→broadcaster thread→main loop |
| `global_config.py` | `GlobalConfig` dataclass + `mkGlobalConfig()` — parses argparse + env vars, constructs `Logger`, `Profiler`, `RuntimeStatsCollector` |
| `runtime_variables.py` | `RuntimeVariables` — UI-editable knobs (belt speed etc.); exposes `VARIABLE_DEFS` list |
| `machine_setup.py` | Frozen dataclass registry for the 3 machine topologies (`standard_carousel`, `classification_channel`, `manual_carousel`) |
| `machine_runtime/__init__.py` | `build_machine_runtime(key)` — dispatches to `StandardCarouselRuntime` or `ClassificationChannelRuntime` |
| `machine_runtime/base.py` | `MachineRuntime` ABC — `create_transport`, `create_feeder`, `create_classification`, `create_distribution` |
| `machine_runtime/standard_carousel.py` | Standard carousel runtime |
| `machine_runtime/classification_channel.py` | C-channel-4 classification variant |
| `defs/consts.py` | `LOOP_TICK_MS=20`, `CHANNEL_SECTION_*`, static angular section ranges |
| `defs/events.py` | Pydantic models for all WS events (`FrameEvent`, `KnownObjectEvent`, `HeartbeatEvent`, …) |
| `defs/channel.py` | `ChannelDetection`, `PolygonChannel`, `ChannelGeometry` — cross-system data classes |
| `defs/known_object.py` | `KnownObject`, `PieceStage`, `ClassificationStatus` — the canonical piece dossier |
| `defs/sorter_controller.py` | `SorterLifecycle` enum |
| `role_aliases.py` | Camera/role string normalization (public `classification_channel` ↔ internal `carousel`) |

### Orchestration

| File | Role |
|------|------|
| `sorter_controller.py` | Thin lifecycle FSM wrapper around `Coordinator`; drives `step()` from the main loop |
| `coordinator.py` | Wires feeder + classification + distribution subsystems; owns `TickBus` and `SharedVariables`; calls `MachineRuntime` factories |
| `piece_transport.py` | `PieceTransport` ABC + `ClassificationChannelTransport` concrete; the piece queue between classification and distribution |
| `sorting_profile.py` | Loads the sorting rules (which part goes to which bin) |
| `run_recorder.py` | Logs per-run statistics to disk |
| `aruco_config_manager.py` | CRUD for ArUco tag JSON config |
| `process_guard.py` | PID-file + port-conflict guard to prevent double-start |

### Subsystems

**Feeder (`subsystems/feeder/`)**

| File | Role |
|------|------|
| `state_machine.py` | `FeederStateMachine` — `IDLE` ↔ `FEEDING` |
| `feeding.py` | `Feeding` state: calls `analyzeFeederChannels`, drives C1/C2/C3 stations via `FeederTickContext` |
| `idle.py` | `Idle` state |
| `analysis.py` | `analyzeFeederChannels()` — maps `ChannelDetection` list to `FeederAnalysis` (ch2/ch3 action + dropzone flags) |
| `admission.py` | `classification_channel_admission_blocked()` — the C3→C4 back-pressure gate |
| `ch2_separation.py` | `Ch2SeparationDriver` — slip-stick idle-time agitation for C2; currently disabled (`CH2_SEPARATION_ENABLED=False`) |
| `strategies/c1_jam_recovery.py` | `C1JamRecoveryStrategy` — escalating shake+push recovery |
| `strategies/c3_holdover.py` | `C3HoldoverStrategy` — holds CH3 in PRECISE for 2 s after a precise detection |
| `calibration.py` | `calibrateFeederChannels()` — reverse-pulse warm-up for MOG2 baseline |

**Channels (`subsystems/channels/`)**

| File | Role |
|------|------|
| `base.py` | `BaseStation`, `FeederTickContext` (mutable tick-level state bag), exit-wiggle constants |
| `c1_bulk.py` | `C1Station` — bulk rotor logic, calls `C1JamRecoveryStrategy` |
| `c2_separation.py` | `C2Station` — separation ring logic, drives `Ch2SeparationDriver` |
| `c3_precise.py` | `C3Station` — precise exit logic, drives exit wiggle |

**Classification — Standard Carousel (`subsystems/classification/`)**

| File | Role |
|------|------|
| `state_machine.py` | `ClassificationStateMachine` (`IDLE→DETECTING→ROTATING→SNAPPING`) |
| `idle.py`, `detecting.py`, `rotating.py`, `snapping.py` | State implementations |
| `carousel.py` | `Carousel` — in-memory ring of `KnownObject` slots |
| `carousel_hardware.py` | Wraps physical carousel stepper |
| `bbox_projection.py` | Crop-coordinate translation helpers |

**Classification — C-Channel Setup (`subsystems/classification_channel/`)**

| File | Role |
|------|------|
| `state_machine.py` | `ClassificationChannelStateMachine` (`IDLE→DETECTING/RUNNING→SNAPPING→EJECTING`; `RUNNING` in dynamic-zone mode) |
| `idle.py`, `detecting.py`, `running.py`, `snapping.py`, `ejecting.py` | State implementations |
| `zone_manager.py` | `ZoneManager` — per-piece angular slots on the classification ring; `TrackAngularExtent`, `ExclusionZone` |
| `recognition.py` | `ClassificationChannelRecognizer` — calls Brickognize, assembles `KnownObject` |

**Distribution (`subsystems/distribution/`)**

| File | Role |
|------|------|
| `state_machine.py` | `DistributionStateMachine` (`IDLE→POSITIONING→READY→SENDING`) |
| `idle.py`, `positioning.py`, `ready.py`, `sending.py` | State implementations |
| `chute.py` | Chute hardware abstraction |

**Shared infra (`subsystems/`)**

| File | Role |
|------|------|
| `base_subsystem.py` | `BaseSubsystem` |
| `shared_variables.py` | `SharedVariables` — inter-subsystem gate flags + TickBus bridge |
| `bus/tick_bus.py` | `TickBus` — in-process pub/sub for gate/motion events |
| `bus/messages.py` | `StationGate`, `ChuteMotion`, `PieceRequest`, `PieceDelivered` typed events |

### Vision

| File | Role |
|------|------|
| `vision/vision_manager.py` | **~2800-line god class**; owns all detection paths, tracker wiring, overlay wiring, region loading, sample scheduling |
| `vision/camera_service.py` | `CameraService` — device/feed registry, frame encode loop, health tracking |
| `vision/camera.py` | `CaptureThread` — OpenCV capture + color correction per camera |
| `vision/camera_feed.py` | `CameraFeed` — annotated frame encode + overlay pipeline |
| `vision/camera_device.py` | `CameraDevice` — health polling abstraction |
| `vision/mog2_channel_detector.py` | `Mog2ChannelDetector` — per-channel MOG2 background subtractor |
| `vision/feeder_analysis_thread.py` | `FeederAnalysisThread` — dedicated 30 ms poll thread for MOG2 |
| `vision/classification_analysis_thread.py` | `ClassificationAnalysisThread` — baseline-diff analysis thread |
| `vision/heatmap_diff.py` | `HeatmapDiff` — carousel drop-detection via frame differencing |
| `vision/gemini_sam_detector.py` | `GeminiSamDetector` — cloud vision API (OpenRouter/Gemini) for piece detection |
| `vision/detection_registry.py` | Algorithm registry — builtin + Hive-installed YOLO/NanoDet ONNX/NCNN |
| `vision/tracking/__init__.py` | `build_feeder_tracker_system()` — wires per-role `PolarFeederTracker` + `PieceHandoffManager` |
| `vision/tracking/polar_tracker.py` | `PolarFeederTracker` — Kalman tracker in (angle, radius) space + Hungarian matching |
| `vision/tracking/handoff.py` | `PieceHandoffManager` — cross-camera `global_id` inheritance |
| `vision/tracking/history.py` | `PieceHistoryBuffer`, `TrackSegment`, `SectorSnapshot` — persistent track history |
| `vision/tracking/bytetrack_tracker.py` | `ByteTrackFeederTracker` — legacy fallback tracker (not used in current config) |
| `vision/tracking/drop_zone_burst.py` | `DropZoneBurstCollector` — pre+post event frame bursts for piece dossier |
| `vision/tracking/appearance.py` | Embedding extraction (OSNet) for cosine-similarity matching |
| `vision/regions.py`, `vision/aruco_region_provider.py`, `vision/default_region_provider.py`, `vision/handdrawn_region_provider.py` | Region polygon sources |
| `vision/overlays/` | Overlay classes (RegionOverlay, TrackOverlay, HeatmapOverlay, TelemetryOverlay, …) |
| `vision/burst_store.py` | `BurstFrameStore` — per-piece pre/post-event frame ring buffer (C3→C4 drop-zone) |
| `vision/diff_configs.py` | `CarouselDiffConfig`, `ClassificationDiffConfig` |
| `vision/ml.py` | Hive model loader (`create_processor`) |

### Classification Engine

| File | Role |
|------|------|
| `classification/__init__.py` | Re-exports `classify` |
| `classification/brickognize.py` | `classify()` — async thread, calls `api.brickognize.com`, returns part_id + color |
| `classification/brickognize_types.py` | Pydantic types for Brickognize API response |

### API / Server

| File | Role |
|------|------|
| `server/api.py` | FastAPI app, all HTTP + WS routes |
| `server/shared_state.py` | **All mutable process-wide globals** — websocket connections, all singleton refs, hardware state, broadcast helpers |
| `server/routers/` | Route groups (cameras, feeder, distribution, aruco, sorting_profile, …) |
| `server/classification_training.py` | Sample collection manager |
| `server/set_progress_sync.py` | Hive upload sync worker |
| `server/waveshare_inventory.py` | Servo bus inventory (background thread) |
| `server/camera_discovery.py` | Camera device discovery helper |
| `server/security.py` | CORS / WS origin allowlist |

### Hardware

| File | Role |
|------|------|
| `hardware/sorter_interface.py` | `SorterInterface`, `StepperMotor`, `ServoMotor`, `DigitalInputPin` — hardware abstraction layer |
| `hardware/bus.py` | `MCUBus` — serial COBS framing to microcontroller |
| `hardware/cobs.py` | COBS encode/decode |
| `hardware/waveshare_bus_service.py` | Waveshare servo bus driver |
| `hardware/macos_uvc_controls.py` | macOS UVC camera controls |
| `hardware/macos_camera_registry.py` | macOS camera enumeration |
| `irl/config.py` | `IRLInterface`, `IRLConfig`, `mkIRLInterface()` — hardware topology discovery and wiring |
| `irl/parse_user_toml.py` | Reads `machine_params.toml` and `machine_specific_params.toml` |
| `irl/bin_layout.py` | `DistributionLayout` — bin→category mapping |

### Persistence / Cross-cutting

| File | Role |
|------|------|
| `local_state.py` | SQLite DB wrapper — stores bin categories, channel polygons, servo states, API keys, recent known objects, piece dossiers |
| `blob_manager.py` | File I/O — `BLOB_DIR`, piece crops, run videos, machine ID |
| `runtime_stats.py` | `RuntimeStatsCollector` — in-memory metrics ring buffers, timeline events, snapshot for WS broadcast |
| `profiler.py` | `Profiler` — wall-clock timers and counters, optional periodic console report |
| `logger.py` | `Logger` wrapper |
| `message_queue/handler.py` | `handleServerToMainEvent` — routes inbound WS commands (pause, resume, reload-profile) to `SorterController` |
| `utils/event.py` | `knownObjectToEvent()` — converts `KnownObject` → `KnownObjectEvent` |
| `set_progress.py` | `SetProgressTracker` — per-set sort completion accounting |

**Potentially dead / prototype code:**

- `vision/tracking/bytetrack_tracker.py` — `SortFeederTracker` alias exists but is never instantiated in the current `build_feeder_tracker_system()` path
- `subsystems/feeder/ch2_separation.py` — `CH2_SEPARATION_ENABLED = False` hardcoded kill-switch
- `subsystems/feeder/feeding.py:39` — `CH2_AGITATION_ENABLED = False` legacy jog, replaced by `Ch2SeparationDriver` which is itself disabled
- `subsystems/classification/` (standard carousel path) — entirely bypassed when `machine_setup=classification_channel`; both runtimes coexist but have no shared interface contract

---

## 2. Entry Points & Lifecycle

**Single entry point:** `main.py:590 → main()`

### Thread Model

| Thread | Owner | Purpose |
|--------|-------|---------|
| `MainThread` | `main()` | Main loop: polls server→main queue, drives `SorterController.step()`, broadcasts frames/heartbeat/stats at fixed intervals |
| `server_thread` (daemon) | `runServer()` | uvicorn + asyncio event loop |
| `broadcaster_thread` (daemon) | `runBroadcaster()` | Drains `main_to_server_queue`, coalesces frame events, schedules WS broadcast on server loop |
| `FeederAnalysisThread` (daemon) | `VisionManager` | 30 ms MOG2 detection loop per active feeder role |
| `ClassificationAnalysisThread` (daemon) | `VisionManager` | Baseline-diff detection loop for classification cameras |
| `CaptureThread` (daemon, per camera) | `CameraService` | OpenCV capture, color correction, latest frame storage |
| `FrameEncodeThread` (daemon) | `CameraService` | JPEG encode + overlay rendering at 100 ms |
| `AuxiliaryDetectionThread` (daemon) | `VisionManager` | 250 ms background Gemini/Hive inference + sample scheduling |
| `hardware_worker_thread` (daemon) | `server/shared_state.py` | Runs `_home_hardware()` / `_initialize_hardware()` off the API thread |
| `SetProgressSyncWorker` | `server/set_progress_sync.py` | Background Hive sync |
| `WaveshareInventoryThread` | `server/waveshare_inventory.py` | Periodic servo bus inventory |
| Classification thread | `classification/brickognize.py:35` | Per-piece Brickognize API call (`threading.Thread(target=_doClassify, daemon=True)`) |

**Startup order** (main.py lines 193–254):

1. `mkGlobalConfig()`, `RunRecorder`
2. `mkIRLConfig()` (reads TOML, no hardware yet)
3. `ArucoConfigManager`
4. `_mkIRLInterfaceStandby()` — a skeleton IRL with no hardware
5. `CameraService.__init__()` + `setCameraService()`
6. `VisionManager.__init__()` + `setVisionManager()`
7. `server_thread.start()` — API available now
8. `broadcaster_thread.start()`
9. `camera_service.start()` — capture threads start
10. `vision.start()` — auxiliary detection thread starts
11. `waveshare_inventory.start() + refresh()`
12. Hardware start deferred until `/api/system/home` is called via `_home_hardware()`

**Shutdown:** `KeyboardInterrupt` → `vision.stop()` → `camera_service.stop()` → `_cleanup_runtime_hardware()`. Graceful but the process relies entirely on daemon threads; if the main loop is blocked (e.g. in a blocking stepper call that hangs), SIGINT may not be serviced promptly.

**Race conditions visible in init:**

- `main.py:120` (`runBroadcaster`): busy-spins on `shared_state.server_loop is None` — the asyncio loop reference is set from within the server thread by a startup event handler; no timeout guard.
- `server/shared_state.py:130-133` (`setVisionManager`): triggers `auto_calibrate()` which calls `vision_manager.getRegions()` — at this point `_feeder_capture` may have no frame yet and `getRegions` returns `{}` silently.
- Hardware worker thread (`hardware_worker_thread`) runs `_home_hardware()` with `controller_lock` but the controller itself is replaced without stopping old vision state; there is no fence between the new controller being set and the main loop calling `current_controller.step()`.

---

## 3. Dataflow: The Hot Path

A single LEGO piece traversing from C1 to a bin:

**Stage 1 — Camera capture (background)**

`CaptureThread._loop()` (`vision/camera.py`) runs per-camera at camera frame rate. Stores latest frame in `CaptureThread.latest_frame: CameraFrame | None`. No queue — overwritten each frame. Readers see a stale frame if they read mid-capture.

**Stage 2 — MOG2 detection (background thread, ~30 ms)**

`FeederAnalysisThread._loop()` (`vision/feeder_analysis_thread.py:51`) calls `self._get_gray()` → `vision_manager.getLatestFeederRaw()` (reads `_feeder_capture.latest_frame.raw`), then `Mog2ChannelDetector.detect(gray)` → returns `list[ChannelDetection]`. Stored in `_latest_detections` behind a `threading.Lock`. Mechanism: **shared mutable state with lock**.

*Alternate path (dynamic algorithms):* `VisionManager._getFeederDynamicDetection(role)` is called from the overlay render path and/or the tracker update path. It calls either `_runGeminiDetectionRequest()` (cloud, throttled) or `_runHiveDetection()` (local ONNX). Results cached in `_feeder_dynamic_detection_cache[role]` — a `dict[str, tuple[float, result]]` with no lock (written from multiple threads in theory).

**Stage 3 — Tracker update (called from detection path / overlay path)**

`VisionManager._updateFeederTracker(role, detection, timestamp)` (`vision_manager.py:2454`) → `PolarFeederTracker.update(bboxes, scores, timestamp)` → Hungarian matching in polar space → returns `list[TrackedPiece]`. Stored in `_feeder_track_cache[role]`.

**Stage 4 — Main loop tick (every 20 ms)**

`main.py:570` calls `current_controller.step()` → `sorter_controller.py:83` calls `coordinator.step()` → `coordinator.py:140-150`:
```
bus.begin_tick()
distribution.step()
classification.step()
feeder.step()
```
Mechanism: **direct synchronous call chain** on the main thread.

**Stage 5 — Feeder analysis**

`FeederStateMachine.step()` → `Feeding.step()` → `Feeding._tick_once()` (`feeding.py:255`):

1. `self.vision.getFeederHeatmapDetections()` — reads `_feeder_analysis.getDetections()` (lock acquire), or drives `_getFeederDynamicDetection()` for dynamic algorithms. Returns `list[ChannelDetection]`.
2. `analyzeFeederChannels(gc, detections)` → `FeederAnalysis` (ch2_action, ch3_action, dropzone flags).
3. `_c3_holdover.apply(ch3_action, now)` — applies 2 s holdover.
4. `_classification_channel_admission_blocked()` — C3→C4 back-pressure gate (`admission.py`).
5. Build `FeederTickContext`.
6. `_c3_station.step(ctx)` → may call `_sendPulse("ch3_precise", …)` → `stepper.move_degrees()` (blocking hardware call on main thread).
7. `_c2_station.step(ctx)`, `_c1_station.step(ctx)`.
8. Schedules `vision.scheduleFeederTeacherCaptureAfterMove()` for sample collection side-channel.

Data structure passed forward: `FeederAnalysis` (dataclass), then `FeederTickContext` (mutable bag).

**Stage 6 — Classification**

`ClassificationStateMachine.step()` or `ClassificationChannelStateMachine.step()`. For the classification-channel path (`Running.step()`, `classification_channel/running.py:91`):
- Polls `irl.carousel_stepper.stopped` to wait for motion completion.
- Calls `vision.getFeederTracks("carousel")` to confirm piece presence.
- Calls `ClassificationChannelRecognizer.run()` which calls `classify()` → `brickognize.py:35` → spawns a daemon thread → HTTP POST to `api.brickognize.com`.
- Callback writes result into `KnownObject.part_id`, `color_id`, `classification_status`.
- `event_queue.put(knownObjectToEvent(piece))` → `main_to_server_queue` for WS broadcast.

**Stage 7 — Distribution**

`DistributionStateMachine.step()` → `Positioning.step()` (finds target bin) → `Ready.step()` → `Sending.step()` (`distribution/sending.py:47`):
- `transport.getPieceForDistributionDrop()` — reads `KnownObject` from `ClassificationChannelTransport` or `Carousel`.
- Waits `CHUTE_SETTLE_MS=1500ms`.
- Then gates on `_shouldReopenGate()` — checks whether the carousel tracker still shows the piece's `global_id` (via `vision.getFeederTrackerLiveGlobalIds("carousel")`).
- On exit: `event_queue.put(knownObjectToEvent(piece))` → broadcast → `gc.run_recorder.recordPiece(piece)`.

**Summary of mechanism types:**

| Between stages | Mechanism |
|---------------|-----------|
| Camera → MOG2 thread | Shared mutable `latest_frame` (no queue, no lock on the frame itself) |
| MOG2 thread → Feeder tick | `threading.Lock` on `_latest_detections` |
| Dynamic detection → tracker | Direct call; result in `_feeder_dynamic_detection_cache` (dict, no lock) |
| Main loop → Feeder/Classification/Distribution | Direct synchronous call chain |
| Feeder tick → Hardware stepper | Blocking call on main thread (small risk of main loop stalls) |
| Classification → broadcast | `event_queue.put()` (unbounded `queue.Queue`) |
| Brickognize result → state machine | Callback into state machine from daemon thread (cross-thread write into shared `KnownObject`) |
| State machine → UI | `main_to_server_queue` → broadcaster thread → `asyncio.run_coroutine_threadsafe` |

---

## 4. Strategy Surface

### C-channel detection strategies (feeder scope)

Configured in `VisionManager._feeder_detection_algorithm_by_role: Dict[str, FeederDetectionAlgorithm]` (`vision_manager.py:133`). Loaded from `blob_manager.getFeederDetectionConfig()` (JSON in SQLite via `local_state.py`).

| Strategy id | Class/function | Selected by | Formal interface |
|-------------|---------------|-------------|-----------------|
| `"mog2"` | `Mog2ChannelDetector` + `FeederAnalysisThread` | DB config per role | Duck-typed: `detector.detect(gray)` returns `list[ChannelDetection]` |
| `"gemini_sam"` | `GeminiSamDetector._detect()` | DB config per role | Duck-typed: `detector.detect(crop, force=)` returns `ClassificationDetectionResult` |
| `"hive:<slug>"` | Loaded ONNX/NCNN model via `vision/ml.py create_processor` | DB config; model file discovered by `detection_registry._discover_hive_algorithms()` | Duck-typed: `processor.predict(frame)` → result |

Algorithm selection: `VisionManager.getFeederDetectionAlgorithm(role)` (`vision_manager.py`) → reads `_feeder_detection_algorithm_by_role[role]`. Changing at runtime via `setFeederDetectionAlgorithm()` invalidates `_feeder_dynamic_detection_cache`.

### Carousel/C4 detection strategy

Stored in `_carousel_detection_algorithm: CarouselDetectionAlgorithm`.

| Strategy id | Class | Selected by |
|-------------|-------|-------------|
| `"heatmap_diff"` | `HeatmapDiff` | DB config (carousel scope) |
| `"gemini_sam"` | `GeminiSamDetector` | DB config |
| `"hive:<slug>"` | Hive ONNX model | DB config + model file |

### Classification detection strategy

| Strategy id | Implementation |
|-------------|----------------|
| `"baseline_diff"` | `ClassificationAnalysisThread` + `HeatmapDiff` |
| `"gemini_sam"` | `GeminiSamDetector` |
| `"hive:<slug>"` | Hive ONNX |

### Tracker confirmation strategy

`PolarFeederTracker` uses a whitelist model (`polar_tracker.py:66-72`). A track becomes `confirmed_real=True` when it passes at least ONE of: monotonic angular progress ≥5°, or centroid drift ≥40px. This is hardcoded, not configurable via a strategy pattern — the thresholds are module-level constants.

### Feeder station strategies (C1, C2, C3)

| Strategy | Class | Interface |
|----------|-------|-----------|
| C1 jam recovery | `C1JamRecoveryStrategy` | Stateful, `run(cfg, now_mono)` → bool; escalating shake+push |
| C3 holdover | `C3HoldoverStrategy` | Stateful, `apply(action, now)` → ChannelAction; 2 s sticky-precise |

Both are concrete classes, no ABC. They are instantiated directly in `Feeding.__init__()` with no registry or configuration abstraction.

### Orphaned strategies

- `ByteTrackFeederTracker` is importable and has a `SortFeederTracker` alias but is never constructed at runtime. Dead.
- `CH2_AGITATION_ENABLED=False` jog pattern in `feeding.py:39` — replaced but not removed.
- `CH2_SEPARATION_ENABLED=False` in `ch2_separation.py:38` — disabled kill-switch; driver is wired but inert.

---

## 5. Backpressure & Capacity

### Queues between stages

| Queue | Type | Size | Drop / Block behavior |
|-------|------|------|----------------------|
| `server_to_main_queue` | `queue.Queue` (unbounded) | ∞ | Blocks producer if full (never — unbounded) |
| `main_to_server_queue` | `queue.Queue` (unbounded) | ∞ | Frame events are coalesced (latest-per-camera kept) in broadcaster |
| `FeederAnalysisThread._latest_detections` | Shared list, lock | Not a queue | Overwritten each detection cycle — no history |
| `_feeder_dynamic_detection_cache` | Dict | 1 entry per role | Overwritten; no lock (race condition possible) |
| `_feeder_track_cache` | Dict | 1 entry per role | Overwritten |
| `BurstFrameStore._store` | Dict, max 50 pieces | 50 | FIFO eviction |
| `RollingFrameBuffer` | Deque | Fixed (ring) | Oldest dropped |
| Brickognize thread | `threading.Thread` | 1 thread per piece | No limit — concurrent classify threads can pile up |

### The C3→C4 flood path

The acute symptom (C3 flooding C4) is gated by `admission.py:classification_channel_admission_blocked()` (`feeding.py:377`). The function checks:

1. **Raw detection cap:** `raw_detection_count >= MAX_CLASSIFICATION_CHANNEL_DETECTION_CAP` (currently `3`) — blocks C3 if the raw detector sees ≥3 blobs on C4 (`admission.py:45-50`).
2. **Zone manager capacity:** if `zone_manager.zone_count() >= max_zones` — blocks C3.
3. **Arc-clear check:** `zone_manager.is_arc_clear(intake_angle_deg, ...)` — blocks C3 if intake arc is occupied.
4. **Transport count:** `transport_piece_count >= max_zones` — blocks C3.

The check is called in `feeding.py:377`, then `classification_channel_block` propagates to `C3Station.step()` which simply returns early (`c3_precise.py:48-63`).

**Where backpressure is missing:**

- There is no queue between the **MOG2 analysis thread** and the **main loop feeder tick**. The analysis thread overwrites `_latest_detections` regardless of whether the main loop has consumed the previous result. If the main loop is slow (e.g., blocked by a stepper call), the next detection result silently replaces the unread one.
- There is no bounded queue between **classification completion** (Brickognize callback) and the **distribution state machine**. The callback writes directly into the `KnownObject` in whatever state the carousel currently holds it; if distribution is slow, pieces can pile up in the carousel ring buffer until they overflow.
- The `main_to_server_queue` is unbounded. Under a burst of frame events + known-object events, the broadcaster thread is the only consumer. A slow WS connection will cause this queue to grow without limit.
- There is no rate limit on spawning Brickognize threads (`brickognize.py:35` spawns a new `threading.Thread` per piece). If the API is slow and pieces arrive fast, thread count grows unbounded.
- The `AuxiliaryDetectionThread` uses a `BoundedSemaphore(10)` for OpenRouter calls (`OPENROUTER_MAX_CONCURRENCY=10`, `vision_manager.py:207`) but this is the only throughput limit.
- `_feeder_dynamic_detection_cache` is a plain dict written from the frame-encode thread (via overlay rendering calling `_ensure_detection`) and read from the feeder tick on the main thread — no lock (`vision_manager.py:354-365`).

---

## 6. Cross-Cutting Concerns

### Logging

`logger.py` wraps Python `logging`. All subsystems receive `gc.logger` via constructor injection. Direct calls: `gc.logger.info()`, `.warning()`, `.error()`. No structured logging; plain strings. Log level via `DEBUG_LEVEL` env var.

### Metrics / profiling

`profiler.py`: `Profiler` class with `hit()` (counters), `mark()` (interval tracking), `timer()` (context manager), `observeValue()`, `enterState()` / `exitState()`. Enabled via `PROFILER_ENABLED=1`. Reports to stdout at `PROFILER_REPORT_INTERVAL_S` interval. Injected via `gc.profiler`.

`runtime_stats.py`: `RuntimeStatsCollector` — in-memory ring buffers of timings, state timeline events, pulse counts, feeder signal snapshots. `snapshot()` produces a dict broadcast over WS as `runtime_stats` event every 1 s.

### UI status updates (WebSocket)

Path: state machine / hardware → `setHardwareStatus()` / `publishSorterState()` → `shared_state.broadcast_from_thread()` → `asyncio.run_coroutine_threadsafe(broadcastEvent(…), server_loop)` → iterate `active_connections` → `websocket.send_json()`.

Frame events follow a different path: main loop → `main_to_server_queue.put(FrameEvent)` → broadcaster thread → `asyncio.run_coroutine_threadsafe(broadcastEvent, server_loop)`.

Events that bypass the broadcaster thread and call `broadcast_from_thread()` directly:
- Hardware status changes (`setHardwareStatus`)
- Sorter FSM state changes (`publishSorterState`)
- Camera health changes (`_on_camera_health_change` callback)
- Cameras config changes

### Error surfacing

Hardware errors are written to `shared_state.hardware_error` string under `hardware_lifecycle_lock`, then broadcast as `system_status` event. Fatal errors trigger `PauseCommandEvent` on `server_to_main_queue` which flows back to `SorterController.pause()`.

### Sample saving / uploads

`vision/feeder_analysis_thread.py` schedules teacher captures via `vision.scheduleFeederTeacherCaptureAfterMove()` which enqueues an `AuxiliaryTeacherCaptureRequest`. The auxiliary detection thread (`_auxiliaryDetectionLoop`) processes these requests, calls `_runGeminiDetectionRequest()`, and saves results to disk. Hive upload is handled by `server/set_progress_sync.py` `SetProgressSyncWorker`.

Piece crops are saved in `blob_manager.write_piece_crop()` by the tracker's segment archival (`history.py`).

### Sound playback

Not present / unclear: no audio subsystem observed in any backend file.

### Cross-cutting in the hot path

`runtime_stats.observeFeederSignals()`, `observeFeederState()`, `observePulse()` are called inline inside `Feeding._tick_once()` on every main-loop tick. Similarly, profiler timers wrap every step call. These are not separated from the hot path.

---

## 7. Implicit Contracts & Coupling

### Module-level singletons / globals

`server/shared_state.py` contains 25+ module-level mutable globals:
- `active_connections: List[WebSocket]` — mutated from multiple async coroutines without a lock (FastAPI's single-thread async model assumed, fragile)
- `server_loop: Optional[asyncio.AbstractEventLoop]` — set once from inside uvicorn; read from main + broadcaster threads
- `gc_ref`, `vision_manager`, `camera_service`, `controller_ref`, `aruco_manager` — all set once at startup, never locked for read
- `hardware_state`, `hardware_error`, `hardware_homing_step` — protected by `hardware_lifecycle_lock` only when writing; readers often read without the lock

`blob_manager.py` is effectively a singleton filesystem namespace (`BLOB_DIR` path constant).

### Dependency direction

```
main.py
  → global_config, runtime_variables
  → irl.config (hardware)
  → vision.camera_service, vision.VisionManager
  → sorter_controller → coordinator
      → machine_runtime (factory)
      → subsystems.feeder (→ vision, irl, shared_variables)
      → subsystems.classification (→ vision, irl, shared_variables)
      → subsystems.distribution (→ irl, shared_variables, sorting_profile)
  → server (→ shared_state ← everything)
```

`shared_state` is imported by almost every leaf — it is the universal coupling point. `server.shared_state` imports from `global_config`, `irl.config`, `runtime_variables`, `aruco_config_manager` — creating a broad fan-in.

`feeding.py:3` imports `server.shared_state` directly to write hardware error banners. This means the feeder state machine is coupled to the API server module.

### Informal dict-key protocols

- `KnownObject` is a dataclass but many dict payloads are assembled ad-hoc (`obj_payload = command.data.model_dump()`) and augmented with extra keys like `track_detail`, `_sample_capture` — no schema.
- `AuxiliaryTeacherCaptureRequest.metadata` dict uses string keys `"background"` with no schema.
- `TrackAngularExtent.piece_uuid` optional field carries a semantic contract ("if set, use this uuid rather than minting a new one") that is documented only in comments.
- `VisionManager._liveTrackPayload()` assembles a dict with ~15 keys from internal tracker state — consumed by the API but never typed.

### Circular import risks

- `subsystems/feeder/feeding.py` imports `server.shared_state` — the server package imports back from `global_config`. Not a direct cycle but a semantic inversion (subsystem → server layer).
- `vision/vision_manager.py` imports from `subsystems.feeder.analysis` (at function call time) and from `subsystems.classification_channel.zone_manager` — bidirectional dependency between vision and subsystems.
- `main.py` deferred-imports `vision.camera_service.CameraService` inside the startup block (line 215) to avoid import-time side effects.

---

## 8. Configuration & Feature Flags

### Static configuration

- `machine_params.toml` / `machine_specific_params.toml` — hardware topology, stepper bindings, pulse configs, camera layout. Read by `irl/parse_user_toml.py` at startup.
- `SORTING_PROFILE_PATH` env var — path to the sorting rules JSON.
- `LOCAL_STATE_DB_PATH` env var — SQLite DB path.
- `SORTER_API_HOST`, `SORTER_UI_PORT`, `SORTER_API_ALLOWED_ORIGINS` — API binding.

### DB-backed config (SQLite via `local_state.py`)

All detection algorithm choices, polygon data, bin categories, API keys, servo states, aruco config are stored in SQLite and can be changed at runtime via API. No schema validation on read — `config.get("algorithm")` on a raw dict.

### Feature flags / experiments

| Flag | Location | Type |
|------|----------|------|
| `USE_CHANNEL_BUS=1` env | `global_config.py:85` | Env var; enables `TickBus` for cross-subsystem signaling |
| `CH2_SEPARATION_ENABLED=False` | `ch2_separation.py:38` | Hardcoded constant — kill-switch |
| `CH2_AGITATION_ENABLED=False` | `feeding.py:39` | Hardcoded constant — dead code |
| `--disable chute`, `--disable servos` | `global_config.py:83-84` | CLI args |
| `PROFILER_ENABLED=0` | `global_config.py:90` | Env var |
| `SORTER_HIVE_INFERENCE_INTERVAL_S` | `vision_manager.py:77` | Env var — inference throttle |
| `DEBUG_LEVEL` | `global_config.py:79` | Env var |
| `use_dynamic_zones` (classification channel config) | `irl_config.classification_channel_config.use_dynamic_zones` | TOML / DB — gates `Running` vs `Detecting/Snapping/Ejecting` states |

### Config validation

Essentially none. TOML parsing uses `dict.get()` with fallbacks throughout. SQLite JSON blobs are parsed with `config.get("key")` on raw dicts. `Pydantic` is used only for WS event models in `defs/events.py`.

---

## 9. Portability Assessment

| Subsystem | Verdict | Reason |
|-----------|---------|--------|
| `vision/tracking/polar_tracker.py` | Port with light cleanup | Solid algorithm, clean internal structure, but tightly coupled to `VisionManager` via `_feeder_track_cache` and `_feeder_dynamic_detection_cache` mutations |
| `vision/tracking/handoff.py` | Keep / port wholesale | Clean, self-contained, testable |
| `vision/tracking/history.py` | Port with light cleanup | Useful persistence logic, but `PieceHistoryBuffer` has ad-hoc side-channel wiring |
| `vision/mog2_channel_detector.py` | Keep / port wholesale | Well-isolated, no global state |
| `vision/heatmap_diff.py` | Keep / port wholesale | Self-contained |
| `vision/gemini_sam_detector.py` | Port with light cleanup | OpenRouter throttle logic is duplicated with `VisionManager`'s own semaphore |
| `vision/detection_registry.py` | Keep / port wholesale | Clean registry pattern |
| `vision/camera_service.py` | Port with light cleanup | Good device/feed abstraction but frame encoding mixed with health polling |
| `vision/camera.py` (CaptureThread) | Port with light cleanup | Capture logic OK; macOS UVC branch is platform-specific graft |
| `vision/vision_manager.py` | **Rewrite** | 2800-line god class — detection, tracking, overlay, sample scheduling, polygon loading, region providers, Hive ML processors all entangled with no clear interface boundary |
| `subsystems/feeder/` | Port with light cleanup | Analysis + station logic is well-factored; `feeding.py` imports `server.shared_state` (wrong direction) |
| `subsystems/feeder/admission.py` | Keep / port wholesale | Clean, self-contained |
| `subsystems/feeder/strategies/` | Keep / port wholesale | Small, clear strategies |
| `subsystems/classification/` | Port with light cleanup | Standard carousel path — clean state machine |
| `subsystems/classification_channel/` | Port with light cleanup | Newer, more complex, mostly well-structured |
| `subsystems/distribution/` | Port with light cleanup | Clean |
| `subsystems/bus/` | Keep / port wholesale | Clean pub/sub |
| `coordinator.py` | Port with light cleanup | Good orchestration layer but `use_channel_bus` conditional is fragile |
| `sorter_controller.py` | Keep / port wholesale | Thin and clean |
| `classification/brickognize.py` | Port with light cleanup | Spawns unbounded daemon threads, no rate limit |
| `server/shared_state.py` | **Rewrite** | 25+ mutable globals, inverse dependency (subsystems import it), no locking discipline |
| `irl/config.py` | Port with light cleanup | Monolithic hardware discovery, no ABC |
| `hardware/sorter_interface.py` | Keep / port wholesale | Reasonable HAL |
| `local_state.py` | Port with light cleanup | SQLite is fine; schema migration is ad-hoc |
| `vision/tracking/bytetrack_tracker.py` | **Delete** | Superseded by polar tracker, never instantiated |
| `subsystems/feeder/ch2_separation.py` | **Delete or enable** | Disabled kill-switch — either commit or remove |
| `CH2_AGITATION_ENABLED` path in `feeding.py` | **Delete** | Dead code |

---

## 10. Smells & Landmines

**1. `VisionManager` is a 2800-line god class**
`vision/vision_manager.py` owns detection, tracking, overlays, polygon loading, region providers, Hive ML processors, sample archival, burst frame collection, and OpenRouter throttling. State is scattered across 40+ instance variables. Testing any subsystem requires instantiating the whole object. Any refactor touches hundreds of existing call sites.

**2. `server/shared_state.py` inverted dependency**
Subsystem code (`subsystems/feeder/feeding.py:3`) imports `server.shared_state` to write hardware error banners. This couples the feeder directly to the API server layer — the direction of dependency is backwards. The pattern is repeated in at least `subsystems/distribution/sending.py:94` (`from server.set_progress_sync import getSetProgressSyncWorker`).

**3. Unbounded Brickognize threads**
`classification/brickognize.py:35` spawns `threading.Thread(target=_doClassify, daemon=True)` per piece with no semaphore, no queue, no max concurrency. If the API is slow (>8 s) and pieces arrive at 1 Hz, 8+ concurrent HTTPS connections pile up.

**4. `_feeder_dynamic_detection_cache` unprotected write**
`vision_manager.py:1672` writes `self._classification_dynamic_detection_cache[cam] = (frame.timestamp, detection)` from the overlay render path (frame-encode thread) and `_getDynamicClassificationDetection` (main thread). Python dict operations are GIL-protected for individual operations but a read-modify-write on the cache entry is not atomic. Similarly `_feeder_dynamic_detection_cache` at line 2486.

**5. Blocking stepper calls on the main loop thread**
`C1JamRecoveryStrategy._run_shake()` (`strategies/c1_jam_recovery.py:127`) calls `stepper.move_degrees_blocking(…, timeout_ms=2500)` — potentially 2.5 s of main-loop stall. During this time no classification or distribution steps are executed, and the heartbeat does not fire.

**6. The `_home_hardware()` closure replaces `irl` via `irl.__dict__` mutation**
`main.py:261-265` replaces the IRL hardware object by mutating `irl.__dict__.clear()` + `irl.__dict__.update(next_irl.__dict__)`. This is a prototype-era trick to avoid updating all references; it's invisible to type checkers, breaks `__slots__`, and is brittle if any subsystem has taken a reference to a specific field rather than the top-level `irl` object.

**7. `main_to_server_queue` is unbounded**
The broadcaster thread consumes events from this queue but only coalesces frame events (latest-per-camera). Non-frame events (known_object, camera_health, etc.) accumulate without limit. A WS disconnect followed by a busy classification run will grow the queue silently.

**8. Config is an ad-hoc JSON-in-SQLite bag with no validation**
`blob_manager.getFeederDetectionConfig()` returns a raw `dict | None`. Every consumer does `config.get("algorithm")` with no schema. A malformed DB entry silently falls back to defaults — there is no validation boundary, no migration test, no declarative schema.

**9. `shared_state.hardware_lifecycle_lock` locking discipline is inconsistent**
Some callers acquire the lock before calling `setHardwareStatus()` (`feeding.py:173`); others call `setHardwareStatus()` directly without the lock. The function itself acquires no lock internally — it relies on callers. The docstring says "Caller is responsible for holding lock when needed" which is not enforced anywhere.

**10. Dual classification pipeline with no shared interface**
`ClassificationStateMachine` (standard carousel) and `ClassificationChannelStateMachine` (C4 setup) are separate code paths selected by `machine_setup.key`. They share no ABC, no common step contract, and have diverged significantly in their occupancy-state instrumentation. Extending either requires knowing which path is active at runtime.

---

## 11. Open Questions for the Architect

1. **Should `VisionManager` be split along detection scope (feeder / classification / carousel) or along function (detection / tracking / overlay)?** The current monolith holds all three scopes and all three functions. Both splits are possible; the architect needs to decide the primary axis.

2. **Is `USE_CHANNEL_BUS` intended to become the sole cross-subsystem signaling mechanism, or is it a permanent optional layer?** Currently `SharedVariables` dual-modes between direct flag reads and TickBus messages (`shared_variables.py:190`). This dual path makes both paths harder to reason about.

3. **Should `server/shared_state.py` globals be converted to dependency-injected services, or is a scoped-singleton container (DI container) acceptable?** The current pattern is the only thing holding the process together — a replacement needs a clear plan for passing references without global state.

4. **Is the `ByteTrackFeederTracker` dead or is it kept as a configurable fallback?** If dead, delete. If intentional fallback, it needs a selection mechanism.

5. **Should Brickognize classification become a bounded async queue (finite concurrency, no daemon thread per piece)?** This needs an architectural decision on concurrency model.

6. **Is the `IRL.__dict__` mutation pattern (`_home_hardware()`) acceptable in the new architecture, or will the IRL become immutable and recreated fresh on each home cycle?** The current approach is fragile with any reference-holding subsystem.

7. **Should `LocalStateDB` (SQLite) grow into a proper schema with typed accessors, or remain a key-value JSON blob store?** The current approach is simple but makes migrations manual and validation impossible.

8. **What is the intended backpressure model for C4 → Distribution?** The `admission.py` gate blocks C3 but there is no back-pressure in the other direction (Distribution telling C4 to slow down). Is the design intent that C4 is always small enough to buffer internally?

9. **Is `PieceHistoryBuffer` with on-disk persistence still needed, or is the Hive upload pipeline the canonical persistence layer?** The two overlap in purpose.

10. **Should the `AuxiliaryDetectionThread` (Gemini/sample scheduling) be merged into the per-role `FeederAnalysisThread`, or remain a single shared background thread?** Currently one thread serves all roles sequentially; under high camera count this is a bottleneck.

---

## Essential Files Reference

The files below are the minimum set required to understand the runtime deeply:

- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/main.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/coordinator.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/sorter_controller.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/server/shared_state.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/vision/vision_manager.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/vision/camera_service.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/vision/detection_registry.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/vision/tracking/__init__.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/vision/tracking/polar_tracker.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/vision/tracking/handoff.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/feeder/feeding.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/feeder/analysis.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/feeder/admission.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/feeder/strategies/c1_jam_recovery.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/channels/c3_precise.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/shared_variables.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/bus/tick_bus.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/classification_channel/running.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/classification_channel/zone_manager.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/piece_transport.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/machine_runtime/base.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/machine_setup.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/global_config.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/defs/consts.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/runtime_stats.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/classification/brickognize.py`
- `/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/local_state.py`

---

## Verification

Spot-check results against cited files on branch `sorthive`, 2026-04-22:

- **Claim 1 — `vision_manager.py` ~2800-line god class:** partial — file is actually **4963 lines** (`vision/vision_manager.py`), considerably larger than the report states. God-class characterization stands; scale understated.
- **Claim 2 — `server/shared_state.py` has 25+ mutable module-level globals:** verified — top-level mutable assignments include `active_connections`, `server_loop`, `runtime_vars`, `command_queue`, `controller_ref`, `gc_ref`, `aruco_manager`, `vision_manager`, `camera_service`, `pulse_locks`, `camera_device_preview_overrides`, `camera_calibration_tasks`, `camera_calibration_tasks_lock`, `runtime_stats_snapshot`, `system_status_snapshot`, `sorter_state_snapshot`, `cameras_config_snapshot`, `sorting_profile_status_snapshot`, `hardware_state`, `hardware_error`, `hardware_homing_step`, `_hardware_start_fn`, `_hardware_initialize_fn`, `_hardware_reset_fn`, `hardware_runtime_irl`, `hardware_worker_thread`, `hardware_lifecycle_lock` — 27 mutable globals before the constants block (`shared_state.py:25-53`).
- **Claim 3 — `MAX_CLASSIFICATION_CHANNEL_DETECTION_CAP = 3` + call-site:** verified — `admission.py:18` defines the constant as `3`; `feeding.py:11` imports `classification_channel_admission_blocked as _classification_channel_admission_blocked` and calls it at `feeding.py:377`.
- **Claim 4 — Brickognize unbounded daemon threads:** verified — `brickognize.py:35-40` constructs `threading.Thread(target=_doClassify, …, daemon=True)` and calls `.start()`. No semaphore, no queue, no concurrency limiter anywhere in the module; `ANY_COLOR`, `FILTER_CATEGORIES`, `API_TIMEOUT_S` are the only module-level knobs.
- **Claim 5 — `_home_hardware()` uses `irl.__dict__.clear(); irl.__dict__.update(...)`:** verified — `main.py:261-265` inside `_replace_irl`:
  ```
  with controller_lock:
      irl.__dict__.clear()
      irl.__dict__.update(next_irl.__dict__)
  ```
  (Minor note: the literal pattern lives inside `_replace_irl`, which is called by `_home_hardware()` — the claim is accurate.)
- **Claim 6 — Subsystems import from `server.shared_state`:** verified — two files:
  - `subsystems/feeder/feeding.py:3` — `import server.shared_state as shared_state`
  - `subsystems/distribution/positioning.py:4` — `import server.shared_state as shared_state`
  
  (Report also mentions `subsystems/distribution/sending.py` importing `server.set_progress_sync` — that is a separate server-layer import, not counted here.)
