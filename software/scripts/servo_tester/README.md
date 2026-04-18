# servo tester

Little htmx web UI to poke all 16 servos **and all TMC2209 steppers** on a Distribution / Feeder board over USB.

## setup

```sh
cd software/scripts/servo_tester
uv sync
```

## firmware

The board must be running `sorter_interface_firmware` with PCA9685 detected. Either role (`feeder` or `distribution`) works — this tool only uses servo commands, which are role-independent. If your Pico is labelled "feeder" it's already correct; nothing to re-flash.

If you need to build the firmware:

```sh
cd software/firmware/sorter_interface_firmware
make build-feeder
make flash-feeder   # Pico in BOOTSEL, mounted as /Volumes/RPI-RP2
```

## run

```sh
uv run python main.py
```

Opens on http://127.0.0.1:8765. Auto-connects to the first Pico it finds (VID 0x2E8A / PID 0x000A).

Flags:

- `--port /dev/cu.usbmodem...` — pick a specific serial port
- `--host 0.0.0.0 --http-port 8080` — bind elsewhere
- `--no-autoconnect` — skip auto-connect (use the UI to connect)

## what it does

- Lists every servo channel the firmware reports (up to 16 via the PCA9685).
- Per servo: slider 0–180°, enable / disable / stop / read-position, "release" checkbox for `move_to_and_release`.
- Lists every stepper channel the firmware reports (`stepper_count` in the init payload).
- Per stepper: steps input with `+` / `-` buttons, enable / disable / stop / read-position.
- Global controls: servo duty limits (µs) / speed / accel / disable-all; stepper speed limits / accel / current / microsteps / disable-all.

Defaults for standard 180° hobby servos: 500–2500µs duty limits. Override in the UI if your servo uses a different pulse range.

## 5th stepper (rev 1.0 Distribution / Feeder MB)

The default `hwcfg_basically.h` in this repo now declares `STEPPER_COUNT = 5`, adding channel 4 on `STEP=GPIO8`, `DIR=GPIO7` (board reference A6). Important caveat: A6's TMC2209 actually lives on a separate UART bus (`uart1` on GPIO4/5) on the rev 1.0 PCB, but the current firmware routes all drivers onto `uart0` (GPIO16/17). That means:

- **STEP/DIR works** (move_steps / move_at_speed will drive it) as long as the A6 driver is externally enabled.
- **UART config (SET_CURRENT / SET_MICROSTEPS / SET_ENABLED) will not reach A6** until the firmware is extended to manage the second UART bus. Driver defaults from power-on are used.
- A6's `~EN` is tied to GPIO0 (shared with the other four), so the global enable pin still disables all five drivers together.

Build + flash after pulling this change:

```sh
cd software/firmware/sorter_interface_firmware
make build-feeder
make flash-feeder
```
