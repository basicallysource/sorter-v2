import os
import sys
from serial.tools import list_ports
from utils.pick_menu import pickMenu


def listAvailableDevices() -> list[str]:
    ports = list_ports.comports()
    usb_ports = []
    for port in ports:
        port_name = port.device
        if "Bluetooth" in port_name or "debug-console" in port_name:
            continue
        usb_ports.append(port_name)
    return sorted(usb_ports)


def promptForDevice(device_name: str, env_var_name: str) -> str:
    env_value = os.environ.get(env_var_name)
    available_devices = listAvailableDevices()

    if not available_devices:
        print(f"Error: No USB serial devices found")
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
    mcu_path = promptForDevice("MCU", "MCU_PATH")

    print(f"\nSelected:")
    print(f"  MCU: {mcu_path}")
    print()

    return mcu_path
