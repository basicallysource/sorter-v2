# Local Machine Setup — Pico 2 W Breadboard (Feeder + Classification)

**Machine owner:** mattm0802@gmail.com
**Host:** macOS (Apple Silicon), MacBook
**Last updated:** 2026-06-23
**Branch carrying these changes:** `claude/epic-hypatia-7o2am2`

> Purpose: record every way this local machine deviates from a "standard"
> Sorter V2 install, so the setup can be reproduced on a fresh clone and so the
> wider dev team can see this machine's status and condition.

---

## 1. Executive summary

This machine is a **bring-up / development rig**, not a full production sorter. It
runs the **feeder + classification** subsystems only, on a single
**Raspberry Pi Pico 2 W (RP2350)** on a breadboard, driving **three NEMA 17
motors** via three TMC2209 drivers in **STEP/DIR standalone mode**. Vision runs
on the Mac via **ONNX** instead of the RK3588 NPU. There is **no distribution
subsystem, no carousel transport, and no C1 bulk channel** (yet).

What works today:
- Firmware ↔ backend handshake over USB.
- Software-driven motion on C2, C3, C4 (jogged from the web UI).
- Full backend running with ONNX perception and 3 live camera feeds.
- Web UI (SvelteKit/Vite) on `:5173` talking to the backend API on `:8000`.

Not yet done (next cycle): detection-zone calibration, C4 spoke-home
calibration, swapping in a newer detection model, restart stability.

---

## 2. Hardware: this machine vs. a standard build

| Aspect | Standard build | This machine |
|---|---|---|
| Compute | Orange Pi 5 (RK3588) | MacBook (macOS, Apple Silicon) |
| Inference | RK3588 NPU (rknnlite) | CPU via `onnxruntime` |
| MCU boards | Feeder MCU PCB + Distribution MCU PCB | One Pico 2 W (RP2350) on a breadboard |
| Stepper drivers | TMC2209 over **UART** (software current/microstep/StallGuard) | TMC2209 in **STEP/DIR standalone** (no UART wired) |
| Channels | C1 (bulk) + C2 + C3 + C4 (classification) + distribution chute | **C2, C3, C4 only** (C1 reserved, no distribution) |
| Motor current | Set in software over UART | Set **by hand via each driver's VREF pot** |
| Microstepping | Set in software | **Fixed 1/8** by MS1/MS2 straps to GND |
| StallGuard / DIAG | Wired, used for stall detection | **Not wired, disabled** |
| Endstops / home pins | Wired (chute/carousel homing) | None wired (C4 uses optical spoke-home, calibrated later) |
| Servos (PCA9685) | Present | Not present (run with `--disable servos`) |

### 2.1 Wiring (from `three_motor_wiring_reference.html`)

Three BTT TMC2209, STEP/DIR mode, MS1/MS2 → GND (1/8 microstep), 24 V (MeanWell)
to driver VS, common ground tied across Pico / drivers / PSU.

| Motor | Channel | STEP | DIR | EN (active-low) | TMC addr |
|---|---|---|---|---|---|
| Motor 1 | C2 | GP2 | GP3 | GP4 | (UART not wired) |
| Motor 2 | C3 | GP5 | GP6 | GP7 | (UART not wired) |
| Motor 3 | C4 (classification) | GP8 | GP9 | GP10 | (UART not wired) |
| *(reserved)* | C1 (bulk) | GP11 | GP12 | GP13 | — |

Cameras (USB, macOS AVFoundation ordinals):
- C2 → index `0` (USB Camera)
- C3 → index `1` (USB Camera)
- C4 classification → index `2` (HD Pro Webcam C920)
- index `3` (FaceTime built-in) — unused

---

## 3. Code changes (committed on `claude/epic-hypatia-7o2am2`)

Seven commits; 11 files. Grouped by purpose.

### 3.1 Firmware — new Pico 2 W breadboard target
- **`software/firmware/sorter_interface_firmware/hwcfg_pico2w_breadboard.h`** *(new)*
  Board config for this rig: 3 steppers named `second_c_channel_rotor` (C2),
  `third_c_channel_rotor` (C3), `carousel` (C4); STEP/DIR/EN pins per the table
  above; DIAG disabled (`-1`); UART + I2C pointed at unused GPIOs (nothing wired
  there). Reserved C1 pins (GP11/12/13) documented inline with the exact edits to
  enable a 4th stepper later.
- **`CMakeLists.txt`** — added `HW_PICO2W_BREADBOARD` option, `FIRMWARE_VARIANT`
  branch, and compile definition (mirrors the existing `HW_BASICALLY_*` pattern).
- **`sorter_interface_firmware.cpp`** — added the `#elif defined(HW_PICO2W_BREADBOARD)`
  hwcfg dispatch and updated the no-config `#error` message.

