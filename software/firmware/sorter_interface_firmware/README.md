# Sorter Interface Firmware

This firmware implements an universal hardware interface for use on a sorting machine. It is configurable to match the available hardware of each node. 

The firmware is designed to run on a Raspberry Pi Pico (RP2040) microcontroller and provides real-time control of stepper motors, communication with TMC2209 stepper drivers via UART, and a modular message/command processing system for interfacing with a host system.

## Directory Structure
- `Stepper.*` — Stepper motor control logic
- `TMC2209.*` — TMC2209 stepper driver abstraction
- `TMC_UART.*` — UART communication with TMC drivers
- `ServoBus.*`, `servo_bus.pio` — Serial bus servos on one open-drain pin
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

`status` is the servo's status (error) byte. A write to ID 254 waits for no answer and its status is 0. If a servo does not answer, or its packet is bad, the reply is an error (the `0x80` bit set on the command) with the text `No reply from servo N`. Bad lengths get an error reply saying so.

## Code Style
- Follows LLVM style (see `.clang-format`).
- 4-space indentation, 120-column limit.

## License
MIT License. See source files for details.
