import os
import sys
import serial
import time
from serial.tools import list_ports
from utils.pick_menu import pickMenu
from blob_manager import getMcuPath, setMcuPath


def listAvailableDevices(device_type: str = "arduino") -> list[str]:
    """
    List available USB serial devices.
    
    Args:
        device_type: "arduino" or "rpi_pico"
    
    Returns:
        List of device ports sorted by path
    """
    ports = list_ports.comports()
    usb_ports = []
    
    for port in ports:
        port_name = port.device
        if "Bluetooth" in port_name or "debug-console" in port_name:
            continue
        
        # Filter by device type if specified
        if device_type == "rpi_pico":
            # RPi Pico uses VID 0x2E8A (Raspberry Pi), PID 0x000A (Pico SDK CDC UART)
            if port.vid == 0x2E8A and port.pid == 0x000A:
                usb_ports.append(port_name)
        elif device_type == "arduino":
            # Arduino Mega typically uses VID 0x2341 (Arduino), PID varies
            # But we'll accept most common Arduino/CH340 serial devices
            if port.vid and port.vid != 0x2E8A:  # Exclude Pico
                usb_ports.append(port_name)
        else:
            # Default: list all devices
            usb_ports.append(port_name)
    
    return sorted(usb_ports)


def promptForDevice(device_name: str, env_var_name: str, device_type: str = "arduino") -> str:
    """
    Prompt user to select a device.
    
    Args:
        device_name: Display name for the device (e.g., "MCU")
        env_var_name: Environment variable name to check
        device_type: "arduino" or "rpi_pico"
    
    Returns:
        Selected device port path
    """
    env_value = os.environ.get(env_var_name)
    available_devices = listAvailableDevices(device_type)

    if not available_devices:
        print(f"Error: No {device_type} devices found")
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


def autoDiscoverFeeder() -> str | None:
    available_devices = listAvailableDevices()

    for device_path in available_devices:
        try:
            ser = serial.Serial(device_path, 115200, timeout=0.5)
            time.sleep(2.0)

            ser.reset_input_buffer()
            ser.write(b"N\n")
            time.sleep(0.2)

            if ser.in_waiting > 0:
                response = ser.readline().decode().strip()
                ser.close()

                if response == "feeder":
                    return device_path
            else:
                ser.close()

        except (serial.SerialException, OSError):
            continue

    return None


def verifyDevice(device_path: str) -> bool:
    try:
        ser = serial.Serial(device_path, 115200, timeout=0.5)
        time.sleep(2.0)
        ser.reset_input_buffer()
        ser.write(b"N\n")
        time.sleep(0.2)
        if ser.in_waiting > 0:
            response = ser.readline().decode().strip()
            ser.close()
            return response == "feeder"
        ser.close()
    except (serial.SerialException, OSError):
        pass
    return False


def discoverMCU() -> tuple[str, str]:
    """
    Discover MCU device and return (port, mcu_type).
    
    MCU_TYPE environment variable:
    - "arduino": Arduino Mega 2560 with RAMPS 1.4 shield
    - "rpi_pico": Raspberry Pi Pico running sorter_interface_firmware
    
    Returns:
        Tuple of (port, mcu_type)
    """
    env_value = os.environ.get("MCU_PATH")
    mcu_type = os.environ.get("MCU_TYPE", "arduino").lower()
    
    if not mcu_type in ["arduino", "rpi_pico"]:
        print(f"Error: Invalid MCU_TYPE '{mcu_type}'. Must be 'arduino' or 'rpi_pico'")
        sys.exit(1)

    if env_value:
        return env_value, mcu_type

    cached_path = getMcuPath()
    if cached_path and mcu_type == "arduino":
        print(f"Trying cached MCU path {cached_path}...")
        if verifyDevice(cached_path):
            print(f"Verified feeder at {cached_path}")
            return cached_path, mcu_type
        print("Cached path didn't respond, falling back to auto-discovery...")

    print(f"Auto-discovering {mcu_type} MCU...")
    
    if mcu_type == "arduino":
        mcu_path = autoDiscoverFeeder()
        if mcu_path:
            print(f"Found Arduino MCU at {mcu_path}")
            setMcuPath(mcu_path)
            return mcu_path, mcu_type
    
    elif mcu_type == "rpi_pico":
        # For Pico, use MCUBus.enumerate_buses() which filters by VID/PID
        from hardware.bus import MCUBus
        available_picos = MCUBus.enumerate_buses()
        if available_picos:
            print(f"Found Pico MCU at {available_picos[0]}")
            return available_picos[0], mcu_type

    print(f"Auto-discovery failed. Please select device manually:")
    port = promptForDevice("MCU", "MCU_PATH", mcu_type)
    if mcu_type == "arduino":
        setMcuPath(port)
    return port, mcu_type