> Build note: the board is RP2350, so CMake **must** be configured with
> `-DPICO_BOARD=pico2_w`, otherwise the SDK builds an RP2040 binary that won't run.
> (See §5 for the full build command.) UART config writes at firmware init are
> harmless no-ops because `uart_write_blocking` never waits for a reply and nothing
> is connected to the drivers' PDN_UART.

### 3.2 Backend — macOS / ONNX / reduced-rig support
- **`perception/runtime.py`** — added `OnnxYoloRuntime` (+ `_nms` helper): CPU ONNX
  inference for non-RK3588 hosts. Accepts `core_mask_name` as a no-op for API
  parity.
- **`main.py`** — `_maybeStartPerception()` detects platform and injects
  `OnnxYoloRuntime` off-RK3588 (production RK3588 still uses `RknnYoloRuntime`).
  Startup log now reports `runtime=onnx|rknn`.
- **`irl/config.py`** — (a) distribution board is now **optional**: when absent,
  log a warning and set `irl.chute = None` instead of raising. (b)
  `_requiredCanonicalStepperNames` now honors `--disable chute / c_channel_N /
  carousel` so a disabled subsystem isn't treated as required hardware.
- **`subsystems/distribution/state_machine.py`** — `step()` early-returns when
  `chute is None`, so distribution stays IDLE with no board.
- **`hardware/bus.py`** — `enumerate_buses()` now accepts both Pico-SDK CDC PIDs:
  `0x000A` (RP2040) **and `0x0009` (RP2350 / Pico 2 W)**. Without this the board
  was never discovered.
- **`machine_platform/control_board.py`** — a feeder board reporting a **subset**
  of the known feeder steppers (e.g. C2/C3/C4 with no C1) is now recognized as a
  feeder with proper canonical names, instead of falling through to the generic
  identity mapping (which left `second_c_channel_rotor` un-canonicalized and made
  discovery report C2/C3 as "missing").
- **`vision/camera.py`** — the macOS camera availability gate now accepts the bare
  AVFoundation ordinal (`0–3`) as well as the offset registry index (`1200+`),
  matching the open path. `cv2-enumerate-cameras` reports `1200+ordinal`, but
  modern OpenCV's `VideoCapture(idx, CAP_AVFOUNDATION)` only accepts the bare
  ordinal, so the gate was rejecting the indices that actually open.

### 3.3 Tooling
- **`scripts/jog_test.py`** *(new)* — minimal stepper jog over the firmware
  protocol (pyserial only, no full backend). Bring-up/diagnostic helper.

> None of these changes alter production (RK3588) behavior: the RKNN runtime is
> still the default, the distribution guard only triggers when no board is present,
> the PID set is a superset, and the camera-gate / discovery changes are additive.

---

## 4. Configuration files (local, not committed)

### 4.1 `software/.env`
Loaded by `main.py` from `Path(__file__).parents[2] / ".env"` (i.e.
`software/.env` — **not** `software/sorter/.env`).
```env
MACHINE_SPECIFIC_PARAMS_PATH=/Users/moranm1/PycharmProjects/sorter-v2-clean/software/sorter/machine.toml
DISABLE_STALLGUARD=1
```

### 4.2 `software/sorter/machine.toml`
```toml
[machine_setup]
type = "classification_channel"     # feeder + C4 classification, no carousel transport, no distribution

[feeder]
mode = "go_to_angle_rev01"          # Rev04 feeder (also the default)

[classification_channel]
mode = "simple_state_machine_rev01" # Rev04 classification (also the default)

[cameras]
layout = "split_feeder"
c_channel_2 = 0                      # bare AVFoundation ordinals (not the 1200+ form)
c_channel_3 = 1
classification_channel = 2

[stepper_bindings]
c_channel_2 = "second_c_channel_rotor"
c_channel_3 = "third_c_channel_rotor"
carousel    = "carousel"

# Operating direction should be clockwise. Uncomment per channel once the
# assembled rotor direction is confirmed (no reflash needed):
# [stepper_direction_inverts]
# c_channel_2 = true
# c_channel_3 = true
# carousel    = true
```

---

## 5. Reproduce on a fresh clone (checklist)

1. **Clone + branch:** check out `claude/epic-hypatia-7o2am2` (carries all code changes).
2. **Build firmware** (RP2350!):
   ```sh
   cd software/firmware/sorter_interface_firmware
   mkdir -p build-pico2w && cd build-pico2w
   cmake -G Ninja -DPICO_BOARD=pico2_w -DHW_PICO2W_BREADBOARD=ON \
         -DFIRMWARE_ROLE=feeder -DINIT_DEVICE_NAME="FEEDER MB" ..
   ninja
   ```
   Flash `sorter_interface_firmware.uf2` via BOOTSEL.
3. **Set the VREF current pot on each driver** (hardware step; not software).
4. **Backend deps:** `cd software/sorter/backend && uv sync`.
5. **Create config:** `software/.env` and `software/sorter/machine.toml` (§4).
6. **Launch backend:**
   ```sh
   DEBUG_LEVEL=2 uv run python main.py --disable servos --disable chute --disable c_channel_1
   ```
