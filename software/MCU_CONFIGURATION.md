# MCU Configuration Guide

This guide explains how to configure and use either an Arduino Mega or Raspberry Pi Pico with the sorter firmware.

## Default: Arduino Mega 2560 with RAMPS 1.4

The system defaults to the Arduino Mega 2560. Follow the original README instructions:

1. **Upload Firmware**
   ```bash
   # Open firmware/feeder/feeder.ino in Arduino IDE
   # Select Board: Arduino Mega 2560
   # Upload
   ```

2. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env (Arduino is already the default MCU_TYPE)
   ```

3. **Run**
   ```bash
   cd ui && npm run dev     # Terminal 1
   cd client && uv run python main.py  # Terminal 2
   ```

---

## Alternative: Raspberry Pi Pico

To use an RPi Pico instead of Arduino:

### Hardware Setup

1. **Flash Pico Firmware**
   - Build and upload `firmware/sorter_interface_firmware/` to your RPi Pico
   - See `firmware/sorter_interface_firmware/README.md` for build instructions

2. **Connection**
   - Connect RPi Pico to your computer via USB
   - The Pico should enumerate as a serial device (e.g., `/dev/ttyACM0` on Linux/Mac, `COM3` on Windows)

### Software Configuration

1. **Update .env**
   ```bash
   cp .env.example .env
   # Edit .env and set:
   export MCU_TYPE="rpi_pico"
   ```

### Pin Mapping Configuration

The `PicoMCU` class **automatically detects and configures pin mappings** by parsing the firmware hardware configuration files. No manual configuration needed!

On startup, it looks for:
1. `firmware/sorter_interface_firmware/hwcfg_skr_pico.h` (preferred)
2. `firmware/sorter_interface_firmware/hwcfg_basically.h` (fallback)

**Example startup log:**
```
Pico interface initialized: SorterInterface_0
Auto-detected Pico pin configuration from firmware
```

If auto-detection fails, the system falls back to hardcoded RAMPS 1.4 mappings with a warning.

For detailed information about auto-detection, including troubleshooting and how to support new hardware configurations, see [PICO_PIN_AUTO_DETECTION.md](PICO_PIN_AUTO_DETECTION.md).

#### Manual Override (if needed)

Edit `client/irl/mcu_pico.py` `__init__` method to set custom mappings:

```python
self._stepper_pin_map = {
    (your_step_pin, your_dir_pin): stepper_channel,
    ...
}
self._enable_pin_to_stepper = {
    enable_pin: (step_pin, dir_pin),
    ...
}
```

3. **Run**
   ```bash
   cd ui && npm run dev     # Terminal 1
   cd client && uv run python main.py  # Terminal 2
   ```

---

## Configuration Options

### MCU_TYPE Environment Variable

Set in `.env`:
```bash
# Use Arduino Mega 2560 (default)
export MCU_TYPE="arduino"

# Use Raspberry Pi Pico
export MCU_TYPE="rpi_pico"
```

### Auto-Detection

- **Arduino**: Auto-detects via serial communication
- **RPi Pico**: Auto-detects using Vendor ID (0x2E8A) and Product ID (0x000A)

Both types support manual device selection if auto-detection fails.

---

## Differences Between Systems

| Feature | Arduino | RPi Pico |
|---------|---------|----------|
| Protocol | Text-based serial | Binary COBS protocol |
| Baud Rate | 115200 | 576000 (default) |
| Multi-device Support | Limited (single device) | Full support via I²C bus |
| Firmware | Simple Arduino sketch | Complex C++/CMake project |
| Power Requirements | Moderate | Low |
| Cost | Higher | Lower |

## Design Details

### Arduino Implementation
Uses text-based serial commands at 115200 baud. Each pin is controlled individually:
- `P` command: Configure pin as input/output
- `D` command: Write digital value to pin (including enable pins)
- `T` command: Perform stepper move with trapezoid acceleration profile

### RPi Pico Implementation  
Uses binary COBS protocol at 576000 baud with high-level `SorterInterface` abstraction:
- Pico MCU wrapper **ignores individual pin control** - pins are managed by Pico firmware
- Enable/disable state is **tracked for compatibility** but not applied to pins
- Stepper moves route directly to `SorterInterface.StepperMotor` high-level commands
- Multiple steppers **share the same enable pin** without conflicts

This design eliminates the "shared enable pin" problem: instead of trying to manage individual pins that may be shared, the Pico implementation uses high-level motor commands that the firmware handles internally.

### Arduino Issues
- Ensure Arduino IDE has board selected: Board Manager → Arduino Mega 2560
- Check serial port in `.env` if auto-detection fails
- Common ports: `/dev/ttyUSB0` (Linux), `/dev/ttyACM0` (Mac), `COM3` (Windows)

### RPi Pico Issues
- Verify Pico firmware is built and uploaded correctly
- Check if Pico appears in device list: `ls /dev/ttyACM*` (Linux/Mac)
- If auto-detection fails, set `MCU_PATH` in `.env` manually
- Check baud rate compatibility if experiencing communication errors

### General Issues
- Always close the previous terminal session before switching MCU types
- Clear serial buffers if switching between devices: unplug and replug USB

---

## Hardware Pin Reference

### RAMPS 1.4 on Arduino Mega 2560

The system uses the following pin mapping:

**Stepper Control:**
- Carousel: Step=36, DIR=34, Enable=30
- Chute: Step=26, DIR=28, Enable=24
- First classifier rotor: Step=46, DIR=48, Enable=62
- Second classifier rotor: Step=60, DIR=61, Enable=56
- Third classifier rotor: Step=54, DIR=55, Enable=38

**Digital I/O:**
- Additional pins configured as needed for sensors and switches

### RPi Pico Mapping

The `PicoMCU` class maps Arduino pins to Pico channels in:
- `_get_output_channel_for_pin()`: Digital I/O mapping
- `_get_stepper_channel_for_pins()`: Stepper channel mapping

Adjust these functions based on your specific RPi Pico to component wiring.

---

## Development Notes

### For Arduino Development
- Edit firmware in `firmware/feeder/feeder.ino`
- Upload via Arduino IDE
- Serial communication uses simple text commands

### For RPi Pico Development
- Edit firmware in `firmware/sorter_interface_firmware/`
- Build with: `cmake build && cd build && make`
- Flash with: `picotool load build/sorter_interface_firmware.uf2`
- Uses binary COBS protocol (see `client/hardware/bus.py`)

### Adding Custom Commands
- **Arduino**: Add commands to `client/irl/mcu.py` and Arduino sketch
- **RPi Pico**: Add commands to `client/irl/mcu_pico.py` and firmware message handler
