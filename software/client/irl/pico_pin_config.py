"""Auto-generate Pico pin mappings from firmware hardware config files."""

import re
import os
from pathlib import Path
from typing import Optional


def parse_hwcfg_file(config_file_path: str) -> Optional[dict]:
    """
    Parse a Pico hardware configuration file (.h) to extract pin definitions.
    
    Args:
        config_file_path: Path to hwcfg_*.h file
        
    Returns:
        Dictionary with stepper and enable pin mappings, or None if parsing fails
    """
    try:
        with open(config_file_path, 'r') as f:
            content = f.read()
    except (FileNotFoundError, IOError) as e:
        print(f"Error reading config file: {e}")
        return None
    
    config = {}
    
    # Extract STEPPER_STEP_PINS array
    step_match = re.search(r'STEPPER_STEP_PINS\[\]\s*=\s*\{([^}]+)\}', content)
    if step_match:
        step_pins = [int(x.strip()) for x in step_match.group(1).split(',')]
        config['step_pins'] = step_pins
    
    # Extract STEPPER_DIR_PINS array
    dir_match = re.search(r'STEPPER_DIR_PINS\[\]\s*=\s*\{([^}]+)\}', content)
    if dir_match:
        dir_pins = [int(x.strip()) for x in dir_match.group(1).split(',')]
        config['dir_pins'] = dir_pins
    
    # Extract STEPPER_nEN_PINS array
    en_match = re.search(r'STEPPER_nEN_PINS\[\]\s*=\s*\{([^}]+)\}', content)
    if en_match:
        en_pins = [int(x.strip()) for x in en_match.group(1).split(',')]
        config['en_pins'] = en_pins
    
    # Extract STEPPER_COUNT
    count_match = re.search(r'STEPPER_COUNT\s*=\s*(\d+)', content)
    if count_match:
        config['stepper_count'] = int(count_match.group(1))
    
    return config if config else None


def build_stepper_pin_map(config: dict) -> dict:
    """
    Build stepper pin mappings from parsed hardware config.
    
    Args:
        config: Parsed hardware config dict
        
    Returns:
        Dict mapping (step_pin, dir_pin) → stepper_channel
    """
    pin_map = {}
    
    if 'step_pins' not in config or 'dir_pins' not in config:
        return pin_map
    
    step_pins = config['step_pins']
    dir_pins = config['dir_pins']
    count = min(len(step_pins), len(dir_pins))
    
    for channel in range(count):
        key = (step_pins[channel], dir_pins[channel])
        pin_map[key] = channel
    
    return pin_map


def build_enable_pin_map(config: dict) -> dict:
    """
    Build enable pin mappings from parsed hardware config.
    
    Args:
        config: Parsed hardware config dict
        
    Returns:
        Dict mapping enable_pin → (step_pin, dir_pin)
    """
    enable_map = {}
    
    if 'en_pins' not in config or 'step_pins' not in config or 'dir_pins' not in config:
        return enable_map
    
    en_pins = config['en_pins']
    step_pins = config['step_pins']
    dir_pins = config['dir_pins']
    count = min(len(en_pins), len(step_pins), len(dir_pins))
    
    for channel in range(count):
        en_pin = en_pins[channel]
        stepper_key = (step_pins[channel], dir_pins[channel])
        # Map each enable pin to its stepper; if same pin used for multiple, 
        # we'll map it only once (the last occurrence wins)
        enable_map[en_pin] = stepper_key
    
    return enable_map


def detect_hwcfg_file() -> Optional[str]:
    """
    Auto-detect which hardware config file is in use.
    
    Looks for hwcfg_basically.h or hwcfg_skr_pico.h in the firmware directory.
    Returns the path of the first one found, preferring skr_pico.
    
    Returns:
        Path to the detected config file, or None if not found
    """
    firmware_dir = Path(__file__).parent.parent.parent / "firmware" / "sorter_interface_firmware"
    
    # Prefer SKR Pico config if it exists
    skr_config = firmware_dir / "hwcfg_skr_pico.h"
    if skr_config.exists():
        return str(skr_config)
    
    # Fall back to Basically config
    basically_config = firmware_dir / "hwcfg_basically.h"
    if basically_config.exists():
        return str(basically_config)
    
    return None


def auto_configure_pico_pins() -> tuple[Optional[dict], Optional[dict]]:
    """
    Auto-detect and configure Pico pin mappings.
    
    Returns:
        Tuple of (stepper_pin_map, enable_pin_map), or (None, None) if detection fails
    """
    config_file = detect_hwcfg_file()
    
    if not config_file:
        return None, None
    
    config = parse_hwcfg_file(config_file)
    
    if not config:
        return None, None
    
    stepper_map = build_stepper_pin_map(config)
    enable_map = build_enable_pin_map(config)
    
    return stepper_map, enable_map


if __name__ == "__main__":
    # Test: print the auto-detected configuration
    print("Auto-detecting Pico pin configuration...")
    stepper_map, enable_map = auto_configure_pico_pins()
    
    if stepper_map and enable_map:
        print(f"\nStepper Pin Map (step_pin, dir_pin) → channel:")
        for pins, channel in sorted(stepper_map.items()):
            print(f"  {pins} → {channel}")
        
        print(f"\nEnable Pin Map enable_pin → (step_pin, dir_pin):")
        for en_pin, stepper_pins in sorted(enable_map.items()):
            print(f"  {en_pin} → {stepper_pins}")
    else:
        print("Failed to detect or parse hardware configuration")
