# Architecture

## Overview

The sorter uses one or more Raspberry Pi Pico microcontrollers running the `sorter_interface_firmware`. A Python client discovers all connected Picos over USB serial, aggregates their actuators (steppers and servos) into a single logical interface, and binds them to application-level roles (carousel, chute, rotors, layer servos).

There is no Arduino or MCU-type switching. The system is exclusively Pico + SorterInterface firmware.

## Hardware Communication

### Bus Protocol

Each Pico exposes a serial port. The client communicates using a binary COBS-framed protocol (`client/hardware/bus.py`) with CRC32 message integrity. The bus supports both directly-attached USB devices (address 0) and multi-drop RS-485 configurations with unique addresses per device.

Key classes:
- `MCUBus` — low-level serial framing, device scanning, send/receive
- `SorterInterface` — high-level device abstraction: steppers, servos, detect/init
- `StepperMotor` / `ServoMotor` — individual actuator control with position persistence

### Device Discovery

`client/irl/device_discovery.py` enumerates all compatible USB serial ports via `MCUBus.enumerate_buses()`. The `MCU_PATH` environment variable can override auto-discovery.

- `discoverMCU()` — returns a single port (first found or env override)
- `discoverMCUs()` — returns all detected ports

## Firmware Role System

A single firmware codebase (`firmware/sorter_interface_firmware/`) builds for different physical nodes by selecting a **firmware role** at CMake time:

```
cmake -DFIRMWARE_ROLE=feeder ..     # or: distribution
```

Each role selects a different set of logical stepper names that are advertised in the `detect` JSON payload. The physical channel wiring stays the same — only the names change.

| Role | Stepper Names (example) |
|------|------------------------|
| `feeder` | `carousel`, `chute_stepper`, `first_c_channel_rotor`, `second_c_channel_rotor` |
| `distribution` | `distribution_ch0`, `distribution_ch1`, `distribution_ch2`, `distribution_ch3` |

Hardware config headers (`hwcfg_basically.h`, `hwcfg_skr_pico.h`) define the physical pin mapping for each board variant, selected via `cmake -DHW_SKR_PICO=ON`.

See `firmware/sorter_interface_firmware/README.md` for build options.

## Client Initialization Flow

All hardware init happens in `client/irl/config.py`:

### 1. `mkIRLConfig()`
- Calls `discoverMCUs()` to find all Pico serial ports
- Loads camera configuration from stored camera setup
- Creates an `ArucoTagConfig` for feeder geometry calibration
- Returns `IRLConfig`

### 2. `mkIRLInterface(config, gc)`
- For each discovered port:
  - Opens an `MCUBus` connection
  - Calls `bus.scan_devices()` to find all addresses on that bus
  - Creates a `SorterInterface` for each address
- Aggregates all `SorterInterface` instances into `irl_interface.sorter_interfaces`
- Iterates each interface's `board_info.stepper_names` to build a global actuator inventory
- Binds each stepper to an attribute on `IRLInterface` by its firmware-reported name (e.g. `carousel_stepper`, `chute_stepper`, `first_c_channel_rotor_stepper`)
- Logs warnings for any required steppers not found in the inventory
- Initializes servos from the first interface that has both servos and a chute stepper
- Initializes the distribution chute
- Returns `IRLInterface`

### Required Stepper Names
The client expects these logical names to be present across all discovered devices:
- `carousel`
- `chute_stepper`
- `first_c_channel_rotor`
- `second_c_channel_rotor`
- `third_c_channel_rotor`

Missing names produce a warning but don't prevent startup.

## Application Startup (`main.py`)

1. Load `.env` and create `GlobalConfig`
2. `mkIRLConfig()` — discover devices and cameras
3. `ArucoConfigManager` — load or seed ArUco tag configuration
4. `mkIRLInterface()` — init all hardware, bind steppers/servos
5. Open servos, home chute
6. Create `VisionManager`, `Telemetry`, `SorterController`
7. Start vision threads, controller, API server, WebSocket broadcaster
8. Enter main loop (heartbeat, frame broadcast, controller step)
9. On `KeyboardInterrupt`: disable steppers, shutdown all interfaces, exit

## Key Directory Layout

```
client/
├── main.py                    # App entry point
├── aruco_config_manager.py    # ArUco tag config persistence
├── aruco_config_default.json  # Committed baseline config
├── aruco_config.json          # Local runtime config (git-ignored)
├── hardware/
│   ├── bus.py                 # MCUBus binary protocol
│   ├── cobs.py                # COBS framing
│   └── sorter_interface.py    # SorterInterface, StepperMotor, ServoMotor
├── irl/
│   ├── config.py              # IRLConfig, IRLInterface, mkIRLInterface()
│   ├── device_discovery.py    # USB device enumeration
│   ├── bin_layout.py          # Distribution bin layout
│   └── pico_pin_config.py     # Firmware header pin parser (used by tests)
├── vision/
│   ├── aruco_tracker.py       # ArUco detection + smoothing + outlier rejection
│   ├── vision_manager.py      # Camera orchestration and frame routing
│   ├── camera.py              # Capture threads
│   └── inference.py           # Model inference threads
├── server/
│   ├── api.py                 # FastAPI REST + WebSocket + MJPEG streaming
│   └── templates/
│       └── aruco_config.html  # Calibration GUI
├── subsystems/
│   ├── feeder/                # Feeder state machine + geometry analysis
│   └── distribution/          # Distribution chute + bin positioning
└── states/                    # Sorter FSM states
```
