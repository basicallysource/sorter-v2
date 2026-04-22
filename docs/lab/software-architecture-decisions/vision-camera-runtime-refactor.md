---
title: Vision and camera runtime refactor concept
type: explanation
audience: contributor planning backend refactors
applies_to: sorter 2.x
owner: sorter
last_verified: 2026-04-22
section: lab
slug: lab-vision-camera-runtime-refactor
kicker: Lab - Refactor Concept
lede: A practical target architecture for shrinking the VisionManager and camera router into small, explicit, agent-friendly modules without losing the current runtime behavior.
permalink: /lab/vision-camera-runtime-refactor/
---

## The question

How should Sorter V2 refactor the current vision and camera backend so that:

- the public runtime behavior stays stable,
- `vision_manager.py` and `server/routers/cameras.py` stop growing as god files,
- the code still follows KISS and the Zen of Python,
- and the result is easier for both humans and LLM agents to read, change, and test?

## Why this matters now

The current backend already contains good low-level modularization:

- `vision/camera_service.py`
- `vision/camera_feed.py`
- `vision/camera_device.py`
- `vision/tracking/*`
- `vision/overlays/*`
- `server/camera_calibration.py`
- `server/camera_preview_hub.py`

But two high-level files still accumulate unrelated responsibilities:

- `software/sorter/backend/vision/vision_manager.py`
- `software/sorter/backend/server/routers/cameras.py`

That is painful for normal maintenance, and even more painful under agent-assisted coding:

- large files exceed "one-pass" comprehension,
- unrelated changes collide in the same file,
- context windows get spent on navigation instead of reasoning,
- and subtle ownership bugs appear because the same behavior is reachable from several places.

This proposal treats "agent-friendly modularity" as a practical extension of the Zen of Python, not as a replacement for it.

## Design principles

### 1. Keep the public API simple

`VisionManager` stays as the stable facade used by subsystems, routers, and tests.

We do not force the whole codebase to learn five new objects at once. We move implementation behind the facade first.

### 2. One owner per concern

Each runtime concern should have one obvious owner:

| Concern | Owner |
|---|---|
| Camera device lifecycle, feeds, live settings, frame encoding | `CameraService` |
| Vision runtime lifecycle and public facade | `VisionManager` |
| Channel and chamber geometry | `VisionGeometry` |
| Classification chamber detection and crops | `ClassificationRuntime` |
| Feeder and carousel detection | `FeederRuntime` |
| Track state and history views | `TrackingRuntime` |
| Artifact side effects: burst capture, segment archival, teacher capture | `CaptureArtifactsRuntime` |
| Camera API persistence and calibration orchestration | `server/camera/*` modules |

If a concern has two owners, the architecture is already drifting.

### 3. Flat over clever

Prefer a handful of top-level modules with explicit names over a deep package tree.

Good:

```text
vision/
  geometry.py
  classification_runtime.py
  feeder_runtime.py
  tracking_runtime.py
  capture_artifacts.py
```

Avoid:

```text
vision/
  services/
    runtime/
      implementations/
        classification/
          manager.py
```

### 4. Small enough to understand in one pass

The repo should optimize for local reasoning, not just abstract cleanliness.

Working limits:

- 150 to 400 lines: healthy default size
- 400 to 700 lines: acceptable if the module has one clear job
- above 700 lines: review whether the file has more than one reason to change
- above 1000 lines: refactor expected unless there is a very strong reason not to

These are not style-police numbers. They are maintenance thresholds.

### 5. Stateful things get classes, pure logic stays as functions

Do not create a `*Service` class just because the code moved.

Use a class when the module owns:

- caches,
- worker threads,
- lifecycle,
- mutable runtime state,
- or external dependencies that should be injected.

Use module functions when the code is:

- pure transformation,
- geometry math,
- config parsing,
- formatting,
- or a single-shot helper.

### 6. Explicit dependencies over hidden globals

`shared_state` remains as an integration seam during migration, but new implementation logic should not reach into it from deep inside helper modules.

Boundary modules may read `shared_state`:

- app bootstrap,
- top-level routers,
- top-level API helpers.

Deep runtime modules should receive collaborators explicitly.

### 7. Practicality beats purity

This is an incremental refactor plan. No big-bang rewrite, no event bus, no abstract factory layer, no generic "service container".

## Non-goals

This proposal does not try to:

- redesign the sorter state machines,
- replace `shared_state` in one shot,
- introduce dependency injection frameworks,
- rename every public method,
- or collapse all camera and vision behavior into a single new abstraction.

The goal is clarity, not novelty.

## Target architecture

## Runtime shape

At the end of the refactor, the runtime should look like this:

