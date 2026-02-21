"""Low-level communication protocol implementation for the MCU bus.

The MCUBus class provides methods for sending commands to devices on the bus and receiving their responses,
using a custom binary protocol with COBS (Consistent Overhead Byte Stuffing) framing and CRC32 for message
integrity checking.

The Message format is as follows:

- Header (4 bytes):
    - Address (1 byte): The device address (0-255)
    - Command (1 byte): The command code (0-255)
    - Channel (1 byte): The channel number (0-255)
    - Payload Length (1 byte): The length of the payload in bytes (0-246
- Payload (0-246 bytes): The command payload
- CRC (4 bytes): A CRC32 checksum of the header and payload for error detection

Followed by one or more 0x00 bytes as a message terminator. The total message size (including header,
payload and CRC) must not exceed 254 bytes. All numbers are encoded in little-endian format.

This interface implementation works both for MCUs directly attached through USB (they will always have
address 0) and for devices connected through a multi-drop bus like RS-485, where each device has a unique
address.

The MCUDevice class is intended to be subclassed for specific device types, providing higher-level methods for commands
specific to that device, while the MCUBus class handles the low-level communication details and access to the
(potentially shared) communication bus.
"""

# Copyright (c) 2020-2026 Jose I. Romero
#
# Licensed under the MIT License. See LICENSE file in the project root for full license information.

import json
import logging
from . import cobs
import serial

import struct
from zlib import crc32
from dataclasses import dataclass
from threading import Lock


MAX_PAYLOAD_SIZE = (
    254 - 8
)  # Max total message size is 254, header is 4 bytes, CRC is 4 bytes


@dataclass
class MessageHeader:
    address: int
    command: int
    channel: int
    payload_length: int


@dataclass
class Message:
    dev_address: int
    command: int
    channel: int
    payload: bytes


class BaseCommandCode:
    INIT = 0x00
    PING = 0x01


class MCUBusError(Exception):
    """Base exception class for errors related to the MCUBus communication."""

    pass


