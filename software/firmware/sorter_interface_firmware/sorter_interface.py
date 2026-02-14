# Test module for the sorter interface communications

class DecodeError(Exception):
    pass

def COBS_encode(message: bytearray) -> bytearray:
    outbuf = bytearray(b'\x01')
    counter_idx = 0
    for mb in message:
        if mb == 0:
            counter_idx = len(outbuf)
        outbuf.append(mb)
        outbuf[counter_idx] += 1;
    return outbuf

def COBS_decode(buff: bytearray) -> bytearray:
    msgbuf = bytearray()
    s = buff.pop(0)
    while buff:
        c = buff.pop(0)
        if c == 0:
            raise DecodeError("Packet contains zeroes")
        if s == 1:
            msgbuf.append(0)
            s = c
        else:
            msgbuf.append(c)
            s -= 1

    if s > 1:
        raise DecodeError("Corrupted count")

    return msgbuf

import logging

from sympy import true

logging.basicConfig(level=logging.WARNING)

import serial
import struct
from zlib import crc32

from dataclasses import dataclass

DBG_MESSAGE_COUNT = 0

class CommandCodes:
    # Common Commands
    CMD_INIT = 0x01
    CMD_PING = 0x02
    # Stepper Commands
    CMD_STEPPER_MOVE_STEPS = 0x10
    CMD_STEPPER_MOVE_AT_SPEED = 0x11
    CMD_STEPPER_SET_SPEED_LIMITS = 0x12
    CMD_STEPPER_SET_ACCELERATION = 0x13
    CMD_STEPPER_IS_STOPPED = 0x14
    # Diagnostics Commands
    CMD_BAD_COMMAND = 0xFF

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

class SorterInterfaceBus:
    def __init__(self, port: str):
        self.ser = serial.Serial(port, baudrate=115200, timeout=1)
    
    def send_command(self, address: int, command: int, channel: int, payload: bytes) -> Message:
        payload_length = len(payload)
        message = struct.pack('<BBBB', address, command, channel, payload_length) + payload
        # Append CRC
        crc = crc32(message)
        message += struct.pack('<I', crc)
        logging.debug(f"Raw message: {message[:-4].hex(b' ', 1)}, CRC: {crc32(message[:-4]):08X}, Length: {len(message)-4}")
        encoded_message = COBS_encode(message) + b'\x00'
        logging.debug(f"Sending: {encoded_message.hex(b' ', 1)}")
        self.ser.write(encoded_message)

        # Read response
        resp_buf = bytearray(self.ser.read_until(b'\x00', 254))
        if not resp_buf:
            raise DecodeError("No response received")
        if resp_buf[-1] != 0:
            raise DecodeError("No terminator received")
        
        logging.debug(f"Received: {resp_buf.hex(b' ', 1)}")

        decoded_resp = COBS_decode(resp_buf[:-1])  # Exclude terminator

        if crc32(decoded_resp[:-4]) != struct.unpack('<I', decoded_resp[-4:])[0]:
            raise DecodeError("CRC check failed")
        
        response_header = MessageHeader(*struct.unpack('<BBBB', decoded_resp[:4]))
        message = Message(
            dev_address=response_header.address,
            command=response_header.command,
            channel=response_header.channel,
            payload=bytes(decoded_resp[4:-4])
        )

        if message.command & 0x80:
            raise RuntimeError(f"Error response received, command: {message.command:#04x}")
        
        global DBG_MESSAGE_COUNT
        DBG_MESSAGE_COUNT += 1
        return message



class SorterInterfaceCard:
    def __init__(self, bus: SorterInterfaceBus, address: int):
        self.bus = bus
        self.address = address

    def send_command(self, command: int, channel: int, payload: bytes) -> bytes:
        return self.bus.send_command(self.address, command, channel, payload)
    
    def stepper_is_stopped(self, channel: int) -> bool:
        res = self.send_command(CommandCodes.CMD_STEPPER_IS_STOPPED, channel, b'')
        response_bool = struct.unpack('?', res.payload)[0]
        return bool(response_bool)

    def stepper_set_speed_limits(self, channel: int, min_speed: int, max_speed: int) -> None:
        payload = struct.pack('<ii', min_speed, max_speed)
        self.send_command(CommandCodes.CMD_STEPPER_SET_SPEED_LIMITS, channel, payload)
    
    def stepper_set_acceleration(self, channel: int, acceleration: int) -> None:
        payload = struct.pack('<i', acceleration)
        self.send_command(CommandCodes.CMD_STEPPER_SET_ACCELERATION, channel, payload)
    
    def stepper_move_steps(self, channel: int, steps: int) -> None:
        payload = struct.pack('<i', steps)
        res = self.send_command(CommandCodes.CMD_STEPPER_MOVE_STEPS, channel, payload)
        response_bool = struct.unpack('?', res.payload)[0]
        return response_bool
    
    def stepper_move_at_speed(self, channel: int, speed: int) -> None:
        payload = struct.pack('<i', speed)
        res = self.send_command(CommandCodes.CMD_STEPPER_MOVE_AT_SPEED, channel, payload)
        response_bool = struct.unpack('?', res.payload)[0]
        return response_bool
    


if __name__ == "__main__":
    import sys, random, time
    if len(sys.argv) != 2:
        print("Usage: python sorter_interface.py <serial_port>")
        sys.exit(1)
    port = sys.argv[1]
    bus = SorterInterfaceBus(port)
    card = SorterInterfaceCard(bus, address=0)
    start_time = time.monotonic()
    message_count = DBG_MESSAGE_COUNT
    try:
        while true:
            for i in range(4):
                if card.stepper_is_stopped(channel=i):
                    card.stepper_set_speed_limits(channel=i, min_speed=16, max_speed=random.randint(500, 2500))
                    card.stepper_set_acceleration(channel=i, acceleration=random.randint(1000, 20000))
                    card.stepper_move_steps(channel=i, steps=random.randint(200, 2000)*random.choice([-1, 1]))
                now = time.monotonic()
                if now - start_time > 1:
                    elapsed = now - start_time
                    print(f"Elapsed time: {elapsed:.2f} seconds, Messages: {DBG_MESSAGE_COUNT - message_count}, Rate: {(DBG_MESSAGE_COUNT - message_count)/elapsed:.2f} msg/s")
                    message_count = DBG_MESSAGE_COUNT
                    start_time = now
    except DecodeError as e:
        print(f"Error: {e}")