```python
class VisionManager:
    def __init__(self, irl_config, gc, irl, camera_service):
        self.cameras = camera_service
        self.geometry = VisionGeometry(...)
        self.classification = ClassificationRuntime(...)
        self.feeder = FeederRuntime(...)
        self.tracking = TrackingRuntime(...)
        self.artifacts = CaptureArtifactsRuntime(...)
        self.overlays = OverlayRegistry(...)
```

`VisionManager` remains the object that other code talks to, but most methods become thin delegations.

## Proposed vision modules

### `vision/vision_manager.py`

Purpose:

- construct collaborators,
- start and stop them in the correct order,
- expose the existing facade methods,
- keep compatibility for the rest of the app.

Should own:

- high-level lifecycle,
- public facade methods,
- minimal wiring state.

Should not own:

- geometry math,
- archive persistence implementation,
- burst implementation details,
- camera crop code,
- detection algorithm internals,
- tracker cache internals.

### `vision/geometry.py`

Purpose:

- load and normalize polygons,
- scale masks to frame size,
- crop channel and chamber regions,
- manage handoff-zone geometry,
- provide geometry answers to other runtimes.

Owns:

- channel polygons,
- channel masks,
- channel angles,
- classification masks,
- polygon resolution metadata,
- carousel polygon,
- handoff-zone geometry derived from saved polygons.

Public examples:

- `reload_polygons()`
- `channel_region_crop(role, frame)`
- `carousel_region_crop(frame)`
- `classification_zone_bbox(cam, frame)`
- `classification_zone_crop(cam, frame)`
- `feeder_track_geometry(role)`

### `vision/classification_runtime.py`

Purpose:

- run and cache classification-chamber detection,
- manage baseline-based and dynamic algorithms,
- expose chamber bboxes, candidates, and crops,
- generate classification debug payloads.

Owns:

- classification heatmaps,
- classification analysis threads,
- classification detection cache,
- algorithm selection for the classification scope,
- chamber sample and crop logic.

Public examples:

- `load_baseline()`
- `get_candidates(cam, force=False, frame=None)`
- `get_combined_bbox(cam, force=False, frame=None)`
- `capture_fresh_frames(timeout_s=1.0)`
- `get_crops(...)`
- `debug_detection(cam, include_capture=False)`

### `vision/feeder_runtime.py`

Purpose:

- manage feeder and carousel detection pipelines,
- own dynamic and baseline detector selection,
- filter detections to channel geometry,
- expose feeder- and carousel-level debug payloads.

Owns:

- MOG2 detectors,
- feeder analysis threads,
- carousel heatmap,
- feeder and carousel dynamic detection caches,
- algorithm selection for feeder and carousel scopes,
- sample-collection flags.

Public examples:

- `init_detection(manual_feed_mode=False)`
- `get_feeder_detection(role, force=False)`
- `get_carousel_detection(force=False)`
- `feeder_detection_availability()`
- `capture_carousel_baseline()`
- `debug_feeder_detection(role, include_capture=False)`
- `debug_carousel_detection(include_capture=False)`

### `vision/tracking_runtime.py`

Purpose:

- own live tracker state,
- update trackers from detector results,
- expose live tracks, geometry, previews, and history views,
- keep tracker-specific policies in one place.

Owns:

- tracker instances,
- track caches,
- piece history buffer,
- live preview helpers,
- confirmation / ghost filtering policy,
- global-id and history query behavior.

Public examples:

- `set_active(active)`
- `update_from_detection(role, detection, timestamp, frame_bgr=None)`
- `get_tracks(role)`
- `get_latest_track(role, max_age_s=1.0)`
- `get_track_history(limit=None, min_sectors=0)`
- `get_track_history_detail(global_id)`
- `get_track_preview(global_id)`
- `mark_carousel_pending_drop(global_id)`

### `vision/capture_artifacts.py`

Purpose:

- own artifact-producing side effects that hang off live vision behavior.

This module intentionally groups three related behaviors:

- segment archival,
- burst capture,
- auxiliary teacher capture.

They all consume live vision data and write secondary artifacts, but they are not part of core detection or core tracking.

Owns:

- burst store,
- burst timers,
- piece transport binding for archival,
- teacher-capture queue,
- auxiliary worker loop,
- OpenRouter throttle coordination for teacher captures.

Public examples:

- `attach_piece_transport(transport)`
- `archive_segment(tracked_global_id, segment)`
- `capture_burst(global_id, pre_count=30, post_count=30, post_window_s=2.0)`
- `get_burst_frames(global_id)`
- `schedule_feeder_teacher_capture_after_move(...)`
- `schedule_carousel_teacher_capture_on_classic_trigger(...)`
- `start()`
- `stop()`

