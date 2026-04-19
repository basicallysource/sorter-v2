# Setup

## Prerequisites

- [Git](https://git-scm.com/) with [Git LFS](https://git-lfs.github.com/)
- [Node.js](https://nodejs.org/) (v20+) and npm
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Raspberry Pi Pico SDK](https://github.com/raspberrypi/pico-sdk) (for firmware builds)

## Clone

```bash
git lfs install
git clone https://github.com/basicallysource/sorter-v2.git
cd sorter-v2/software
```

Git LFS files (models, `parts_with_categories.json`) should download automatically. If not, run `git lfs pull`. You can verify by checking that `software/models/` contains `.pt` files (not small text pointers).

## Firmware

Build and flash the `sorter_interface_firmware` for each Raspberry Pi Pico. See `firmware/sorter_interface_firmware/README.md` for full build instructions, including role-based build variants (feeder vs distribution).

Quick example (feeder role):
```bash
cd firmware/sorter_interface_firmware
mkdir -p build && cd build
cmake -DFIRMWARE_ROLE=feeder ..
ninja
picotool load -f sorter_interface_firmware.uf2
```

## Environment

```bash
cp .env.example .env
```

Edit `.env` and update:
- `CLASSIFICATION_CHAMBER_MODEL_PATH`, `FEEDER_MODEL_PATH`, `PARTS_WITH_CATEGORIES_FILE_PATH` — set these to the absolute paths where the repo was cloned (the files are pulled via Git LFS)
- Pico devices are auto-detected via USB. Override with `MCU_PATH` if needed.
- `MACHINE_SPECIFIC_PARAMS_PATH` — optional path to a TOML file with machine-specific overrides (see `sorter/backend/irl/example_configs/machine_specific_params_example.toml` for an example)

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
