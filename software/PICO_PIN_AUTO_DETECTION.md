# Pico Pin Auto-Detection

## Overview

The `PicoMCU` class automatically detects and configures pin mappings by parsing the Pico firmware hardware configuration files. This eliminates the need for manual pin mapping configuration.

## How It Works

### 1. File Detection
On startup, the system looks for hardware config files in this order:
1. `firmware/sorter_interface_firmware/hwcfg_skr_pico.h` (preferred)
2. `firmware/sorter_interface_firmware/hwcfg_basically.h` (fallback)

### 2. Pin Extraction
The parser reads the C header file and extracts:
- `STEPPER_STEP_PINS[]` - Array of step pin numbers
- `STEPPER_DIR_PINS[]` - Array of direction pin numbers  
- `STEPPER_nEN_PINS[]` - Array of enable pin numbers
- `STEPPER_COUNT` - Number of steppers

### 3. Mapping Generation
From the extracted pins, the system generates two mappings:

**Stepper Pin Map**: `(step_pin, dir_pin) → stepper_channel`
- Used to route stepper commands to the correct motor

**Enable Pin Map**: `enable_pin → (step_pin, dir_pin)`
- Used to track enable/disable state for each stepper

## Example: hwcfg_skr_pico.h

```cpp
const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {11, 6, 19, 14};
const uint8_t STEPPER_DIR_PINS[] = {10, 5, 28, 13};
const int STEPPER_nEN_PINS[] = {12, 7, 2, 15};
```

**Auto-generated mappings:**

```
Stepper Pin Map:
  (11, 10) → 0  (Stepper 0)
  (6, 5) → 1    (Stepper 1)
  (19, 28) → 2  (Stepper 2)
  (14, 13) → 3  (Stepper 3)

Enable Pin Map:
  12 → (11, 10)   (Stepper 0 enable pin)
  7 → (6, 5)      (Stepper 1 enable pin)
  2 → (19, 28)    (Stepper 2 enable pin)
  15 → (14, 13)   (Stepper 3 enable pin)
```

## Example: hwcfg_basically.h

```cpp
const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {28, 26, 21, 19};
const uint8_t STEPPER_DIR_PINS[] = {27, 22, 20, 18};
const int STEPPER_nEN_PINS[] = {0, 0, 0, 0};  // All share same enable pin
```

**Auto-generated mappings:**

```
Stepper Pin Map:
  (28, 27) → 0  (Stepper 0)
  (26, 22) → 1  (Stepper 1)
  (21, 20) → 2  (Stepper 2)
  (19, 18) → 3  (Stepper 3)

Enable Pin Map:
  0 → (19, 18)   (All steppers share enable pin 0)
```

## Fallback Behavior

If auto-detection fails (missing config files), the system falls back to hardcoded RAMPS 1.4 mappings:

```python
_stepper_pin_map = {
    (36, 34): 0,  # Carousel
    (26, 28): 1,  # Chute
    (46, 48): 2,  # First rotor
    (60, 61): 3,  # Second rotor
    (54, 55): 4,  # Third rotor
}

_enable_pin_to_stepper = {
    30: (36, 34),  # Carousel enable
    24: (26, 28),  # Chute enable
    62: (46, 48),  # First rotor enable
    56: (60, 61),  # Second rotor enable
    38: (54, 55),  # Third rotor enable
}
```

A warning is logged when fallback is used:
```
Could not auto-detect Pico pins; using default RAMPS 1.4 mappings
```

## Testing Auto-Detection

You can test the auto-detection directly:

```bash
cd software/client/irl
python3 pico_pin_config.py
```

Output:
```
Auto-detecting Pico pin configuration...

Stepper Pin Map (step_pin, dir_pin) → channel:
  (11, 10) → 0
  (6, 5) → 1
  (14, 13) → 3
  (19, 28) → 2

Enable Pin Map enable_pin → (step_pin, dir_pin):
  2 → (19, 28)
  7 → (6, 5)
  12 → (11, 10)
  15 → (14, 13)
```

## Adding a New Hardware Configuration

To support a new Pico hardware configuration:

1. Create a new header file: `firmware/sorter_interface_firmware/hwcfg_custom.h`
2. Define the stepper pins:
   ```cpp
   const uint8_t STEPPER_COUNT = 4;
   const uint8_t STEPPER_STEP_PINS[] = {...};
   const uint8_t STEPPER_DIR_PINS[] = {...};
   const int STEPPER_nEN_PINS[] = {...};
   ```
3. In `sorter_interface_firmware.cpp`, include your config:
   ```cpp
   // Select one:
   #include "hwcfg_basically.h"      // or
   #include "hwcfg_skr_pico.h"       // or
   #include "hwcfg_custom.h"         // Your new config
   ```
4. The Python client will automatically detect and use the matching config

## Troubleshooting

### Issue: "Could not auto-detect Pico pins"

**Possible causes:**
1. Hardware config files not found in `firmware/sorter_interface_firmware/`
2. Config file format doesn't match expected patterns
3. Module import path issue

**Solution:**
- Verify config files exist: `ls software/firmware/sorter_interface_firmware/hwcfg_*.h`
- Check file format matches examples above
- Manually add mappings to `client/irl/mcu_pico.py` as fallback

### Issue: Wrong pins mapping detected

**Possible causes:**
1. Config file has invalid pin array format
2. Regex pattern doesn't match file format

**Solution:**
- Verify config file opens correctly: `cat software/firmware/sorter_interface_firmware/hwcfg_*.h`
- Check that arrays are on single lines (no line breaks in definitions)
- Edit `client/irl/pico_pin_config.py` to adjust regex patterns if needed

## Implementation Details

The auto-detection is implemented in `client/irl/pico_pin_config.py`:

- `detect_hwcfg_file()` - Locates hardware config files
- `parse_hwcfg_file()` - Parses C header file
- `build_stepper_pin_map()` - Generates stepper routing map
- `build_enable_pin_map()` - Generates enable pin tracking map
- `auto_configure_pico_pins()` - Main entry point

These functions are called in `PicoMCU.__init__()` to configure pins at startup.