class MCUBus:
    """Class for communicating with the MCU over a serial bus using a custom protocol."""

    def __init__(self, port: str, baudrate: int = 576000, timeout: float = 0.1):
        """Initialize the MCUBus with the given serial port parameters.

        Args:
            port: The serial port to use (e.g. "/dev/ttyUSB0")
            baudrate: The baud rate for the serial communication (default 576000)
            timeout: The read timeout in seconds (default 0.01s = 10ms)
        """

        self._serial = serial.Serial(port, baudrate=baudrate, timeout=timeout)
        self._lock = Lock()

    def send_command(
        self, address: int, command: int, channel: int, payload: bytes
    ) -> Message:
        """Send a command to the MCU and return the response from it.

        Args:
            address: The device address (0-255)
            command: The command code (0-255)
            channel: The channel number (0-255)
            payload: The command payload (0-246 bytes)

        Returns:
            A Message object containing the response from the MCU.

        Raises:
            ValueError: If any of the input parameters are out of range or if the payload is too large.
            MCUBusError: If there is a communication error, CRC check failure, or if the response indicates an error.
        """
        payload_length = len(payload)
        # Validate inputs
        if payload_length > MAX_PAYLOAD_SIZE:
            raise ValueError(
                f"Payload too large: {payload_length} bytes (max {MAX_PAYLOAD_SIZE})"
            )
        if address < 0 or address > 255:
            raise ValueError(f"Address must be 0-255, got {address}")
        if command < 0 or command > 255:
            raise ValueError(f"Command must be 0-255, got {command}")
        if channel < 0 or channel > 255:
            raise ValueError(f"Channel must be 0-255, got {channel}")
        # Construct message
        message = (
            struct.pack("<BBBB", address, command, channel, payload_length) + payload
        )
        # Append CRC
        crc = crc32(message)
        message += struct.pack("<I", crc)
        logging.debug(
            f"Raw message: {message[:-4].hex(b' ', 1)}, CRC: {crc32(message[:-4]):08X}, Length: {len(message)-4}"
        )
        encoded_message = cobs.encode(message) + b"\x00"
        logging.debug(f"Sending: {encoded_message.hex(b' ', 1)}")

        with self._lock:  # Ensure that this transaction is atomic with respect to other threads
            # Before writing, resynchronize by clearing the read buffer of any stale data
            self._serial.reset_input_buffer()
            self._serial.write(encoded_message)
            # Read response, will block until data received or timeout occurs
            resp_buf = bytearray(self._serial.read_until(b"\x00", 254))
            if not resp_buf or resp_buf[-1] != 0:
                raise MCUBusError("Truncated response received")

        logging.debug(f"Received: {resp_buf.hex(b' ', 1)}")

        decoded_resp = cobs.decode(resp_buf[:-1])  # Exclude terminator

        if crc32(decoded_resp[:-4]) != struct.unpack("<I", decoded_resp[-4:])[0]:
            raise MCUBusError("CRC check failed")

        response_header = MessageHeader(*struct.unpack("<BBBB", decoded_resp[:4]))
        message = Message(
            dev_address=response_header.address,
            command=response_header.command,
            channel=response_header.channel,
            payload=bytes(decoded_resp[4:-4][: response_header.payload_length]),
        )

        if response_header.payload_length != len(message.payload):
            raise MCUBusError(
                f"Payload length mismatch: expected {response_header.payload_length}, got {len(message.payload)}"
            )

        if message.dev_address != address:
            raise MCUBusError(
                f"Response address mismatch: expected {address}, got {message.dev_address}"
            )

        if message.command & 0x80:
            raise MCUBusError(
                f"Error response received, command: {message.command:#04x}, payload: {message.payload}"
            )

        return message

    @classmethod
    def enumerate_buses(cls, vid=0x2E8A, pid=0x000A) -> list[str]:
        """Enumerate available serial ports that could be used for the MCU bus. Filtered by VID and PID

        Args:
            vid: The USB Vendor ID to filter by (default 0x2e8a, Raspberry Pi Foundation)
            pid: The USB Product ID to filter by (default 0x000a, Pico SDK CDC UART)

        Returns:
            A list of serial port names (e.g. ["/dev/ttyUSB0", "/dev/ttyUSB1"])
        """
        import serial.tools.list_ports

        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports if port.vid == vid and port.pid == pid]

    def scan_devices(self, min_address=0, max_address=15) -> list[int]:
        """Scan the bus for devices by sending a ping command to each address in the specified range.

        Note: this process can take a long time since it waits for a timeout for each address that doesn't respond.
        The default range is 0-15 since we expect only a few devices on the bus, but this can be adjusted as needed.

        Args:
            min_address: The minimum device address to scan (default 0)
            max_address: The maximum device address to scan (default 15)

        Returns:
            A list of device addresses that responded to the ping command.
        """
        found_devices = []
        for addr in range(min_address, max_address + 1):
            try:
                self.send_command(addr, BaseCommandCode.PING, 0, b"")
                found_devices.append(addr)
                logging.debug(f"Device found at address {addr}")
            except Exception as e:
                logging.debug(f"No response from address {addr}: {e}")
                pass
        return found_devices


class MCUDevice:
    """Higher-level abstraction for a device on the MCU bus, providing methods for common commands."""

    def __init__(self, bus: MCUBus, address: int):
        self._bus = bus
        self._address = address

    def send_command(self, command: int, channel: int, payload: bytes) -> Message:
        """Send a command to this device and return the response."""
        return self._bus.send_command(self._address, command, channel, payload)

    def ping(self, payload: bytes = b"") -> bool:
        """Send a ping command to the device to check if it's responsive."""
        return self.send_command(BaseCommandCode.PING, 0, payload)
    
    def detect(self) -> dict:
        """Send an init command to the device to check if it's responsive and properly initialized."""
        res = self.send_command(BaseCommandCode.INIT, 0, b"") # Returns a JSON string with device info if successful
        info_str = res.payload.decode("utf-8")
        return json.loads(info_str)



if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Enumerating buses...")
    buses = MCUBus.enumerate_buses()
    print(f"Available buses: {buses}")
    if not buses:
        print("No buses found, exiting.")
    else:
        print(f"Testing bus on port {buses[0]}...")
        bus = MCUBus(port=buses[0])
        devices = bus.scan_devices()
        print(f"Devices found: {devices}")
        if devices:
            device = MCUDevice(bus, devices[0])
            response = device.ping(b"Hello")
            print(f"Ping response: {response}")
            info = device.detect()
            print(f"Device info: {info}")