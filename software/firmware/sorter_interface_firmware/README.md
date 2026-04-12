# Sorter Interface Firmware

This firmware implements an universal hardware interface for use on a sorting machine. It is configurable to match the available hardware of each node. 

The firmware is designed to run on a Raspberry Pi Pico (RP2040) microcontroller and provides real-time control of stepper motors, communication with TMC2209 stepper drivers via UART, and a modular message/command processing system for interfacing with a host system.

## Directory Structure
- `Stepper.*` — Stepper motor control logic
- `TMC2209.*` — TMC2209 stepper driver abstraction
- `TMC_UART.*` — UART communication with TMC drivers
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
make -j$(nproc)
```

### Distribution firmware
```sh
mkdir -p build-distribution
cd build-distribution
cmake -DFIRMWARE_ROLE=distribution -DINIT_DEVICE_NAME="DISTRIBUTION MB" ..
make -j$(nproc)
```

Both variants keep the same physical channel wiring but advertise different `stepper_names` in detect JSON, letting the client bind actuators by role-specific names.

## Code Style
- Follows LLVM style (see `.clang-format`).
- 4-space indentation, 120-column limit.

## License
MIT License. See source files for details.
