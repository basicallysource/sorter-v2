---
title: LegoSorter Runtime Rebuild — Design Proposal
scope: software/sorter/backend/
branch: sorthive (no separate rebuild branch)
date: 2026-04-22
status: approved (plan), open decisions remain in §10
source: architect-runtime v1 output with Marc's corrections applied
canonical_vision: runtime-architecture.html
related:
  - runtime-architecture.html (canonical visual vision — takes precedence on structure)
  - docs/lab/runtime-current-state-map.md (IST-state, LEGACY reference only)
  - ~/.claude/plans/der-setup-prozess-wird-eine-eager-finch.md (master plan)
---

# LegoSorter Runtime Rebuild — Design Proposal

*Target location: `docs/lab/runtime-rebuild-design.md`*
*Author: lead architect (Claude Opus 4.7) · Date: 2026-04-22 · Working branch: `sorthive` (no separate rebuild branch)*

---

## 0. TL;DR

- One Python process, **hybrid execution**: a single main-loop tick (20 ms) drives `Runtime.step()` state machines; **per-feed perception threads** run detection/tracking off-tick (OpenCV releases the GIL); **bounded `ThreadPoolExecutor` (max 4)** handles Brickognize HTTPS; **blocking stepper calls (C1 jam recovery up to 2.5 s) move off the tick onto the owning runtime's own worker thread.** No asyncio inside the runtime — asyncio stays in FastAPI only.
- Hot path is **explicit typed dataflow**: `Camera → Feed → Zone → Detector → Tracker → FilterChain → RuntimeInbox`. No globals, no WS coupling.
- **Pull-based backpressure** modeled as **bounded capacity handoff slots** (`CapacitySlot` wrapping `threading.Semaphore`). Each Runtime publishes `available_slots()` upstream; upstream only *arms* the next release when a slot is claimable. C3→C4 admission cap collapses into the general model — no more special-case.
- **Five Runtimes**: `RuntimeC1`, `RuntimeC2`, `RuntimeC3` (both C2 and C3 are Separation semantics), `RuntimeC4` (Classification; holds a `Classifier` strategy), `RuntimeDistributor` (consults a `RulesEngine` for bin mapping). Internals may be state-machine-based — public contract is `Runtime`.
- **Strategy registry** kills every `if algorithm == "mog2"` branch. Detectors, Trackers, Filters, Calibration, **Classifier**, **RulesEngine**, and Runtime behaviors are all `@register_strategy("key")` plugins with typed Protocols, loaded from config.
- **Camera → Feed is 1:1 by design.** Legacy rigs with 1 camera producing multiple feeds are wrapped via a `SplitFeed` compat shim — explicit Legacy, not first-class.
- **Event bus (kept, rewired)**: existing `TickBus` evolves into `EventBus` — carries lifecycle/telemetry/UI, never hot-path frames or detections. `SharedVariables` dual-path is deleted; the bus is the *only* cross-cutting channel.
- **`shared_state.py` is deleted.** Replaced with a `RuntimeContext` dataclass passed by constructor (DI container pattern, no globals).
- **Migration on the existing `sorthive` branch**, 6 phases. Cutover is one PR (`sorthive → main`) that deletes the old runtime tree when the Minimum Viable Sorter (full sort cycle on real machine) lands. A marker commit on `sorthive` signals "pre-architecture" before scaffolding begins; `main` is untouched until cutover.

---

## 0.5 Rebuild Approach: Two-Track Strategy

The target is a **4-layer × 5-column grid**: **L1 Input** (cameras → feeds → zones), **L2 Perception** (detector → tracker → filter), **L3 Runtimes** (C1, C2, C3, C4, Distributor), **L4 Cross-Cutting EventBus**. Pieces flow left-to-right through typed `PieceHandoff` messages; capacity flows right-to-left through `ReadySignal` grants. **C1 and Distributor are blind** — no camera, no perception. The canonical visual source is `runtime-architecture.html`; this doc is the engineering companion (contracts, phases, effort).

Not every part of the backend is equally broken. The rebuild philosophy is **per-layer**:

**Track A — Perception layer: carve out and port carefully ("carve-and-rewire").**
The algorithmic substance (MOG2 detection, diff/heatmap, polar tracker, handoff, burst capture, Brickognize client, zone/region providers, calibration) works well in its core — the problem is the *wiring*, currently trapped in the 4963-line `vision_manager.py` god-class. For this layer: **port algorithms conservatively, don't reinvent them**; route them through the new contracts into a clean `perception/` tree. Each module ≤300 LoC, clear Protocol interfaces, no coupling to `shared_state`.

