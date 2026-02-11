# Setup

## Prerequisites

- [Git](https://git-scm.com/) with [Git LFS](https://git-lfs.github.com/)
- [Node.js](https://nodejs.org/) (v20+) and npm
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Arduino IDE](https://www.arduino.cc/en/software)

## Clone

```bash
git lfs install
git clone https://github.com/basicallysource/sorter-v2.git
cd sorter-v2/software
```

Git LFS files (models, `parts_with_categories.json`) should download automatically. If not, run `git lfs pull`. You can verify by checking that `software/models/` contains `.pt` files (not small text pointers).

## Firmware

Open `firmware/feeder/feeder.ino` in the Arduino IDE. Select **Arduino Mega 2560** as the board (with RAMPS 1.4 shield). Upload.

## Environment

```bash
cp .env.example .env
```

To find the addresses for your webcams, run the following from `client/`. You will use them in your environment file in the next step.
```
uv run python ../scripts/webcam_discovery.py
```

Edit `.env` and update:
- `CLASSIFICATION_CHAMBER_MODEL_PATH`, `FEEDER_MODEL_PATH`, `PARTS_WITH_CATEGORIES_FILE_PATH` — set these to the absolute paths where the repo was cloned (the files are pulled via Git LFS)
- `FEEDER_CAMERA_INDEX`, `CLASSIFICATION_CAMERA_BOTTOM_INDEX`, `CLASSIFICATION_CAMERA_TOP_INDEX` — webcam device indices. 
- Arduino serial port is auto-detected. On Mac/Linux it shows up as `/dev/ttyUSB*` or `/dev/ttyACM*`. On Windows it will be a `COM` port (e.g. `COM3`).

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

On startup, the client will prompt you to select the MCU (Arduino Mega with RAMPS shield) connected over USB.

**Windows**: Run PowerShell as Administrator to access serial ports.
