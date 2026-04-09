---
layout: default
title: Sorter architecture
type: explanation
audience: contributor
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-architecture
kicker: Sorter — Under the hood
lede: Where things live in the Sorter V2 local software, and why. Read this before changing any module under `software/sorter/backend/`.
permalink: /sorter/architecture/
---

The local software is two processes:

| Process | Path | Responsibility |
|---|---|---|
| **Python backend** | `software/sorter/backend/` | Owns hardware, vision, authoritative state. Listens on `:8000`. |
| **SvelteKit UI** | `software/sorter/frontend/` | View + command emitter. No machine state. Vite on `:5173`. |

`./dev.sh` boots both. The UI proxies API calls to the backend.

## Backend boot

Entry point: `software/sorter/backend/main.py`. It wires together:

- **`global_config.py`** — logging, profiler, runtime stats. Passed everywhere as `gc`.
- **`irl/config.py`** — `IRLConfig` is the declarative hardware config; `IRLInterface` is the live hardware (servos, steppers, chute, carousel).
- **`vision/vision_manager.py`** — camera capture threads + detection pipelines.
- **`sorter_controller.py`** — lifecycle wrapper. States: `INITIALIZING / READY / PAUSED / RUNNING`.
- **`server/api.py`** — FastAPI + WebSocket. Runs in its own thread.

The main thread runs a tick loop. When the controller is `RUNNING`, each tick calls `coordinator.step()`.

## The coordinator and three subsystems

`coordinator.py` is thin. It holds three independent state machines under `subsystems/` and ticks them in order:

```python
def step(self):
    self.feeder.step()
    self.classification.step()
    self.distribution.step()
```

Cross-subsystem communication is one tiny dataclass: `SharedVariables` (`classification_ready`, `distribution_ready`, `carousel`, `chute_move_in_progress`). That is the *entire* shared API.

| Subsystem | States | Job |
|---|---|---|
| **Feeder** | `IDLE`, `FEEDING` | Watches the MOG2 channel detector; moves detected parts from a C-channel to the carousel. Skipped entirely in `manual_carousel` mode. |
| **Classification** | `IDLE`, `DETECTING`, `ROTATING`, `SNAPPING` | Rotates the carousel until a part is found, then captures top/bottom frames and runs the detection algorithm. The slow path — most OpenRouter latency lives here. |
| **Distribution** | `IDLE`, `POSITIONING`, `READY`, `SENDING` | Maps the classified part → category via `SortingProfile`, asks `Chute` to move to the matching bin angle, releases the part. |

`chute.py` is worth reading if you care about calibration: bin angles are computed open-loop from `first_bin_center + section * 60° + bin * bin_width`. No closed loop after homing.

## Vision pipeline

`vision/vision_manager.py` is the most complex single module. It owns:

- **One `CaptureThread` per camera**, holding the latest frame.
- **`FeederAnalysisThread`** — runs MOG2 against the feeder camera.
- **`ClassificationAnalysisThread`** — runs the configured detection algorithm against the classification cameras.
- **A ~10 FPS preview encoder** that pushes frames to the UI over WebSocket.

Two camera layouts:

| Layout | Cameras |
|---|---|
| `default` | One feeder camera covering all C-channels + carousel; one or two classification cameras. |
| `split_feeder` | One camera per C-channel + carousel; classification cameras separate. |

Detection algorithms are plugin-style (`detection_registry.py`). Defaults: MOG2 (feeder), heatmap diff (carousel), `gemini_sam` (classification — remote Gemini call + SAM2 post-processing).

## Machine platform

`machine_platform/` is the layer that lets the same higher-level code run on different hardware. The key type is `MachineProfile`:

```python
@dataclass(frozen=True)
class MachineProfile:
    camera_layout: str
    feeding_mode: str
    servo_backend: str            # "pca9685" or "waveshare"
    stepper_bindings: Mapping[str, str]
    stepper_direction_inverts: Mapping[str, bool]
    boards: tuple[BoardSummary, ...]
    capabilities: MachineCapabilities
```

Built from auto-discovered control boards over USB serial + the user's `machine_specific_params.toml`. `stepper_bindings` is the escape hatch for wiring mistakes — rebind a logical name like `carousel` to whichever physical channel the motor is actually wired to.

## Configuration layers

Four sources, in increasing user-editability:

| Layer | Where | Owns |
|---|---|---|
| **Code defaults** | Python constants | Things that are the same on every machine. |
| **TOML** | `machine_specific_params.toml` (env: `MACHINE_SPECIFIC_PARAMS_PATH`) | Servo angles, layer layout, chute calibration, camera indices, feeding mode. |
| **Blob storage** | `software/sorter/backend/blob/*.json` (via `blob_manager`) | Detection configs, classification polygons, Hive credentials, ArUco calibrations. Most of this is UI-edited. |
| **SQLite** | `local_state.sqlite` | API keys, recent known objects, lifecycle state across restarts. |

The sorting profile (`sorting_profile.json`) is technically a blob but is edited through its own UI because it changes during a run. See [profile reference]({{ '/sorter/profile-reference/' | relative_url }}).

## UI

SvelteKit + Vite. REST for commands and config; WebSocket (`/api/ws`) for events (frames, transitions, detections, runtime stats). The UI owns no authoritative state — if two tabs disagree, the missing piece is a WebSocket event, not a frontend cache.

Routes mirror operator mental model, not backend module layout: `/setup`, `/`, `/profiles`, `/bins`, `/classification-samples`, `/settings`, `/styleguide`.

## Restart safety

`process_guard.py` enforces one backend per machine — so a crashed `./dev.sh` cannot race the old serial-port owner. Restart always boots into `INITIALIZING`; it takes an explicit `start` then `resume` from the UI to reach `RUNNING`. Parts mid-classification at shutdown are lost — the system does not try to resume an in-flight part.

## Where to look first

| Symptom | Start here |
|---|---|
| Nothing detected in the feeder | `vision/mog2_channel_detector.py`, `subsystems/feeder/feeding.py` |
| Carousel spins forever | `subsystems/classification/rotating.py`, `vision/classification_detection.py` |
| Part lands in the wrong bin | `subsystems/distribution/chute.py`, `sorting_profile.py` |
| UI state ≠ reality | `server/api.py`, `message_queue/handler.py`, the WebSocket events |
| First-boot config refuses to save | `blob_manager.py`, `machine_platform/machine_profile.py` |

User-facing version of this list: [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}).