### `vision/overlay_registry.py`

Purpose:

- own feed overlay registration.

This should stay small and explicit. It reads state from the other runtimes and registers overlays on `CameraFeed` objects.

It does not own detection, tracking, or geometry itself.

## Camera API shape

The camera HTTP layer should split by concern, not by "whatever happened to land in `cameras.py`".

## Proposed camera modules

```text
server/camera/
  config.py
  feeds.py
  settings.py
  calibration.py
  calibration_tasks.py
```

```text
server/routers/
  cameras.py
  camera_config.py
  camera_feeds.py
  camera_settings.py
  camera_calibration.py
```

### `server/camera/config.py`

Purpose:

- camera role normalization,
- TOML read and write helpers for assignments,
- source lookup,
- shared config-table helpers.

Owns:

- `_camera_source_for_role`-style logic,
- role alias resolution,
- persisted assignment and capture-mode writes.

### `server/camera/feeds.py`

Purpose:

- camera discovery aggregation,
- direct preview and feed helpers,
- dashboard crop specification and application,
- histogram frame access helpers.

Owns:

- USB and network list helpers,
- crop-spec logic for live feeds,
- lightweight frame grab helpers used by the HTTP layer.

### `server/camera/settings.py`

Purpose:

- picture settings,
- device settings,
- color profile persistence,
- live-apply helpers against `CameraService`.

Important rule:

Routers should not bounce between `VisionManager` and `CameraService` for the same concern. Camera hardware state should flow through `CameraService`, with `VisionManager` only used when a vision-specific interpretation is required.

### `server/camera/calibration.py`

Purpose:

- calibration orchestration only.

Owns:

- task creation and progress updates,
- USB vs Android calibration flows,
- histogram and LLM-guided calibration orchestration,
- gallery management,
- color-profile save/apply coordination.

This is the single biggest extraction opportunity from the current camera router.

### `server/camera/calibration_tasks.py`

Purpose:

- replace ad-hoc shared task dictionaries with a small focused task store.

Can remain simple:

- a lock,
- a dict,
- `create`, `update`, `get`, `cleanup`.

No framework needed.

## Router shape

`server/routers/cameras.py` should become a compatibility aggregator:

```python
router = APIRouter()
router.include_router(camera_config_router)
router.include_router(camera_feeds_router)
router.include_router(camera_settings_router)
router.include_router(camera_calibration_router)
```

This keeps `server/api.py` almost unchanged while making the camera HTTP layer locally understandable.

## Ownership rules

The refactor should follow these hard rules.

### Rule 1: camera hardware belongs to `CameraService`

If code needs:

- a live device,
- a feed,
- a capture thread,
- device settings,
- picture settings,
- capture mode,
- or color profile application,

the first stop should be `CameraService`.

### Rule 2: geometry belongs to `VisionGeometry`

If code asks:

- where is the zone,
- how do I crop this role,
- which points define this polygon,
- which bbox is valid for this channel,

the first stop should be `VisionGeometry`.

### Rule 3: detection belongs to scope runtimes

Classification chamber detection should not live in the same implementation block as feeder/carousel detection.

They may share helpers, but not one mixed owner.

### Rule 4: artifact side effects do not live in core detection modules

Burst capture, archival, and teacher capture are all useful, but they are secondary behaviors. They should not make detection modules harder to understand.

### Rule 5: routers speak HTTP, not OpenCV

Routers may:

- validate payloads,
- call a service/runtime,
- translate exceptions into HTTP responses,
- shape response payloads.

Routers should not contain:

- frame-processing pipelines,
- task state machines,
- device control heuristics,
- or large image-analysis algorithms.

## Working style for LLM and agent coding

This refactor adds one explicit project rule:

**Optimize for local reasoning.**

That means:

- new features extend a nearby module instead of the biggest file,
- most edits should stay inside one or two modules,
- a reader should be able to understand a file without scanning 4000 surrounding lines,
- and tests should be able to stub one owner instead of half the system.

The practical reading model is:

- one file,
- one clear responsibility,
- one obvious owner,
- one small change radius.

## Migration plan

The work should be done in phases, each leaving the app runnable.

## Phase 0: guardrails first

Before moving major logic:

- add contract tests around current `VisionManager` facade methods,
- add route tests around the current camera endpoints,
- document the ownership rules in contributor docs.

Done when:

- we can change internals without guessing whether behavior drifted.

## Phase 1: extract camera calibration

Move the large calibration implementation out of `server/routers/cameras.py` into:

- `server/camera/calibration.py`
- `server/camera/calibration_tasks.py`
- `server/routers/camera_calibration.py`

