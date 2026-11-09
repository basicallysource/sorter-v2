# Sorter Interface Firmware

This firmware implements an universal hardware interface for use on a sorting machine. It is configurable to match the available hardware of each node. 

The firmware is designed to run on a Raspberry Pi Pico (RP2040) microcontroller and provides real-time control of stepper motors, communication with TMC2209 stepper drivers via UART, and a modular message/command processing system for interfacing with a host system.

## Directory Structure
- `Stepper.*` — Stepper motor control logic
- `TMC2209.*` — TMC2209 stepper driver abstraction
- `TMC_UART.*` — UART communication with TMC drivers
- `ServoBus.*`, `servo_bus.pio` — Serial bus servos on one open-drain pin
- `ServoGuard.*`, `ServoWire.h` — Watches serial servos while they move, and stops one that meets resistance
- `test/` — Desk tests that need no board
- `HostLink.*`, `host_link.pio` — UART link to the host on two pins (v1.5)
- `message.*` — Message and command processing
- `cobs.*`, `crc.*` — Communication utilities
- `build/` — Build output directory

## Build Instructions
It is recommended to open this project using Visual Studio Code with the RP2040 SDK extension, which will handle building and flashing the firmware for you. However, if you prefer to use the command line, you can build and load the firmware manually with the following steps:
1. Install the Raspberry Pi Pico SDK and toolchain.
2. Create a `build/` directory and run CMake:
    ```sh
    mkdir build
    cd build
    cmake ..
    ninja
    ```
3. If this is the first time loading the firmware into the Pico, you need to reset the board in BOOTSEL mode by holding the BOOTSEL button while plugging it into your computer. This will mount the Pico as a USB drive.
4. Flash the generated `.uf2` file to your Pico board using picotool or by copying it to the mounted USB drive.
    ```sh
    picotool load -f sorter_interface_firmware.uf2
    ```

## Custom Build Options

You can customize the firmware build using CMake options:

- `HW_SKR_PICO`: Enable compilation for SKR Pico hardware (default: OFF)
- `FIRMWARE_ROLE`: Select logical actuator naming profile (`feeder` or `distribution`, default: `feeder`)
- `INIT_DEVICE_NAME`: Set the initial device name (defaults to `FEEDER MB` for `feeder` role and `DISTRIBUTION MB` for `distribution` role)
- `INIT_DEVICE_ADDRESS`: Set the initial device address (default: 0x42)

To use these options, pass them as `-D` arguments to CMake. For example:

```sh
cmake -DHW_SKR_PICO=ON -DFIRMWARE_ROLE=distribution -DINIT_DEVICE_NAME="DISTRIBUTOR" -DINIT_DEVICE_ADDRESS=0x01 ..
```

This will enable SKR Pico hardware support, use the `distribution` naming profile, set the device name to "DISTRIBUTOR", and the device address to 0x01.

## Building Two Firmware Variants (Feeder + Distribution)

Use separate build directories so each Pico can run the same firmware codebase with different logical actuator names.

### Feeder firmware
```sh
mkdir -p build-feeder
cd build-feeder
cmake -DFIRMWARE_ROLE=feeder -DINIT_DEVICE_NAME="FEEDER MB" ..
ninja
```

### Distribution firmware
```sh
mkdir -p build-distribution
cd build-distribution
cmake -DFIRMWARE_ROLE=distribution -DINIT_DEVICE_NAME="DISTRIBUTION MB" ..
ninja
```

Both variants keep the same physical channel wiring but advertise different `stepper_names` in detect JSON, letting the client bind actuators by role-specific names.

## Serial Servo Bus (`SERVO_BUS` commands)

The v1.5 board (`make build-distribution-v1-5`) drives Feetech SC serial bus servos on one half-duplex line instead of PWM servos through a PCA9685. It runs at 1 Mbps, 8N1. The firmware only ever pulls the line low or releases it, and never drives it high. `GET_OBSERVABILITY` reports `"servo_bus":true` on a board with a bus. Other boards answer these commands with "Invalid command", and `SERVO_COUNT` is 0 on v1.5, so the PWM servo commands answer "Invalid channel" there.

The channel byte is the servo's ID, 0 to 254, and 254 is broadcast. A wait for a servo that does not answer costs about 2 ms.