**Track B — Runtime layer: green-field, from scratch.**
How each carousel / channel behaves internally, how they hand off pieces to each other, how backpressure flows, how error/jam/recovery states are orchestrated — this is **chaos right now** (Marc's word: "komplette Grütze"). Dual classification pipelines, blocking stepper calls on the main loop, inverted imports into `shared_state`, a single special-case admission gate instead of systemic backpressure. For this layer: **do NOT cut and reshape the existing code**; design the Runtimes (`RuntimeC1/C2/C3/C4/Distributor`) and the Orchestrator/Coupling model **from zero** on top of the new contracts and Marc's pull-backpressure model. We read the existing `coordinator.py`, `feeding.py`, `classification_channel/state_machine.py`, `distribution/state_machine.py` only as behavioral reference ("this is how the hardware sequencing factually works"), never as implementation templates.

| Layer | Approach | Code stance |
|---|---|---|
| Perception (Detector/Tracker/Filter/Calibration/Classifier) | Track A — Port | Keep algorithms, rewire with new contracts |
| Runtime orchestration (Runtimes, Slots, state machines, piece lifecycle, handoffs) | Track B — Green-field | From zero, old code only read as reference |
| Hardware layer (`hardware/`, `irl/`) | Track A — Light port | Stepper/servo HAL kept; `_home_hardware()` `__dict__` trick replaced by immutable IRL |
| Event bus / config / persistence | Hybrid | Extend `tick_bus.py` (small), new Pydantic config, SQLite wrapper kept |

---

## 1. Directory Layout

New top-level package: `software/sorter/backend/rt/` ("runtime, rewritten"). Old tree stays alongside until cutover. No import cross-talk between `backend/*` (old) and `backend/rt/*` (new). Gateway module `rt/__init__.py` exports the public builder. `main.py` gets a `--runtime=rt` flag during migration; default flips in the cutover PR.

```
software/sorter/backend/rt/
  __init__.py                    # build_runtime(config) — entry
  context.py                     # RuntimeContext (replaces shared_state globals)
  config/
    __init__.py
    schema.py                    # Pydantic config models (FeedConfig, RuntimeConfig, PipelineConfig)
    loader.py                    # TOML + SQLite merge, validation, hot-reload boundaries
  contracts/
    __init__.py
    feed.py                      # Feed, FeedFrame, Zone
    detection.py                 # Detector, Detection
    tracking.py                  # Tracker, Track
    filters.py                   # Filter, FilterChain
    classification.py            # Classifier, ClassifierResult
    rules.py                     # RulesEngine, BinDecision
    calibration.py               # CalibrationStrategy, PictureSettings
    runtime.py                   # Runtime ABC, RuntimeInbox, CapacitySlot
    registry.py                  # StrategyRegistry, @register_strategy
    events.py                    # EventBus protocol, Event dataclasses
  classification/
    __init__.py
    brickognize.py               # Brickognize HTTP client (ported from backend/classification/)
    brickognize_types.py
  perception/                    # was vision_manager.py
    pipeline.py                  # PerceptionPipeline (one per Feed): detect→track→filter
    pipeline_runner.py           # PerceptionRunner (thread per feed)
    feeds.py                     # CameraFeed, SyntheticFeed
    zones.py                     # RectZone, PolarZone, PolygonZone
    detectors/
      mog2.py                    # port of mog2_channel_detector
      heatmap_diff.py            # port of heatmap_diff.py
      gemini_sam.py              # port of gemini_sam_detector
      hive_onnx.py               # port of ml.create_processor wrapper
      baseline_diff.py
    trackers/
      polar.py                   # port of polar_tracker.py (unchanged algorithm)
      bytetrack.py               # kept only if Marc opts in (see §10)
    filters/
      size.py
      ghost.py                   # the "confirmed_real" whitelist as a filter
      class_id.py
    classifiers/
      __init__.py
      brickognize_classifier.py  # Brickognize-backed Classifier (registered as "brickognize")
      # future: local_onnx_classifier.py, huggingface_classifier.py, etc.
    calibration/
      reverse_pulse.py           # port of calibrateFeederChannels
      aruco_polygons.py          # port of aruco_region_provider
      handdrawn.py               # port of handdrawn_region_provider
  rules/
    __init__.py
    lego_rules.py                # LegoRulesEngine — ports DistributionLayout + SortingProfile
    # future: coin_rules.py, screw_rules.py, etc.
  runtimes/
    base.py                      # BaseRuntime mixin helpers (tick, state_transition)
    c1.py                        # RuntimeC1 (Bulk seed shuttle)
    c2.py                        # RuntimeC2 (Separation seed shuttle)
    c3.py                        # RuntimeC3 (Separation seed shuttle)
    c4.py                        # RuntimeC4 (Classification; owns a Classifier strategy)
    distributor.py               # RuntimeDistributor (consults RulesEngine + chute)
    _states/                     # Internal state machines (private)
      c1_states.py
      c2_states.py
      c3_states.py
      c4_states.py
      distributor_states.py
  coupling/
    slots.py                     # CapacitySlot, HandoffSlot
    orchestrator.py              # Orchestrator: builds runtimes, wires slots, drives tick
  hardware/                      # Thin port of backend/hardware/ — no rewrite
    sorter_interface.py          # moved, not rewritten
    bus.py
    cobs.py
    waveshare_bus_service.py
    macos_uvc_controls.py
  irl/                           # Thin port — immutable IRLInterface (no __dict__ trick)
    interface.py                 # Frozen dataclass
    loader.py
    bin_layout.py
  events/
    bus.py                       # InProcessEventBus (extends/replaces TickBus)
    topics.py                    # Typed topic names + payload types
    sinks/
      ws_broadcaster.py          # Subscribes to bus, pushes to FastAPI WS loop
      metrics_collector.py       # Subscribes to bus, updates RuntimeStatsCollector
      sample_capture.py          # Subscribes to drop_zone_burst events
      hive_upload.py             # Subscribes to piece_classified events
  server/                        # FastAPI, mostly unchanged
    api.py
    routers/...                  # Kept; shared_state.py DELETED
  persistence/
    sqlite.py                    # Thin wrapper over local_state.py
    piece_dossier.py             # typed piece dossier accessors
  defs/                          # KEEP AS-IS (WS event Pydantic models)
    events.py
    known_object.py
    channel.py
```

**Rationale:**
- `rt/` top-level keeps old and new side-by-side without import soup. Cutover PR removes old tree.
- `contracts/` is the **one** place to look for a Protocol/ABC. Single source of truth for type discovery.
- `perception/` replaces the 4963-line `vision_manager.py`. Each detector/tracker/filter/classifier is its own file, ≤300 LoC target.
- `rules/` isolates domain logic (which part → which bin). Swapping domains (coins, screws) = new rules engine, no runtime changes.
- `runtimes/_states/` underscore is deliberate — state machines are internal, the `Runtime` contract is public.
- No file targets >600 LoC. Decomposition is the point.

---

## 2. Core Contracts

All types live in `rt/contracts/`. Dataclasses + `typing.Protocol` (not ABC) where duck-typing is fine; ABC when lifecycle hooks are mandatory.

### 2.1 Feed & Zone

```python
# rt/contracts/feed.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Literal
import numpy as np

FeedPurpose = Literal["c2_feed", "c3_feed", "c4_feed", "aux"]
# Note: no c1_feed / distributor_feed — C1 and Distributor are blind (no perception).

@dataclass(frozen=True, slots=True)
class FeedFrame:
    feed_id: str
    camera_id: str
    raw: np.ndarray            # BGR
    gray: np.ndarray | None    # precomputed if cheap
    timestamp: float           # wall time
    monotonic_ts: float
    frame_seq: int

class Feed(Protocol):
    feed_id: str
    purpose: FeedPurpose
    camera_id: str
    def latest(self) -> FeedFrame | None: ...
    def fps(self) -> float: ...
```

```python
# rt/contracts/feed.py (cont.)
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True, slots=True)
class RectZone:
    x: int; y: int; w: int; h: int

@dataclass(frozen=True, slots=True)
class PolygonZone:
    vertices: tuple[tuple[int, int], ...]

@dataclass(frozen=True, slots=True)
class PolarZone:
    center_xy: tuple[float, float]
    r_inner: float
    r_outer: float
    theta_start_rad: float
    theta_end_rad: float

Zone = RectZone | PolygonZone | PolarZone
```

### 2.2 Detector

```python
# rt/contracts/detection.py
from dataclasses import dataclass, field
from typing import Protocol, Any
from .feed import FeedFrame, Zone

@dataclass(frozen=True, slots=True)
class Detection:
    bbox_xyxy: tuple[int, int, int, int]
    score: float
    class_id: str | None = None
    mask: Any | None = None     # np.ndarray | None — optional
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class DetectionBatch:
    feed_id: str
    frame_seq: int
    timestamp: float
    detections: tuple[Detection, ...]
    algorithm: str              # registry key used
    latency_ms: float

class Detector(Protocol):
    key: str                    # registry key, e.g. "mog2", "hive:slug"

    def requires(self) -> frozenset[str]:  # {"gray", "raw", "baseline", "background"}
        ...

    def detect(self, frame: FeedFrame, zone: Zone) -> DetectionBatch: ...

    # Lifecycle
    def reset(self) -> None: ...
    def stop(self) -> None: ...
```

### 2.3 Tracker

```python
# rt/contracts/tracking.py
from dataclasses import dataclass, field
from typing import Protocol

@dataclass(frozen=True, slots=True)
class Track:
    track_id: int                         # stable within tracker lifetime
    global_id: int | None                 # stable across handoffs
    piece_uuid: str | None                # minted early on C3 (port of MIN_C3_HITS_FOR_PIECE_UUID)
    bbox_xyxy: tuple[int, int, int, int]
    score: float
    confirmed_real: bool
    angle_rad: float | None               # polar, if PolarZone
    radius_px: float | None
    hit_count: int
    first_seen_ts: float
    last_seen_ts: float

@dataclass(frozen=True, slots=True)
class TrackBatch:
    feed_id: str
    frame_seq: int
    timestamp: float
    tracks: tuple[Track, ...]
    lost_track_ids: tuple[int, ...]       # tracks that expired this tick

class Tracker(Protocol):
    key: str
    def update(self, detections: DetectionBatch, frame: FeedFrame) -> TrackBatch: ...
    def live_global_ids(self) -> set[int]: ...
    def reset(self) -> None: ...
```

### 2.4 Filter

```python
# rt/contracts/filters.py
from typing import Protocol
from .tracking import TrackBatch
from .feed import FeedFrame

class Filter(Protocol):
    key: str
    def apply(self, tracks: TrackBatch, frame: FeedFrame) -> TrackBatch: ...

class FilterChain:
    """Ordered composition of filters. Built from config, immutable."""
    def __init__(self, filters: tuple[Filter, ...]) -> None: ...
    def apply(self, tracks: TrackBatch, frame: FeedFrame) -> TrackBatch: ...
```

Filter examples: `SizeFilter(min_area_px, max_area_px)`, `GhostFilter(confirmed_real_only=True)`, `ClassIdFilter(allowed={"lego_brick"})`.

### 2.5 Classifier

```python
# rt/contracts/classification.py
from dataclasses import dataclass, field
from typing import Protocol, Any
from concurrent.futures import Future
from .feed import FeedFrame
from .tracking import Track

@dataclass(frozen=True, slots=True)
class ClassifierResult:
    part_id: str | None         # e.g. "3001"
    color_id: str | None        # e.g. "red"
    category: str | None        # domain-specific category (brick/plate/technic/...)
    confidence: float           # 0..1
    algorithm: str              # registry key
    latency_ms: float
    meta: dict[str, Any] = field(default_factory=dict)

class Classifier(Protocol):
    key: str                    # registry key, e.g. "brickognize", "local_onnx:screws"

    def classify(self, track: Track, frame: FeedFrame, crop: Any) -> ClassifierResult: ...
    def classify_async(self, track: Track, frame: FeedFrame, crop: Any) -> "Future[ClassifierResult]":
        """Submit for async classification; Runtime holds the Future and awaits it."""
    def reset(self) -> None: ...
    def stop(self) -> None: ...
```

Classifier examples: `BrickognizeClassifier` (wraps the HTTP client + bounded `ThreadPoolExecutor(max_workers=4)`), future `LocalOnnxClassifier` (for coin/screw domains without a cloud round-trip). **Swapping classifiers is a config change, not a code change.** `RuntimeC4` holds a `Classifier` — it does not know what's inside.

### 2.6 Calibration

```python
# rt/contracts/calibration.py
from typing import Protocol
from dataclasses import dataclass
from .feed import Zone

@dataclass(frozen=True, slots=True)
class PictureSettings:
    exposure: int | None
    white_balance: int | None
    focus: int | None
    gain: int | None

class CalibrationStrategy(Protocol):
    key: str
    def compute_zones(self, camera_id: str) -> tuple[Zone, ...]: ...
    def picture_settings(self, camera_id: str) -> PictureSettings | None: ...
    def needs_warmup(self) -> bool: ...
    def run_warmup(self, hw) -> None: ...     # e.g. reverse-pulse calibration
```

### 2.7 Runtime

```python
# rt/contracts/runtime.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol
from .tracking import TrackBatch

@dataclass(frozen=True, slots=True)
class RuntimeInbox:
    """Input surface: what the runtime sees each tick.
    Tracks arrive via the perception thread writing into a thread-safe latest-tracks slot
    (reader never blocks; gets last complete batch)."""
    tracks: TrackBatch | None
    capacity_downstream: int                  # slots downstream currently has

@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    state: str                                # "idle" | "running" | "paused" | "error"
    blocked_reason: str | None
    last_tick_ms: float

class Runtime(ABC):
    """One per hardware component. Pull-driven."""
    runtime_id: str

    @abstractmethod
    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None: ...

    @abstractmethod
    def available_slots(self) -> int:
        """How many pieces can I accept from upstream RIGHT NOW.
        This is the pull-backpressure signal the orchestrator reads."""

    @abstractmethod
    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        """Upstream confirms a handoff just completed."""

    @abstractmethod
    def health(self) -> RuntimeHealth: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
```

### 2.8 Strategy Registry

```python
# rt/contracts/registry.py
from typing import Callable, TypeVar, Generic
from threading import Lock

T = TypeVar("T")

class StrategyRegistry(Generic[T]):
    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._entries: dict[str, Callable[..., T]] = {}
        self._lock = Lock()

    def register(self, key: str, factory: Callable[..., T]) -> None:
        with self._lock:
            if key in self._entries:
                raise ValueError(f"{self._kind} strategy {key!r} already registered")
            self._entries[key] = factory

    def create(self, key: str, **kwargs) -> T:
        try:
            return self._entries[key](**kwargs)
        except KeyError:
            raise LookupError(f"Unknown {self._kind} strategy: {key!r}")

    def keys(self) -> frozenset[str]:
        return frozenset(self._entries)

# Module-level registries. Strategies self-register via import side-effect.
DETECTORS: StrategyRegistry["Detector"] = StrategyRegistry("detector")
TRACKERS: StrategyRegistry["Tracker"] = StrategyRegistry("tracker")
FILTERS: StrategyRegistry["Filter"] = StrategyRegistry("filter")
CLASSIFIERS: StrategyRegistry["Classifier"] = StrategyRegistry("classifier")
CALIBRATIONS: StrategyRegistry["CalibrationStrategy"] = StrategyRegistry("calibration")
RULES_ENGINES: StrategyRegistry["RulesEngine"] = StrategyRegistry("rules_engine")
ADMISSION_STRATEGIES: StrategyRegistry["AdmissionStrategy"] = StrategyRegistry("admission")
EJECTION_TIMING_STRATEGIES: StrategyRegistry["EjectionTimingStrategy"] = StrategyRegistry("ejection_timing")

def register_detector(key: str):
    def deco(cls):
        DETECTORS.register(key, cls)
        return cls
    return deco

def register_classifier(key: str):
    def deco(cls):
        CLASSIFIERS.register(key, cls)
        return cls
    return deco

def register_rules_engine(key: str):
    def deco(cls):
        RULES_ENGINES.register(key, cls)
        return cls
    return deco

def register_admission(key: str):
    def deco(cls):
        ADMISSION_STRATEGIES.register(key, cls)
        return cls
    return deco

def register_ejection_timing(key: str):
    def deco(cls):
        EJECTION_TIMING_STRATEGIES.register(key, cls)
        return cls
    return deco
# (register_tracker, register_filter, register_calibration analogous)
```

Hive ONNX models register dynamically at startup scan time (same code path as `detection_registry._discover_hive_algorithms`, rewritten to call `DETECTORS.register(f"hive:{slug}", factory)`).

### 2.9 Event Bus

```python
# rt/contracts/events.py
from typing import Protocol, Callable, TypeVar, Generic
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Event:
    topic: str
    payload: dict
    source: str
    ts_mono: float

class EventBus(Protocol):
    def publish(self, event: Event) -> None: ...
    def subscribe(self, topic_glob: str, handler: Callable[[Event], None]) -> "Subscription": ...
    def drain(self) -> None: ...  # for tests

class Subscription(Protocol):
    def unsubscribe(self) -> None: ...
```

Implementation lives in `rt/events/bus.py`. Handlers run on a **dedicated event-dispatch thread** with a bounded queue (`maxsize=2048`, drop-oldest for lossy topics). Slow handlers cannot backpressure publishers.

### 2.10 RulesEngine

```python
# rt/contracts/rules.py
from dataclasses import dataclass
from typing import Protocol
from .classification import ClassifierResult

@dataclass(frozen=True, slots=True)
class BinDecision:
    bin_id: str | None          # None = "no bin available, hold or reject"
    category: str | None
    reason: str                 # human-readable: "matched profile X", "default bin", "rejected: unknown part"

class RulesEngine(Protocol):
    key: str                    # registry key, e.g. "lego_default", "coins_v1"

    def decide_bin(
        self,
        classification: ClassifierResult,
        context: dict,          # run-state (current profile, active set, etc.)
    ) -> BinDecision: ...

    def reload(self) -> None:   # hot-reload rules (sorting profile update)
        ...
```

The rules engine is the **explicit home for domain knowledge**: which LEGO part goes into which bin, which sorting profile is active, what the fallback is for unknown parts. Today this logic lives across `DistributionLayout`, `SortingProfile`, and various string-matching helpers. In the rebuild it's one pluggable strategy with a single-method contract. `LegoRulesEngine` ships as the default; a `CoinRulesEngine` or `ScrewRulesEngine` is a new file, not a rewrite.

### 2.11 AdmissionStrategy

```python
# rt/contracts/admission.py
from typing import Protocol
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    allowed: bool
    reason: str               # "zone_cap", "arc_clear", "transport_cap", "health_error", or "ok"

class AdmissionStrategy(Protocol):
    """How a Runtime decides whether to accept an incoming ReadySignal request.
    Collapses what was scattered as the C3→C4 admission gate (raw-detection cap,
    zone-count, arc-clear check, transport-count) into a single pluggable decision."""
    key: str
    def can_admit(self, inbound_piece_hint: dict, runtime_state: dict) -> AdmissionDecision: ...
```

### 2.12 EjectionTimingStrategy

```python
# rt/contracts/ejection.py
from typing import Protocol
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class EjectionTiming:
    pulse_ms: float           # duration of the eject motor pulse
    settle_ms: float          # how long to wait after pulse before declaring "delivered"
    fall_time_ms: float       # minimum hold before accepting next upstream piece

class EjectionTimingStrategy(Protocol):
    """How a Runtime (esp. C3, C4) decides timing of its ejection pulse and
    settle/fall-time windows. Swappable per hardware variant, per seed profile,
    or per experimental tuning run."""
    key: str
    def timing_for(self, piece_context: dict) -> EjectionTiming: ...
```

Both are new explicit plugins carved out of what today lives scattered across `admission.py`, `ejecting.py`, and various hardcoded timing constants. They register into the module-level registries `ADMISSION_STRATEGIES` and `EJECTION_TIMING_STRATEGIES` (extend §2.8) via `@register_admission("key")` / `@register_ejection_timing("key")` decorators analogous to the others.

---

## 3. Hot-Path Dataflow

**Concrete trace of a single frame on the `c3_feed`:**

1. `CaptureThread` (one per camera) reads OpenCV frames at camera FPS (~30) into an atomic `latest_frame: FeedFrame | None`. GIL released during `VideoCapture.read()`. *(Port of `vision/camera.py`; no change.)*

2. `PerceptionRunner(feed_id="c3_feed")` — one dedicated thread per feed, loop period tied to `feed.fps_target` (e.g. 10 Hz for MOG2 feeds, 5 Hz for Hive ONNX). Steps per iteration:
   - Read `feed.latest()` → `FeedFrame`.
   - `detector.detect(frame, zone)` → `DetectionBatch`.
   - `tracker.update(detections, frame)` → `TrackBatch`.
   - `filter_chain.apply(tracks, frame)` → `TrackBatch`.
   - Atomic store into `self._latest_tracks: TrackBatch`.
   - Publish `Event(topic="perception.tracks", ...)` on the bus (for overlays & telemetry; downsampled to 5 Hz).

3. `MainLoop` (thread name `MainThread`) runs at 20 ms:
   - `orchestrator.tick()` — sequential per-runtime.
   - For each `Runtime`: build `RuntimeInbox` with `tracks=perception_runner.get_latest_tracks(feed_id)` and `capacity_downstream=next_runtime.available_slots()`.
   - `runtime.tick(inbox, now_mono)`.
   - Non-blocking: the runtime enqueues commands onto its own `_hw_worker` if they'd block >5 ms (stepper moves, jam recovery). **The main loop never blocks on hardware.**

4. `HardwareWorker` (one per runtime that owns a stepper, daemon thread): consumes `StepperCommand` from a bounded `queue.Queue(maxsize=4)`. Hardware errors surface via `runtime._health` + `EventBus.publish("hardware.error", ...)`.

5. WebSocket broadcast: `WsBroadcaster` subscribes to `frame.*`, `piece.*`, `system.*`, `runtime_stats.*` on the bus. Uses `asyncio.run_coroutine_threadsafe` onto the FastAPI loop (unchanged from today).

**GIL / threads vs. asyncio vs. processes — decision:**

- **Perception threads win.** OpenCV, numpy, ONNX, MOG2, Kalman — all release the GIL for the hot path inside C code. Per-feed threads parallelize well. Measured in practice on the current code (3 analysis threads today at 30 ms cadence without GIL contention).
- **asyncio does not fit the runtime.** The runtime's natural unit is a synchronous tick. Mixing asyncio into hardware control introduces reentrancy and cancellation hazards we don't want. asyncio stays in FastAPI only.
- **Processes only if measured.** Camera drivers and ONNX inference may in the future benefit from separate processes (shared-memory frame handoff), but we do not do this up front. Single process.
- **Classifier concurrency**: lives inside the `Classifier` implementation. `BrickognizeClassifier` ships with `concurrent.futures.ThreadPoolExecutor(max_workers=4)` internally — bounded, queueable, cancelable — replacing the current `threading.Thread(daemon=True)` per-piece footgun (`classification/brickognize.py:35`). `RuntimeC4` only sees `classifier.classify_async(...)` → `Future`.
- **Blocking stepper calls (C1 jam recovery, up to 2.5 s)**: moved off the tick thread onto `RuntimeC1._hw_worker`. The runtime's state machine enqueues a `RecoveryCommand`; the worker runs the blocking sequence; the runtime's next tick sees `jam_recovery_in_flight=True` and skips further work. Main loop stays ≤5 ms tick budget.

**Recommended execution model (Marc asked for a commit, not an option list):**

> **Hybrid: single-threaded tick loop (20 ms) + per-feed perception threads + per-runtime hardware workers + bounded executor for Brickognize + asyncio only in FastAPI.**

Rationale tied to the code reality:
- Current code already runs `FeederAnalysisThread`, `ClassificationAnalysisThread`, `AuxiliaryDetectionThread` — the threading model works. Formalize it.
- `irl.*_stepper.move_degrees()` blocks 50–2500 ms. The current architecture accepts this stall on MainThread; we move it off.
- Brickognize calls are 2–8 s HTTPS round-trips. Thread-per-piece is fine in concept but must be bounded. Asyncio for this single outbound call buys nothing — requests don't benefit because the rest of the runtime is sync.
- Pure asyncio would require rewriting OpenCV and hardware I/O around executors anyway, defeating the purpose.
- Pure single-thread would serialize everything behind the slowest detector (~40 ms Hive ONNX on a 20 ms tick budget — fails immediately).

---

## 4. Pull-Based Backpressure Model

### Mechanism: `CapacitySlot`

```python
# rt/coupling/slots.py
from threading import Lock
from dataclasses import dataclass, field

class CapacitySlot:
    """One-directional 'I have room' signal. Non-blocking, observable,
    testable. Semaphore-semantics without threading.Semaphore's
    blocking-acquire footgun.
    """
    def __init__(self, name: str, capacity: int) -> None:
        self.name = name
        self._capacity = capacity
        self._taken = 0
        self._lock = Lock()

    def available(self) -> int:
        with self._lock:
            return max(0, self._capacity - self._taken)

    def try_claim(self) -> bool:
        """Upstream calls when it physically releases a piece downstream."""
        with self._lock:
            if self._taken >= self._capacity:
                return False
            self._taken += 1
            return True

    def release(self) -> None:
        """Downstream calls when a piece has left its region (exited, dropped, distributed)."""
        with self._lock:
            if self._taken > 0:
                self._taken -= 1

    def set_capacity(self, capacity: int) -> None:
        with self._lock:
            self._capacity = max(0, int(capacity))
```

### Topology

```
RuntimeC1 --slot(C1→C2, cap=1)--> RuntimeC2
RuntimeC2 --slot(C2→C3, cap=1)--> RuntimeC3
RuntimeC3 --slot(C3→C4, cap=N_c4)--> RuntimeC4
RuntimeC4 --slot(C4→Dist, cap=1)--> RuntimeDistributor
```

Capacities come from per-runtime config:
- `C1→C2` cap = 1 (C2 ring can hold many pieces physically, but we cap inflow because C3 only exits one at a time — same invariant as today's `MAX_CH2_PIECES_FOR_CH1_FEED=5` becomes a soft bound at a different layer).
- `C2→C3` cap = 1 (C3 is a one-at-a-time precise feeder).
- `C3→C4` cap = **derived from `ClassificationChannelConfig.max_zones`** — the `ZoneManager.zone_count()` check and the `MAX_CLASSIFICATION_CHANNEL_DETECTION_CAP=3` raw-detection guard both collapse into `RuntimeC4.available_slots()`. No special case.
- `C4→Dist` cap = 1 (chute holds one piece mid-flight).

### How each Runtime computes `available_slots()`

- **`RuntimeC1`**: infinite (bulk bucket); `available_slots()` returns `1 if not jamming else 0`. (Jam is not a backpressure signal; it's a health error.)
- **`RuntimeC2`**: `1 if ring_count < max_ring_count else 0`. Ring count from tracker tracks confirmed_real.
- **`RuntimeC3`**: `1 if ring_count < 1 else 0` (C3 ring is tiny).
- **`RuntimeC4`**: `max_zones - zone_manager.zone_count() - pending_intake_requests`. This is where the C3→C4 admission collapses. `admission.classification_channel_admission_blocked` becomes `RuntimeC4.available_slots() == 0` and disappears as a special file.
- **`RuntimeDistributor`**: `1 if not (chute_in_motion or piece_in_flight) else 0`.

### Orchestrator wiring (replaces `Coordinator.step`)

```python
# rt/coupling/orchestrator.py (sketch)
class Orchestrator:
    def __init__(self, runtimes: list[Runtime], slots: dict[tuple[str,str], CapacitySlot]):
        ...
    def tick(self, now_mono: float) -> None:
        # Downstream-first evaluation so upstream sees fresh capacity.
        for rt in reversed(self.runtimes):
            inbox = RuntimeInbox(
                tracks=self.perception.latest_tracks(rt.feed_id),
                capacity_downstream=self.slots[rt.runtime_id, rt.downstream_id].available(),
            )
            rt.tick(inbox, now_mono)
```

### Alternatives briefly considered, rejected:

| Option | Why not |
|---|---|
| `queue.Queue(maxsize=N)` between runtimes | Queues carry *items*, but the item here is a physical piece on a physical machine — there is no serializable handoff object to enqueue. Modeling it as "I've enqueued a stepper command" is the wrong abstraction. |
| `threading.Semaphore` direct | Its natural API is blocking `.acquire()`. We explicitly want non-blocking polling so the main loop tick never stalls. |
| Reactive/RxPy / observers | Adds a dependency and a concurrency model we don't need. The natural rhythm is "tick, poll capacity, decide." |

### Why this collapses the C3→C4 special case

Today (`admission.py:34-78`) there is a 4-way OR across: raw-detection cap (3), `zone_manager.zone_count` vs `max_zones`, arc-clear check, transport piece count. These are all **symptoms of one missing thing: a capacity signal from C4 to C3.** In the new model, `RuntimeC4.available_slots()` is the single source of truth, computed from the same underlying signals but exposed as *one number*. `RuntimeC3.tick()` just asks "can I release?" → `capacity_downstream > 0 and track_is_at_exit and stepper_not_busy`. No four-way special case.

---

## 5. Per-Runtime Contracts

All five implement `Runtime` (§2.7). Public contract is `tick / available_slots / on_piece_delivered / health / start / stop`. Internal implementation is state-machine (reused patterns from today, cleaned up).

### 5.1 `RuntimeC1` — Bulk seed shuttle

**C1 is blind — no camera, no perception feed.** It reacts purely to upstream grants and internal timers.

**Reads:** nothing from Perception. Reacts to `ReadySignal` from C2 (upstream grant that C1 is allowed to pulse) and internal HW timers (jam recovery runs time-based, not frame-based).
**Signals upstream:** none (nothing is upstream of C1; the physical bucket is source-of-parts).
**Signals downstream:** claims C1→C2 slot when it fires a forward pulse it believes delivers a piece.
**Internal:** state machine `Idle → Pulsing → Recovering(shake+push)`. Jam recovery (`C1JamRecoveryStrategy`) runs on `_hw_worker`, not on tick. Pause-on-exhaustion emits `Event("hardware.error", ...)` instead of directly writing `shared_state.hardware_error`.

### 5.2 `RuntimeC2` — Separation seed shuttle

**Reads:** `TrackBatch` from `c2_feed`, `capacity_downstream` from C2→C3.
**Upstream signal:** C1→C2 slot release when a piece is confirmed past C2 intake.
**Downstream:** claims C2→C3 slot on exit pulse.
**Internal:** state machine + `Ch2SeparationDriver` (port kept gated by config, today hardcoded disabled). Exit-zone wiggle moves behind the `Filter` chain (as a `StallDetectedAction` event, or stays inline — port choice, not architectural).

### 5.3 `RuntimeC3` — Separation seed shuttle (precise exit)

Same shape as C2, smaller cap, tighter exit semantics. **Important naming correction from Marc:** C3 is Separation, *not* Precise. The "precise" label in the scout map referenced the pulse-type configuration, not the runtime's role.

**Reads:** `TrackBatch` from `c3_feed`, `capacity_downstream` from C3→C4.
**Behavior:** identical contract to C2; different station-specific logic (precise pulse vs. normal, 2 s holdover (`C3HoldoverStrategy`) as an internal strategy). Exit wiggle runs on own `_hw_worker` when `capacity_downstream == 0` and a piece is jammed at exit.

**Strategy plugins (C2 & C3):** Both hold an `AdmissionStrategy` (gates acceptance of inbound ReadySignal requests) and an `EjectionTimingStrategy` (decides exit pulse_ms / settle_ms / fall_time_ms per piece context). Defaults cover today's hardcoded timings; experimental tuning is a config swap.

### 5.4 `RuntimeC4` — Classification

The special one. Owns:
- **`ZoneManager`** (port) — per-piece angular slots.
- **`ClassificationChannelTransport`** (port) — the piece dossier queue.
- **A `Classifier` strategy** (injected from config) — e.g. `BrickognizeClassifier` today, potentially a `LocalOnnxClassifier` tomorrow. Concurrency (bounded executor, timeouts) lives *inside* the classifier implementation, not in the runtime. `RuntimeC4` only sees `Future[ClassifierResult]`.
- **State machine**: `Idle / Running / ExitReleaseShimmy / DropCommit`. Dynamic-zone mode is now the *only* mode — static-zone code path is dropped in the rebuild (no machine config using it per scout data; if needed, re-add as a runtime strategy).
- **Piece lifecycle hooks**: `on_intake (C3→C4 handoff)` mints/resumes `KnownObject`; `on_classified (ClassifierResult arrives)` fills part_id/color_id/confidence; `on_drop_approved (Distributor says ready)` rotates carousel; `on_piece_delivered → RuntimeDistributor` releases C4→Dist slot + waits `min_fall_time_ms` before acknowledging.

**`available_slots()`** delegates to the injected `AdmissionStrategy`: internally calls `self._admission.can_admit(inbound_hint, runtime_state)` where `runtime_state` carries `{zone_count, max_zones, awaiting_intake_count, arc_clear_ok}`. The default `ClassificationChannelAdmission` returns `allowed = (max_zones - zone_count - awaiting_intake > 0) and arc_clear_ok`. **The arc-clear check stays a C4-internal computation but is reflected in the admission decision, not in a neighbor's logic.** Ejection pulse/settle/fall-time come from the injected `EjectionTimingStrategy`.

**`on_piece_delivered`** (inbound from C3): called by orchestrator right after C3 fires its release pulse. C4 flips `awaiting_intake_piece=True` and arms its tracker to bind the next new track at the intake angle.

**Classifier usage — runtime stays generic:**
```python
# rt/runtimes/c4.py
from concurrent.futures import Future
from rt.contracts.classification import Classifier, ClassifierResult

class RuntimeC4(Runtime):
    def __init__(self, ..., classifier: Classifier):
        self._classifier = classifier
        self._inflight: dict[str, Future] = {}  # piece_uuid -> future

    def tick(self, inbox, now_mono):
        # when a new piece is at the classify spot:
        future = self._classifier.classify_async(track, frame, crop)
        self._inflight[piece_uuid] = future
        # on next tick: check future.done(), retrieve ClassifierResult
```

All Brickognize-specific concerns — `max_concurrent=4`, `timeout_s=12.0`, retry-on-connection-reset, HTTP session pooling — live inside `perception/classifiers/brickognize_classifier.py`. Swapping the classifier is a config change in `ClassificationConfig.classifier` (§7), never a runtime edit.

#### C4 ↔ Distributor 7-step handoff handshake

The piece handoff between `RuntimeC4` and `RuntimeDistributor` is the most concurrency-sensitive junction in the whole pipeline: a classification arrives (async Future), the chute must be physically positioned (~hundreds of ms servo move), and then C4 and Distributor must agree on the exact tick to eject + commit. Colors below match `runtime-architecture.html`: **solid red = typed direct call downstream**, **dashed blue = ReadySignal grant upstream**, **solid green = HandoffAck reply**.

1. `RuntimeC4` publishes `PieceClassifiedEvent` on the EventBus — Telemetry, Hive Upload, UI Broadcast consume fire-and-forget. (Bus, not part of the handshake proper.)
2. `RuntimeC4` calls `RuntimeDistributor.handoff_request(PieceHandoff(piece_uuid, ClassifierResult, dossier))` — **solid red** direct typed call downstream.
3. `RuntimeDistributor` consults `RulesEngine.decide_bin(classification, context)` → `BinDecision`, then internally moves chute servos to the target bin. Distributor FSM: `idle → positioning`.
4. When the chute is settled at target, `RuntimeDistributor` sends `ReadySignal(capacity=1, ticket=piece_uuid)` back to `RuntimeC4` — **dashed blue** upstream grant. Distributor FSM: `positioning → ready`.
5. `RuntimeC4` receives the ReadySignal matching its in-flight piece, fires the eject pulse (timing from `EjectionTimingStrategy.timing_for(piece_context)`). C4 FSM: `eject_pending → ejecting`.
6. After `fall_time_ms`, `RuntimeC4` calls `RuntimeDistributor.handoff_commit(piece_uuid)` — **solid red**. Distributor transitions `ready → sending` (piece physically falling into bin).
7. `RuntimeDistributor` completes the drop, publishes `PieceDistributedEvent` (Bus: Run Recorder, set_progress_sync consume), then sends `HandoffAck(piece_uuid, accepted=True)` back to C4 — **solid green**. Both FSMs return to idle.

**Timeout / reject path:** if `RuntimeDistributor` cannot fulfill the request (no bin matches, hardware error, servo timeout), at Step 4 it sends `HandoffAck(piece_uuid, accepted=False, reason=...)` instead of `ReadySignal`. `RuntimeC4` routes the piece to the reject bin (or its own reject chute if configured) and releases the C3→C4 slot. This replaces the ad-hoc "chute failed, what now?" flow in today's `distribution/sending.py`.

### 5.5 `RuntimeDistributor` — Bin mapping + chute

**Bin-mapping is the Distributor's responsibility, delegated to a `RulesEngine` strategy.** C4 hands off the full `ClassifierResult` (plus `piece_uuid` and the piece dossier). Distributor calls:

```python
decision: BinDecision = self._rules_engine.decide_bin(
    classification=result,
    context={"current_profile": ..., "active_set": ...},
)
target_bin = decision.bin_id
```

The default ships as `LegoRulesEngine` — it ports today's `DistributionLayout` + `SortingProfile` logic behind the new Protocol. For new sorting domains (coins, screws, buttons) a different rules engine is configured; no runtime code changes.

**Sorting profile hot-reload:** triggered by an API call, runs `rules_engine.reload()` on the live instance, no runtime restart required.

**Distributor is blind — no camera, no perception feed.** It reacts to inbound `PieceHandoff.request` from C4 and internal chute/servo state.

**Reads:** nothing from Perception. Reacts to `PieceHandoff.request` from C4 and internal HW state (chute position, servo motion).
**External API:**
- `request_distribution(piece: KnownObject, classification: ClassifierResult) -> None` — C4 calls this when it wants to send a piece. Does not block.
- `is_ready_for_piece() -> bool` — returns True iff chute is homed on the target bin and downstream is clear. Orchestrator consults via `available_slots()`.
- `on_piece_delivered(piece_uuid, now_mono)` — called by orchestrator when chute fall time elapsed; triggers piece commit, run_recorder, WS event.

**Internal state machine** (unchanged): `Idle → Positioning → Ready → Sending`. `Sending._shouldReopenGate` logic (port of `sending.py:104`) becomes internal; the "piece still visible on carousel tracker" check is now read from the bus via subscribed `perception.tracks` events (handed in as `inbox.tracks_for_feed("c4_feed")`).

### Per-runtime summary table

| Runtime | Feed(s) read | Up-slot (releases) | Down-slot (claims) | Owns hardware | Owns strategies | Internal FSM states |
|---|---|---|---|---|---|---|
| C1 | — (blind) | — | C1→C2 | C1 rotor stepper | `AdmissionStrategy`, `EjectionTimingStrategy` | Idle, Pulsing, Recovering |
| C2 | `c2_feed` | C1→C2 | C2→C3 | C2 rotor + separation | `AdmissionStrategy`, `EjectionTimingStrategy` | Idle, Pulsing, Agitating, Wiggling |
| C3 | `c3_feed` | C2→C3 | C3→C4 | C3 rotor, precise control | `AdmissionStrategy`, `EjectionTimingStrategy` | Idle, Pulsing(Precise/Normal), Holdover, Wiggling |
| C4 | `c4_feed` | C3→C4 | C4→Dist | Carousel stepper | `Classifier`, `AdmissionStrategy`, `EjectionTimingStrategy` | Running, DropCommit, ExitReleaseShimmy |
| Distributor | — (blind) | C4→Dist | — | Chute servos + door servos | `RulesEngine`, `AdmissionStrategy` | Idle, Positioning, Ready, Sending |

---

## 6. Cross-Cutting: Event Bus & Side Channels

### What goes on the bus (non-hot-path only)

| Topic | Payload | Publisher | Subscribers |
|---|---|---|---|
| `system.hardware_state` | state, error | orchestrator, runtimes | `WsBroadcaster`, `MetricsCollector` |
| `system.sorter_state` | paused/running/etc. | sorter_controller | WS |
| `piece.registered` | KnownObject | RuntimeC4 | WS, `SampleCapture`, `HiveUpload` |
| `piece.classified` | KnownObject + ClassifierResult | RuntimeC4 | WS, `MetricsCollector`, `HiveUpload` |
| `piece.distributed` | KnownObject + bin | RuntimeDistributor | WS, `run_recorder`, `set_progress_sync` |
| `perception.tracks` | TrackBatch (downsampled 5 Hz) | PerceptionRunner | Overlay renderer, `MetricsCollector` |
| `perception.frame` | JPEG + overlays | FrameEncoder | `WsBroadcaster` (coalesced latest-per-camera) |
| `hardware.error` | banner message | any runtime | `WsBroadcaster`, `SorterController` (auto-pause) |
| `runtime.stats` | snapshot | `MetricsCollector` (1 Hz) | WS |

### What does NOT go on the bus

- `DetectionBatch` / `TrackBatch` between detector → tracker → filter → runtime. That is explicit typed dataflow inside the `PerceptionPipeline` and from `PerceptionRunner` into `RuntimeInbox`. Never on the bus.
- `StepperCommand`. Direct call from runtime to its `_hw_worker`.
- `CapacitySlot` claims. Direct calls.
- `ClassifierResult` between `Classifier` → `RuntimeC4` → `RuntimeDistributor`. Direct Future-and-dataclass handoff.

### Sample capture & Hive upload

Today these are woven into VisionManager and Distribution (`scheduleFeederTeacherCaptureAfterMove`, `set_progress_sync.notify`, `blob_manager.write_piece_crop`). In the rebuild:

- `rt/events/sinks/sample_capture.py` subscribes to `piece.registered` + `perception.drop_zone_burst_complete`. It owns the burst-capture side effect — writes crops, enqueues into Hive pipeline. No coupling from runtime to blob storage.
- `rt/events/sinks/hive_upload.py` subscribes to `piece.classified` + `piece.distributed`. Owns the upload queue (the existing `SetProgressSyncWorker` port).

### Concurrency strategy for sinks

Event bus dispatcher runs on a dedicated thread. Slow sinks (Hive upload is seconds) get their own internal queue + worker. If the dispatch queue fills (2048 events), drop-oldest with a logged counter. The bus never blocks publishers — publishers are on hot threads and must be lossless-in-publishing but lossy-in-delivery for non-critical topics (`perception.tracks` is explicitly lossy; `piece.classified` is NOT — it goes into an unbounded-but-persisted SQLite table via `remember_piece_dossier` immediately at publish-time, then the WS broadcast is best-effort).

### Classifier calls — explicit placement

The `Classifier` protocol (and its Brickognize implementation) is NOT on the bus. It's a synchronous-from-C4's-point-of-view API call via `classifier.classify_async(...)` returning a `Future`. The result is published as `piece.classified` *after* the future completes. This separates "what the runtime does" (submit + await) from "who else cares" (bus subscribers).

---

## 7. Configuration & Strategy Registry

### Strategy registration

- **Decorator-based self-registration** (rejected: entry-points — adds packaging overhead; rejected: explicit list — fragile and duplicative).
- Each strategy module: `@register_detector("mog2")` / `@register_classifier("brickognize")` / `@register_rules_engine("lego_default")` on the class. Modules imported at startup by their package `__init__.py`:

```python
# rt/perception/detectors/__init__.py
from . import mog2, heatmap_diff, gemini_sam, hive_onnx, baseline_diff  # noqa: F401
# import side-effect triggers registration
```

```python
# rt/perception/classifiers/__init__.py
from . import brickognize_classifier  # noqa: F401
```

```python
# rt/rules/__init__.py
from . import lego_rules  # noqa: F401
```

### Config schema (Pydantic — already a project dep)

```python
# rt/config/schema.py
from pydantic import BaseModel, Field
from typing import Literal

class ZoneConfig(BaseModel):
    kind: Literal["rect", "polygon", "polar"]
    params: dict

class FeedConfig(BaseModel):
    feed_id: str
    camera_id: str
    purpose: Literal["c2_feed", "c3_feed", "c4_feed", "aux"]  # C1 and Distributor are blind
    zone: ZoneConfig
    picture_settings: dict | None = None
    fps_target: float = 10.0

class FilterConfig(BaseModel):
    key: str
    params: dict = Field(default_factory=dict)

class PipelineConfig(BaseModel):
    feed_id: str
    detector: dict   # {"key": "hive:foo", "params": {...}}
    tracker: dict    # {"key": "polar", "params": {...}}
    filters: list[FilterConfig] = Field(default_factory=list)
    calibration: dict | None = None

class RuntimeConfig(BaseModel):
    runtime_id: Literal["c1","c2","c3","c4","distributor"]
    feeds: list[str]                     # feed_ids this runtime consumes (empty for blind runtimes C1/Distributor)
    downstream: str | None               # next runtime_id
    capacity_to_downstream: int = 1
    admission: dict = Field(default_factory=dict)         # {"key": "classification_channel", "params": {...}}
    ejection_timing: dict = Field(default_factory=dict)   # {"key": "default_c4", "params": {...}}
    params: dict = Field(default_factory=dict)

class ClassificationConfig(BaseModel):
    classifier: dict                     # {"key": "brickognize", "params": {"max_concurrent": 4, "timeout_s": 12.0}}

class DistributionConfig(BaseModel):
    rules_engine: dict                   # {"key": "lego_default", "params": {"sorting_profile_path": "..."}}

class SorterConfig(BaseModel):
    cameras: list[dict]                  # thin port of today's TOML camera section
    feeds: list[FeedConfig]              # camera → 1..N feeds (transitional, see §10)
    pipelines: list[PipelineConfig]      # one per feed
    runtimes: list[RuntimeConfig]
    classification: ClassificationConfig
    distribution: DistributionConfig
```

### Config sources

- **Hardware topology + feed mapping + pipeline wiring** → `machine_params.toml` (human-edited, git-tracked per-machine).
- **Per-feed strategy selection + filter params** → SQLite (editable at runtime via API). Validated through `PipelineConfig.model_validate()` before commit.
- **Machine-specific overrides** → `machine_specific_params.toml` (as today).
- Startup: `loader.py` merges TOML + SQLite, validates with Pydantic, yields a frozen `SorterConfig`. Any validation error is a fatal startup error with a machine-readable path (`feeds[2].zone.params.r_inner: field required`).

### Example config excerpt

```toml
# machine_params.toml
# 1:1 Camera:Feed target. Legacy rigs with 1 camera producing multiple feeds
# use SplitFeed compat shim (see §0 TL;DR).
[[feeds]]
feed_id = "c2_feed"
camera_id = "cam_c2"
purpose = "c2_feed"
fps_target = 10.0
zone = { kind = "polar", params = { center_xy = [960,540], r_inner = 180, r_outer = 260, theta_start_rad = 0.0, theta_end_rad = 6.28 } }

# Note: no c1_feed / distributor_feed — C1 and Distributor are blind.

[classification]
classifier = { key = "brickognize", params = { max_concurrent = 4, timeout_s = 12.0 } }

[distribution]
rules_engine = { key = "lego_default", params = { sorting_profile_path = "profiles/current.json" } }
```

```json
// SQLite JSON blob for pipeline
{
  "feed_id": "c2_feed",
  "detector": {"key": "mog2", "params": {"history": 500, "var_threshold": 16}},
  "tracker":  {"key": "polar", "params": {"score_threshold": 0.1}},
  "filters":  [{"key": "size", "params": {"min_area_px": 400}},
               {"key": "ghost", "params": {"confirmed_real_only": true}}]
}
```

---

## 8. Migration Plan (Phased)

All work continues on the existing `sorthive` branch — no separate `runtime-rebuild` branch. On `sorthive`, no unrelated feature work is started during the rebuild; `main` is untouched until cutover. A marker commit (`chore: pre-architecture marker`) lands on `sorthive` immediately before scaffolding begins so the "before/after" boundary is git-addressable. Each phase ends with an intermediate tag on `sorthive` (`rebuild-phase-N-green`); the tags are local breadcrumbs, not release markers.

### Phase 1 — Scaffold (≈3–4 PD)
Create `rt/` tree, contracts (§2), strategy registry, Pydantic config schema + loader, `EventBus` implementation, `RuntimeContext` (the DI container).
**Done when:** `pytest rt/tests/contracts/` green; registry round-trips a dummy strategy; config file loads and validates end-to-end; `EventBus` handles 10k events/s in the dispatcher thread test.

### Phase 2 — One perception stack end-to-end (≈4–5 PD)
Port MOG2 detector + PolarTracker + SizeFilter + GhostFilter for *one* feed (`c2_feed`). Build `PerceptionRunner` per-feed thread. Wire to the existing FastAPI through a minimal `WsBroadcaster` sink that publishes `perception.frame` events. Keep the old runtime running; new pipeline runs side-by-side on a `--shadow=rt` flag. UI shows the new overlay.
**Done when:** Operator can toggle old/new overlays and see identical bboxes and tracks on `c2_feed`. Shadow-mode perception matches old detector output within 5% box-IoU on a recorded 5-minute clip.

### Phase 3 — Runtimes C1–C3 + pull coupling (≈6–8 PD)
Port `RuntimeC1/C2/C3` with `CapacitySlot` wiring. `Orchestrator` drives them. Hardware workers operational. No C4 yet. Behind a `--runtime=rt` flag, `main.py` starts only the feeder runtimes; classification+distribution still run on the old path through a compatibility shim (`OldRuntimeAdapter` that reads from the new perception and exposes old-style interfaces).
**Done when:** Dry sort cycle with empty bucket, capacity slots observably propagate, stall recovery runs on hardware worker thread, main-loop tick stays ≤5 ms 99th percentile (Profiler snapshot).

### Phase 4 — RuntimeC4 + Classifier strategy (≈5–7 PD)
Port ZoneManager, ClassificationChannelTransport, `Running` state logic into `RuntimeC4`. Ship `BrickognizeClassifier` as the first `Classifier` strategy — internally uses `ThreadPoolExecutor(4)` replacing today's unbounded daemon threads. Port piece dossier handoff. Delete `ClassificationStateMachine` (standard carousel) unless config flag is set — if set, keep the file behind a `UnifiedClassificationAdapter`.
**Done when:** C3→C4 piece intake works on real machine, Brickognize runs bounded (never more than 4 concurrent), timeout paths exercised by manual network-kill test, classifier swap demoed end-to-end (even if only against a `DummyClassifier` returning fixed output).

### Phase 5 — RuntimeDistributor + RulesEngine + end-to-end sort (≈3–4 PD)
Port distribution state machine. Wire C4→Dist slot. Port bin_mapping into `LegoRulesEngine` behind the `RulesEngine` Protocol. Full hot-path now on `rt/`.
**Done when:** "Minimum Viable Sorter" — operator presses Home → feeds a known set → full sort cycle completes → bins contain the correct parts. All 27 `shared_state` globals eliminated; `server.shared_state` reduced to `active_connections + server_loop` (WS infrastructure only). Main loop tick under 5 ms 99th percentile under full load. Sorting profile hot-reload via `rules_engine.reload()` verified.

### Phase 6 — Cutover PR `sorthive → main` (≈1 PD)
Single PR from `sorthive` to `main` that:
- Removes `--runtime=` flag (new is default).
- Deletes `backend/vision/vision_manager.py`, `backend/server/shared_state.py` (large rewrite portions), `backend/subsystems/feeder/`, `backend/subsystems/classification/`, `backend/subsystems/classification_channel/`, `backend/subsystems/channels/`, `backend/machine_runtime/`, `backend/coordinator.py`, `backend/piece_transport.py`.
- Renames `rt/` → `backend/` (or keeps `rt/` — Marc's call).
- Updates docs.

**Total: ~22–29 PD.** Given pair-cadence ambiguity, treat as a 4–6 week feature stream.

**Riskiest phase: Phase 4.** The classification channel code is the most tangled — `Running.step()` alone is ~200 LoC with seven interacting sub-systems (zone manager, transport, recognition, burst capture, handoff, live-id probe, drop snapshot). The Brickognize bounded-pool switch is a correctness change (bounded concurrency changes timing under load). Plan for 1–2 days of pairing debugging on real hardware with a recorded load.

---

## 9. Effort Sizing

| Category | LoC (rough) |
|---|---|
| New code (contracts, registry, orchestrator, event bus, perception pipeline scaffold, runtime bases, slot coupling, config loader, Classifier + RulesEngine contracts & default impls) | ~3 700 |
| Ported code (polar tracker, mog2, heatmap diff, gemini_sam, handoff, history, station strategies, distribution FSM, zone manager, recognizer, aruco + region providers, brickognize client, carousel HW, stepper interface) | ~6 000 (mostly mechanical: imports, interface adapters, constructor-injection) |
| Deleted code (old vision_manager.py 4963 + shared_state.py writes 350 + coordinator/machine_runtime 400 + machine_setup/classification dual-pipe 800 + dead bytetrack/ch2_agitation 500) | ~7 000 |

Net: **code shrinks by ~2 300 LoC** despite adding a full contract layer (now including Classifier and RulesEngine). That's the primary win.

Person-days: **22–29 PD** end-to-end. See §8 for phase breakdown.

**Riskiest phase: Phase 4 (RuntimeC4)** — most tangled original code; touches concurrency (Brickognize bound) + real hardware + WS contract simultaneously.

---

## 10. Open Design Decisions (Require Marc's Call)

Minimized list — Marc decided runtime execution model, 1:1 Camera:Feed (legacy via `SplitFeed`), branch strategy, and the Classifier/RulesEngine plugin shape. Five decisions remain.

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | **Event bus library** | `pyee`, `blinker`, custom, extend TickBus | **Extend TickBus → `InProcessEventBus`**. Keep the well-understood code (85 LoC today), add topic-glob subscribe, bounded dispatcher queue, typed payloads. No new dep. Rewrite is small; library adoption is risk we don't need. |
| 2 | **Config source of truth split** | (a) TOML only, (b) SQLite only, (c) both with clear split | **(c) split by axis**: TOML for hardware topology, feed→camera wiring, pipeline structure (detector/tracker slots). SQLite for tunable params, strategy keys per scope, sorting profile. Rule: if operator changes it at runtime via UI → SQLite. If it changes only when the physical machine changes → TOML. |
| 3 | **Classifier concurrency model (inside `BrickognizeClassifier`)** | (a) bounded ThreadPoolExecutor, (b) asyncio queue + aiohttp, (c) task-per-piece with Semaphore | **(a) ThreadPoolExecutor(max_workers=4)** inside `BrickognizeClassifier`. Matches everything else in the runtime (sync + threads). No asyncio intrusion. `Future.result(timeout=12)` is clean and replaces the current twin-thread timeout hack. |
| 4 | **Keep ByteTrack?** | delete, keep as fallback | **Delete.** Dead for two years; polar tracker is better on our geometry (`polar_tracker.py:10-13` argues this). One less strategy to maintain. |
| 5 | **`PieceHistoryBuffer` vs. Hive pipeline** | keep both, consolidate on Hive | **Keep both in this rebuild.** The on-disk history is used for recognizer crops (`ejecting.py:229` → `vision.getFeederTrackHistoryDetail`). Consolidation is a follow-up; out of scope for the runtime rebuild. |
| — | **Classifier + RulesEngine are mandatory plugins** (not an "optional choice") | — | **Decided.** Both are explicit strategy Protocols in §2. Shipped implementations: `BrickognizeClassifier` (default classifier), `LegoRulesEngine` (default rules engine). Future domains (coins, screws) ship additional strategies; the Runtime layer never needs to change. |

**Previously-open, now-closed:**

- **Camera:Feed mapping** → decided: **1:1 is the target.** Legacy rigs with 1 camera → multiple feeds are wrapped via a `SplitFeed` compat shim — explicit Legacy, not first-class, not transitional. The canonical vision (`runtime-architecture.html`) pins this.
- **Branch strategy** → decided: **stay on `sorthive`** with a pre-architecture marker commit; no separate `runtime-rebuild` branch.

---

## 11. What We're Explicitly NOT Doing

- **Setup-flow rebuild** (homing wizard, auto-calibration UI) — follow-up. Current `_home_hardware()` is ported as-is, but the `irl.__dict__.clear/update` trick is replaced with **immutable IRL — construct fresh on each home, swap reference under one lock, no in-place mutation**.
- **Firmware** — untouched.
- **`hive/` cloud platform** — untouched.
- **Frontend** — unchanged WS event names: `frame`, `known_object`, `runtime_stats`, `system_status`, `sorter_state`, `heartbeat`, `cameras_config`, `camera_health`, `sorting_profile_status`. Payload shapes unchanged. Minor additions allowed (e.g. `runtime_stats.payload.slots` for per-coupling capacity) but never removals.
- **No microservices decomposition.** Single Python process.
- **No ROS, no Dora, no agent framework.** Plain threads + typed contracts.
- **No new storage** beyond SQLite + blob filesystem. Schema validation added (§7); storage layer untouched.
- **Not rewriting algorithms.** Polar tracker, MOG2, heatmap diff, Gemini/SAM, Brickognize — all ported. Only their *wiring* changes.
- **Not reworking WS transport.** Uvicorn + wsproto, run_coroutine_threadsafe pattern stays.
- **Not changing the macOS UVC camera branch.** Port as-is.
- **Not on a separate rebuild branch** — the work happens on `sorthive`, bookended by a Pre-Architecture marker commit before scaffolding begins. `main` is untouched until the single cutover PR.

---

*End of design proposal. Cite this document by anchor (`§N.M`) in implementation PRs on `sorthive`.*

---

### Critical Files for Implementation

The five files most load-bearing for the rebuild:

- /Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/vision/vision_manager.py
- /Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/server/shared_state.py
- /Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/classification_channel/running.py
- /Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/subsystems/feeder/admission.py
- /Users/mneuhaus/Workspace/LegoSorter/sorter-v2/software/sorter/backend/coordinator.py
