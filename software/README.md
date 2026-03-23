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

Run camera setup from `client/`. A window will open showing each camera — press **F**, **B**, or **T** to assign it as feeder, classification bottom, or classification top. Press **N** to skip, **Q** to quit and save.
```bash
cd client
uv run python scripts/camera_setup.py
```



## UI Dependencies

```bash
cd ui
npm install
```

---

# Running

You'll need two terminal tabs, both from `sorter-v2/software`.

## Terminal 1: UI

```bash
cd ui
npm run dev
```

## Terminal 2: Client

```bash
cd client
uv run python main.py
```

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
- [client/ARUCO_GUI_USAGE.md](client/ARUCO_GUI_USAGE.md) — Web-based ArUco tag calibration GUI
- [firmware/sorter_interface_firmware/README.md](firmware/sorter_interface_firmware/README.md) — Firmware build options and flashing
