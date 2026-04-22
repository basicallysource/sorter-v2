# Setup

## Prerequisites

- [Git](https://git-scm.com/)
- [Node.js](https://nodejs.org/) (v20+) and npm
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Raspberry Pi Pico SDK](https://github.com/raspberrypi/pico-sdk) (for firmware builds)

## Clone

```bash
git clone https://github.com/basicallysource/sorter-v2.git
cd sorter-v2/software
```

## Firmware

Flash firmware to each Raspberry Pi Pico using the Makefile in `firmware/sorter_interface_firmware/`. Put one Pico into BOOTSEL mode at a time (so it mounts as `RPI-RP2`), then run the appropriate target — the build happens automatically:

```bash
cd firmware/sorter_interface_firmware
make flash-feeder       # builds and flashes feeder firmware
make flash-distribution # builds and flashes distribution firmware
```

Flash each Pico separately, one at a time in BOOTSEL mode.

## Environment

```bash
cp .env.example .env
cp machine.example.toml machine.toml
```

Edit the path in `.env` to match the real path to `machine.toml`.


Camera assignment happens in the UI: open the running frontend and use the Settings → Cameras page to map each OpenCV device index to its role (feeder, classification top/bottom, carousel, etc). The resulting assignments are written back to `machine_params.toml` under `[cameras]`.

## UI Dependencies

```bash
cd sorter/frontend
npm install
```

---

# Running

You'll need two terminal tabs, both from `sorter-v2/software`.

## Terminal 1: UI

```bash
cd sorter/frontend
npm run dev
```

## Terminal 2: Client

```bash
cd sorter/backend
uv run python main.py
```

Or from `sorter-v2/software`, you can use the bundled dev runner:

```bash
./dev.sh backend
```

That starts the full machine client with the controller, hardware bindings, and API. If you only want the lightweight API shell for UI work, use:

```bash
./dev.sh api
```

If you want to use an Android phone as the carousel camera on macOS, run:

```bash
./scripts/android_camera_bridge.sh
```

Then point `[cameras].carousel` at `http://127.0.0.1:18081/carousel.mjpg`.

`uv` will install Python 3.13 and all dependencies on first run. The `.env` file is loaded automatically.

On startup the client will:
1. Discover all connected Pico devices over USB serial
2. Scan each bus for SorterInterface firmware devices
3. Aggregate stepper and servo actuators across all discovered boards
4. Bind actuators to logical roles (carousel, chute, rotors) using firmware-reported names

**Windows**: Run PowerShell as Administrator to access serial ports.

---

# Further Reading

- [ARCHITECTURE.md](ARCHITECTURE.md) — Multi-Pico hardware abstraction, firmware roles, client init flow
- [../docs/runtime-status.md](../docs/runtime-status.md) — Current detector benchmark conclusions, deployment recommendations, and canonical local artifacts to keep
- [../docs/model-artifacts.md](../docs/model-artifacts.md) — Which detector exports and compiled formats exist, what they are for, and how they map to targets
- [sorter/backend/ARUCO_GUI_USAGE.md](sorter/backend/ARUCO_GUI_USAGE.md) — Web-based ArUco tag calibration GUI
- [../docs/device-benchmarking.md](../docs/device-benchmarking.md) — Reproducible detector benchmarking across Mac, Raspberry Pi, and Orange Pi targets
- [../docs/hailo-hef-workflow.md](../docs/hailo-hef-workflow.md) — `ONNX -> HEF` workflow for Raspberry Pi 5 AI HAT deployments
- [firmware/sorter_interface_firmware/README.md](firmware/sorter_interface_firmware/README.md) — Firmware build options and flashing