7. **Frontend:** `cd software/sorter/frontend && npm install && npm run dev` → http://localhost:5173
8. **In the UI:** Start/Home (steppers come online), then calibrate (§7).

### macOS host gotchas encountered
- **Xcode Command Line Tools** had to be reinstalled; also needed
  `export SDKROOT="$(xcrun --show-sdk-path)"` was *not* sufficient — a clean CLT
  reinstall fixed missing C++ headers when building the Pico host tool `pioasm`.
- **Pico SDK 2.x** required for RP2350; `PICO_BOARD=pico2_w` is mandatory.
- **Camera permissions:** macOS prompts the first time the terminal/PyCharm opens a
  camera; must be allowed or `VideoCapture` fails.
- **Build tools:** `brew install cmake ninja uv node` + `gcc-arm-embedded` cask.

---

## 6. Runtime bypasses / workarounds (and why)

| Bypass | Mechanism | Reason |
|---|---|---|
| Servos off | `--disable servos` | No PCA9685 servo board present |
| Distribution off | `--disable chute` + distribution-optional code | No distribution MCU board |
| C1 off | `--disable c_channel_1` | C1 bulk motor not installed yet |
| StallGuard off | `DISABLE_STALLGUARD=1` | DIAG pins not wired (STEP/DIR standalone) |
| Motor current | VREF pot per driver | No UART to set current in software |
| Microstepping | Fixed 1/8 (MS straps) | No UART to set microsteps in software |
| Inference | ONNX (`OnnxYoloRuntime`) | No RK3588 NPU on macOS |
| Verbose logs | `DEBUG_LEVEL=2` | Default `0` suppresses info/warn on console |

> The three `--disable` flags must be passed on every launch (see "open items").

---

## 7. Remaining one-time calibration (next cycle)

Done through the web UI; required before the sorting pipeline detects anything:
1. Assign the detection algorithm (`c-chamber-combined-yolo11s-320`, or the newer
   model once swapped in) to each channel.
2. Draw the detection-zone polygons for C2, C3, C4. Until then,
   `Perception … channels=[]` is expected.
3. Calibrate the C4 spoke-home arc geometry (optical homing for the classification
   rotor).
4. Confirm rotor directions; set `[stepper_direction_inverts]` for clockwise.

---

## 8. Current status report (for the dev team)

**Condition: functional development rig; feeder/classification motion proven, vision not yet calibrated.**

- ✅ Custom RP2350 firmware builds & flashes; board enumerates as `FEEDER MB` with
  steppers `[second_c_channel_rotor, third_c_channel_rotor, carousel]`.
- ✅ Backend discovers/binds C2, C3, C4 and jogs them from the UI.
- ✅ ONNX perception service starts; all three USB cameras stream.
- ⏳ Detection zones / algorithm assignment / C4 spoke-home: not yet calibrated.
- ⏳ Restart stability not yet exercised.
- 🔜 Plan to replace the bundled `c-chamber-combined-yolo11s-320` ONNX model with a
  newer export (verify output tensor shape against `OnnxYoloRuntime`'s parser).

### Open items / questions for the team
1. **Launch flags as config.** The `--disable servos/chute/c_channel_1` flags are
   passed manually every start. Worth a machine.toml/`.env` way to declare absent
   subsystems so discovery requirements derive from config rather than CLI?
2. **Camera index forms.** `cv2-enumerate-cameras` returns `1200+ordinal` on this
   macOS/OpenCV combo while `VideoCapture(idx, CAP_AVFOUNDATION)` wants the bare
   ordinal — the availability gate was the only place that assumed the offset form.
   Worth auditing other camera-index call sites for the same assumption.
3. **Feeder subset profile.** Discovery now accepts a feeder reporting a subset of
   the known steppers; confirm this is acceptable upstream vs. a dedicated board
   profile / HW_ID-based detection.
4. **Model export shape.** `OnnxYoloRuntime` assumes the ultralytics YOLO11 export
   layout `(1, num_classes+4, 8400)`; the newer model must match or the parser
   needs updating.

---

## 9. Change inventory (commits)

```
14c6e5c hardware discovery: support reduced feeder rig (C2/C3/C4, no chute/C1)
de33944 vision/camera: accept bare AVFoundation ordinals in macOS availability gate
995dfb6 scripts: add minimal stepper jog test (firmware protocol, pyserial only)
6ee388e hardware/bus: discover RP2350 (Pico 2 W) boards by USB PID 0x0009
954266b firmware: map 3 breadboard motors to C2/C3/C4, reserve C1 pins
2c911a2 firmware: fill in real Pico 2W breadboard pins (3 motors, STEP/DIR)
049a383 feeder + classification on Pico 2W breadboard (macOS/ONNX)
```
