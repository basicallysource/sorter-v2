# Sorter — software

The sorter runs as a single **headless station server**: one process serves the web UI **and**
the control/vision API on `http://<host>:8000`. You drive everything — camera assignment,
polygon drawing, baseline calibration, and running the sorter — from a browser on any device on
the LAN. Nothing needs to be typed on the machine after it's started.

Classification is done via the **Brickognize cloud API** — there are no local ML models to
download.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager (installs Python 3.13+ on first run)
- [Node.js](https://nodejs.org/) v22+ and npm — to build the web UI
- [Git LFS](https://git-lfs.github.com/) — for `parts_with_categories.json`
- Linux/V4L2 (the camera stack is Linux-only)
- [Raspberry Pi Pico SDK](https://github.com/raspberrypi/pico-sdk) — only if you build firmware

## Setup

```bash
git lfs install
git clone https://github.com/basicallysource/sorter-v2.git
cd sorter-v2/software
git lfs pull                      # fetch parts_with_categories.json (not a tiny pointer)

cp .env.example .env              # then edit absolute paths (CONFIG_DIR, sorting profile, ...)

cd ui && npm install && npm run build && cd ..   # build the SPA the server serves
```

Make sure the user can access the hardware: cameras need the `video` group and the Picos need
the `dialout` group (`sudo usermod -aG dialout,video $USER`, then re-login).

## Firmware (optional)

Build and flash `sorter_interface_firmware` for each Raspberry Pi Pico. See
[firmware/sorter_interface_firmware/README.md](firmware/sorter_interface_firmware/README.md)
for role-based build variants (feeder vs distribution).

```bash
cd firmware/sorter_interface_firmware
mkdir -p build && cd build
cmake -DFIRMWARE_ROLE=feeder ..
ninja
picotool load -f sorter_interface_firmware.uf2
```

## Run

```bash
cd client
uv run python app.py
```

`uv` installs Python + dependencies on first run; `.env` is loaded automatically. The server
prints its address and serves on `0.0.0.0:8000`. From any device on the LAN open:

```
http://<host>.local:8000
```

The station boots **idle** and owns no hardware until you start a run. Ctrl-C (or `systemctl
stop`) shuts down cleanly, releasing cameras, Picos, and motors.

## First-time calibration (all in the browser)

Open the UI and go to **Setup & Calibration**. Complete the steps in order — each unlocks the
next, and the **Activate Sorter** button enables once all are done:

1. **Assign cameras** — preview each camera and tag it as `c_channel_2`, `c_channel_3`,
   `classification`, or `carousel`.
2. **Draw polygons** — outline the channel regions and the classification region over the live
   feeds.
3. **Capture baseline** — the "wiggle": rotates the carousel while vibrating the chute to record
   the HSV detection envelope (chute frequency/amplitude are adjustable, live).

Then **Activate Sorter** on the Setup page (powers up the machine); run/operate it from the main
dashboard.

On startup the station discovers connected Pico devices over USB serial, scans each bus for
SorterInterface firmware, and binds steppers/servos to logical roles (carousel, chute, rotors)
by firmware-reported name.

## Boot autostart + LAN name

For a true appliance — boots straight into serving the UI — install the station as a systemd
service and use mDNS (`avahi`) so it's reachable at `http://<host>.local:8000`. (Setup script
to come.)

## Persistent state

All machine state (camera assignment, polygons, aruco config, baselines, machine id) is stored
under `CONFIG_DIR` so it survives re-cloning the repo.
