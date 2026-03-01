import os
import sys
from utils.pick_menu import pickMenu
from hardware.bus import MCUBus


def listAvailableDevices() -> list[str]:
    """
    List available MCU bus devices compatible with SorterInterface firmware.

    Returns:
        List of device ports sorted by path
    """
    return MCUBus.enumerate_buses()


def promptForDevice(device_name: str, env_var_name: str) -> str:
    """
    Prompt user to select a device.
    
    Args:
        device_name: Display name for the device (e.g., "MCU")
        env_var_name: Environment variable name to check

    Returns:
        Selected device port path
    """
    env_value = os.environ.get(env_var_name)
    available_devices = listAvailableDevices()

    if not available_devices:
        print("Error: No compatible MCU devices found")
        sys.exit(1)
    options = []

    if env_value:
        options.append(f"Use environment variable: {env_value}")

    for device in available_devices:
        options.append(device)

    print(f"\nSelect {device_name}:")
    choice_index = pickMenu(options)

    if choice_index is None:
        print("Selection cancelled")
        sys.exit(1)

    if env_value and choice_index == 0:
        return env_value

    if env_value:
        return available_devices[choice_index - 1]
    else:
        return available_devices[choice_index]


def discoverMCU() -> str:
    """
    Discover MCU device port for SorterInterface firmware.

    Returns:
        Port path
    """
    env_value = os.environ.get("MCU_PATH")
    if env_value:
        return env_value

    available_devices = listAvailableDevices()
    if available_devices:
        print(f"Found MCU at {available_devices[0]}")
        return available_devices[0]

    print("Auto-discovery failed. Please select device manually:")
    return promptForDevice("MCU", "MCU_PATH")
