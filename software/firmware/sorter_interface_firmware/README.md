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
- `INIT_DEVICE_NAME`: Set the initial device name (default: "DefaultDevice")
- `INIT_DEVICE_ADDRESS`: Set the initial device address (default: 0x42)

To use these options, pass them as `-D` arguments to CMake. For example:

```sh
cmake -DHW_SKR_PICO=ON -DINIT_DEVICE_NAME="DISTRIBUTOR" -DINIT_DEVICE_ADDRESS=0x01 ..
```

This will enable SKR Pico hardware support, set the device name to "DISTRIBUTOR", and the device address to 0x01.

## Code Style
- Follows LLVM style (see `.clang-format`).
- 4-space indentation, 120-column limit.

## License
MIT License. See source files for details.
