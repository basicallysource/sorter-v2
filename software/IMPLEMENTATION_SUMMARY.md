# RPi Pico Setup - Implementation Summary

## Overview

The code now supports seamless switching between Arduino Mega 2560 and RPi Pico with full auto-detection of pin configurations.

## Files Created/Modified

### New Files

1. **`client/irl/pico_pin_config.py`** - Auto-detection module
   - Parses `hwcfg_*.h` files from firmware directory
   - Generates stepper and enable pin mappings automatically
   - Includes fallback to hardcoded defaults if detection fails

2. **`PICO_PIN_AUTO_DETECTION.md`** - Detailed documentation
   - How auto-detection works
   - Examples for both hwcfg_basically.h and hwcfg_skr_pico.h
   - Troubleshooting guide
   - Instructions for adding new hardware configs

3. **`MCU_CONFIGURATION.md`** - Setup guide
   - Updated with simplified pin mapping documentation
   - References new auto-detection document

### Modified Files

1. **`.env.example`**
   - Added `MCU_TYPE` configuration option ("arduino" or "rpi_pico")

2. **`client/irl/mcu_pico.py`**
   - Now uses auto-detection on startup
   - Falls back to hardcoded RAMPS 1.4 mappings if detection fails
   - Routed to high-level `SorterInterface` stepper commands
   - No longer tries to control individual pins

3. **`client/irl/device_discovery.py`**
   - Updated to return `(port, mcu_type)` tuple
   - Filters device detection by MCU type (Arduino vs Pico)
   - Auto-detects Pico using VID/PID filtering

4. **`client/irl/config.py`**
   - Updated `IRLConfig` to store `mcu_type`
   - Modified `mkIRLInterface()` to instantiate correct MCU class
   - Updated type hints to support both MCU types

## Key Features

### ✅ Auto-Detection
- Automatically finds and parses firmware hardware config files
- Generates correct pin mappings at startup
- Falls back safely to defaults if files not found

### ✅ High-Level Stepper Control
- Routes stepper commands through `SorterInterface.StepperMotor` objects
- Avoids pin conflicts when multiple steppers share enable pins
- Ignores individual `pinMode`/`digitalWrite` calls (not needed for Pico)

### ✅ Flexible Configuration
- Supports both `hwcfg_basically.h` and `hwcfg_skr_pico.h` automatically
- Easy to add new hardware configurations
- Manual override possible if needed

### ✅ Backward Compatibility
- Arduino mode works exactly as before
- Fallback mappings ensure system works even without config files
- No changes required to application logic (`Stepper` class)

## Usage

### For Arduino (Default)

```bash
cp .env.example .env
# Leave MCU_TYPE="arduino" (default)
cd client && uv run python main.py
```

### For RPi Pico

```bash
cp .env.example .env
# Edit .env and set: MCU_TYPE="rpi_pico"
cd client && uv run python main.py
```

The system will automatically:
1. Detect which MCU type to use
2. Find the appropriate device (with device selection prompts if needed)
3. For Pico: Parse firmware hardware config and generate pin mappings
4. Initialize the correct MCU class with auto-detected configuration

## Testing Auto-Detection

```bash
cd software/client/irl
python3 pico_pin_config.py
```

Output shows detected pin mappings:
```
Stepper Pin Map (step_pin, dir_pin) → channel:
  (11, 10) → 0
  (6, 5) → 1
  ...
```

## Architecture

```
Arduino Path:
  main.py
  ├─ mkIRLInterface() → MCU(arduino_port)
  ├─ client/irl/mcu.py (text serial protocol)
  └─ Stepper → sends "T,step_pin,dir_pin,steps,..."

Pico Path:
  main.py
  ├─ mkIRLInterface() → PicoMCU(pico_port)
  ├─ client/irl/mcu_pico.py (high-level commands)
  ├─ client/irl/pico_pin_config.py (auto-detection)
  └─ Stepper → routes to SorterInterface.StepperMotor.move_steps()
```

## Supported Configurations

### hwcfg_basically.h
- 4 steppers sharing single enable pin
- Pins: step={28,26,21,19}, dir={27,22,20,18}, enable={0,0,0,0}

### hwcfg_skr_pico.h
- 4 steppers with individual enable pins
- Pins: step={11,6,19,14}, dir={10,5,28,13}, enable={12,7,2,15}

### Custom Configurations
Add new `hwcfg_custom.h` to firmware and the system will auto-detect it!

## Troubleshooting

### Issue: "Could not auto-detect Pico pins"
→ Check that config files exist in `firmware/sorter_interface_firmware/`
→ Verify file format (array definitions on single lines)
→ See [PICO_PIN_AUTO_DETECTION.md](PICO_PIN_AUTO_DETECTION.md) troubleshooting section

### Issue: Wrong stepper mapping
→ Verify firmware header file has correct pin definitions
→ Run `python3 client/irl/pico_pin_config.py` to check detected mapping
→ Manually override in `mcu_pico.py` if needed

### Issue: Communication errors
→ Check firmware is built and uploaded to Pico
→ Verify Pico serial connection: `ls /dev/ttyACM*`
→ Try manual device selection if auto-detection fails

## Next Steps

1. **Upload Pico Firmware**
   - Build and flash `firmware/sorter_interface_firmware/` to your Pico

2. **Set Environment**
   ```bash
   cp .env.example .env
   export MCU_TYPE="rpi_pico"
   ```

3. **Run Application**
   ```bash
   cd client && uv run python main.py
   ```

4. **Verify Auto-Detection**
   - Check startup logs for "Auto-detected Pico pin configuration"
   - Or run `python3 client/irl/pico_pin_config.py` to test directly

That's it! The system will automatically detect your hardware configuration and set up the correct pin mappings.