Why first:

- biggest immediate file-size reduction,
- isolated concern,
- low impact on the rest of the runtime.

Done when:

- calibration endpoints are still identical,
- router code is mostly HTTP translation,
- task storage no longer lives as a raw dict in `shared_state`.

## Phase 2: extract capture artifacts from `VisionManager`

Move:

- segment archival,
- burst capture,
- auxiliary teacher capture.

Why second:

- large and mostly self-contained,
- side-effect heavy,
- reduces noise around the core detection and tracking logic.

Done when:

- `VisionManager` delegates these behaviors to one collaborator,
- existing methods stay callable through the facade,
- tests for burst and archival target the new runtime directly.

## Phase 3: extract geometry

Move all polygon, mask, crop, and zone geometry into `VisionGeometry`.

Why third:

- both classification and feeder paths depend on geometry,
- clean geometry ownership makes later detection and tracking splits simpler.

Done when:

- no detection runtime owns polygon persistence details,
- crop logic is centralized,
- handoff-zone geometry no longer sits in the main facade.

## Phase 4: extract classification runtime

Move:

- classification detection config and caches,
- baseline loading,
- top/bottom chamber detection,
- chamber crop and sample helpers,
- classification debug payloads.

Done when:

- classification code lives in one place,
- `VisionManager` methods mostly delegate,
- chamber-facing subsystems can be tested against `ClassificationRuntime` directly.

## Phase 5: extract feeder runtime and tracking runtime

Move feeder/carousel detection into `FeederRuntime`, then tracker state into `TrackingRuntime`.

Why in this order:

- tracker logic consumes feeder/carousel outputs,
- detection ownership should settle before tracker ownership.

Done when:

- track updates no longer share a class with detector and crop implementation,
- live-track queries and history views come from `TrackingRuntime`,
- feeder and carousel detection caches sit outside `VisionManager`.

## Phase 6: slim the camera router into an aggregator

Create:

- `server/routers/camera_config.py`
- `server/routers/camera_feeds.py`
- `server/routers/camera_settings.py`
- `server/routers/camera_calibration.py`

Keep:

- `server/routers/cameras.py` as an include-only shim.

Done when:

- the main camera router is small and boring,
- each camera route file matches one operator-facing concern.

## Phase 7: reduce global coupling

Only after the above:

- narrow `shared_state` usage,
- move camera-calibration task state out of shared globals,
- consider a small backend runtime object for bootstrap-owned references.

Do not do this earlier unless another phase truly requires it.

## Testing strategy

The refactor should change where logic lives, not how the machine behaves.

Test layers:

| Layer | What to verify |
|---|---|
| Facade contract tests | Existing `VisionManager` methods still behave the same |
| Runtime unit tests | Geometry, classification, feeder, tracking, artifacts each test their own logic directly |
| Router tests | Endpoints keep the same payload shape and status codes |
| Integration smoke tests | Startup, camera feed access, calibration task lifecycle, burst capture flow |

High-value contract targets:

- `captureClassificationSample`
- `getClassificationCombinedBbox`
- `getFeederTracks`
- `getFeederTrackHistoryDetail`
- `captureBurst`
- `setDeviceSettingsForRole`
- `setColorProfileForRole`

## Acceptance criteria

The refactor is successful when these statements become true:

- `vision_manager.py` is primarily lifecycle and delegation, not implementation.
- `server/routers/cameras.py` is a thin aggregator.
- Camera calibration lives outside the router.
- Geometry has one owner.
- Classification and feeder/carousel detection do not share one god module.
- Artifact side effects do not sit inside core detection flows.
- Most new features have an obvious target module.
- A contributor or agent can change one runtime concern without reading several thousand lines first.

Suggested size targets:

| File | Target size |
|---|---|
| `vision/vision_manager.py` | under 700 lines |
| `server/routers/cameras.py` | under 300 lines |
| Each new runtime module | usually 200 to 600 lines |

## Anti-patterns to avoid during the refactor

- Replacing one god file with a god package.
- Creating abstract base classes before there are multiple real implementations.
- Moving code without changing ownership, then calling that "modular".
- Letting routers call both `VisionManager` and `CameraService` for the same hardware concern.
- Introducing a dependency injection framework for a handful of explicit collaborators.
- Renaming everything at once and destroying diff readability.

## Final recommendation

The right target is not "many services". The right target is:

- one stable facade,
- a few explicit runtime owners,
- small and locally understandable files,
- simple module names,
- and HTTP routers that only do HTTP.

That gives the project the benefits of the Zen of Python and KISS while also addressing the practical reality of agent-assisted development: code must be easy to reason about in bounded context.