| Command | Payload | Reply |
|---|---|---|
| `0x50 PING` | none | `[status u8]` |
| `0x51 READ` | `[address u8, count u8]`, count 1 to 64 | `[status u8, data...]`, count data bytes |
| `0x52 WRITE` | `[address u8, data...]`, 1 to 64 data bytes | `[status u8]` |

`status` is the servo's status (error) byte. A write to ID 254 waits for no answer and its status is 0. Bad lengths get an error reply saying so. When no good answer comes, the reply is an error (the `0x80` bit set on the command) whose text begins with what went wrong:

- `No reply from servo N`: silence. No servo has that ID.
- `Garbled reply from servo N`: bytes came back that are no packet. Two servos share the ID and answer over each other (new servos all come as ID 1), or the line is noisy.
- `Servo bus line is stuck (servo N)`: the line did not carry what the board sent. It is held low or shorted.

### Guarded moves (`MOVE`, `PROBE`, `STATE`, `STOP`)

A servo that pushes against something it cannot move draws its stall current until something lets go, and a host can be busy for longer than that takes. So the board watches the servos it is asked to move (`ServoGuard`). `GET_OBSERVABILITY` reports `"servo_guard":true` when these commands exist.

| Command | Payload | Reply |
|---|---|---|
| `0x53 MOVE` | `<BHHHBHHBBHH`: flags, goal, time ms, speed, acceleration, stall load, stall ms, flat, arrived, back-off, timeout ms | none |
| `0x54 STATE` | none | `<BHhHHH`: state, position, load, mark, peak load, elapsed ms |
| `0x55 PROBE` | `<BbBBHHHH`: flags, direction, step, period ms, limit, lag, load, back-off | none |
| `0x56 STOP` | `[release u8]` | none |

Positions are the servo's own counts. Flags: bit 0 is the SC series (big-endian registers, a goal with a time; without it the STS series, a goal with a speed and an acceleration), bit 1 lets the servo go when it arrives, bit 2 lets it go once it has backed off or been stopped short.

- **`MOVE`** writes the goal, turns the torque on and reads the servo every 10 ms. Within `arrived` counts of the goal it has arrived. Loaded past `stall load` (0 to 1000) while moving less than `flat` counts, for `stall ms`, it has stalled: the board sends it `back-off` counts back the way it came (never past where it started) and reports where it stalled. The servo's own overload flag counts as a stall at once. Past `timeout ms` it is stopped where it is.
- **`PROBE`** finds an end of travel without pushing hard. The torque comes on with the goal where the servo already is; then the goal creeps `step` counts every `period ms` toward `limit` (`direction` +1 for higher counts, -1 for lower). When the servo falls `lag` counts behind its goal, or its load passes `load`, on two readings in a row, something holds it: the board backs it off and reports where.
- **`STATE`** is what the board knows of that servo. States: 0 idle (not watched), 1 moving, 2 arrived, 3 stalled, 4 timed out, 5 lost (it stopped answering), 6 probing, 7 contact (a probe met resistance; `mark` is where), 8 no contact (a probe reached its limit). `mark` is where it stalled or met resistance, `peak load` the most load since it began.
- **`STOP`** ends the watch and stops the servo: `release` 1 lets it go, 0 holds it where it is. With ID 254 it lets every servo go.

A `WRITE` to a watched servo ends its watch: the host has taken it over. The board watches up to 8 servos at once; a ninth that is still moving is refused with `Servo guard is full (servo N)`.

`make test-servo-guard` runs the guard's logic on a desk against pretend servos, with no board.

## Host Link (v1.5)

The v1.5 board sits on the host's header, and the host can talk to it there instead of over USB: a UART at 1.5 Mbps, 8N1, through the board's isolator, with GP7 sending and GP19 receiving. The commands, framing and replies are the same as over USB, and a reply goes back the way its command came. USB keeps working beside it. On an Orange Pi 5 the link is UART0 (`overlays=uart0-m2`, header pins 8 and 10, `/dev/ttyS0`), and header pin 15 high holds the Pico in reset, so drive it low.

The RP2040 takes new firmware only over USB, so a flash needs the board's USB port plugged into the host. `GET_OBSERVABILITY` reports the microcontroller's serial number as `"uid"`, the same one its USB port gives, so a host that reaches the board both ways knows it is one board: it uses it over one link, and flashes it over USB.

## Code Style
- Follows LLVM style (see `.clang-format`).
- 4-space indentation, 120-column limit.

## License
MIT License. See source files for details.
