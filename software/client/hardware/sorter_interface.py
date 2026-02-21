"""Implementation of the Sorter Interface hardware drivers"""

# Copyright (c) 2026 Jose I. Romero
#
# Licensed under the MIT License. See LICENSE file in the project root for full license information.


import logging
import time
from .bus import MCUDevice, BaseCommandCode
import struct

class InterfaceCommandCode(BaseCommandCode):
    """Command codes specific to the Sorter Interface."""
    # Stepper commands
    STEPPER_MOVE_STEPS = 0x10
    STEPPER_MOVE_AT_SPEED = 0x11
    STEPPER_SET_SPEED_LIMITS = 0x12
    STEPPER_SET_ACCELERATION = 0x13
    STEPPER_IS_STOPPED = 0x14
    STEPPER_GET_POSITION = 0x15
    STEPPER_SET_POSITION = 0x16
    STEPPER_HOME = 0x17
    # Stepper driver commands
    STEPPER_DRV_SET_ENABLED = 0x20
    STEPPER_DRV_SET_MICROSTEPS = 0x21
    STEPPER_DRV_SET_CURRENT = 0x22
    STEPPER_DRV_READ_REGISTER = 0x26
    STEPPER_DRV_WRITE_REGISTER = 0x27
    # Digital I/O commands
    DIGITAL_READ = 0x30
    DIGITAL_WRITE = 0x31
    # Servo commands
    SERVO_SET_ENABLED = 0x40
    SERVO_MOVE_TO = 0x41
    SERVO_SET_SPEED_LIMITS = 0x42
    SERVO_SET_ACCELERATION = 0x43


class DigitalInputPin:
    def __init__(self, device: MCUDevice, channel: int):
        self._dev = device
        self._channel = channel
    
    @property
    def value(self):
        res = self._dev.send_command(InterfaceCommandCode.DIGITAL_READ, self._channel, b'')
        return bool(res.payload[0])
    
    @property
    def channel(self):
        return self._channel
    
class DigitalOutputPin:
    def __init__(self, device: MCUDevice, channel: int):
        self._dev = device
        self._channel = channel
        self._value = False
        self._enabled = True

    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, value: bool):
        self._value = bool(value)
        payload = struct.pack("<?", self._value) # 1 byte, boolean
        self._dev.send_command(InterfaceCommandCode.DIGITAL_WRITE, self._channel, payload)
    
    @property
    def channel(self):
        return self._channel

class StepperMotor:
    def __init__(self, device: MCUDevice, channel: int):
        self._dev = device
        self._channel = channel
        self._steps_per_revolution = 200
        self._microsteps = 16

    def move_degrees(self, degrees: float) -> bool:
        """
        Move the stepper by a given number of degrees (positive or negative).
        Uses steps_per_revolution to calculate the number of steps.
        """
        steps = int(round((degrees / 360.0) * self._steps_per_revolution * self._microsteps))
        return self.move_steps(steps)
    
    def move_steps(self, steps: int) -> bool:
        """Move the stepper by a given number of microsteps (positive or negative)."""
        payload = struct.pack("<i", steps) # 4 bytes, little-endian signed integer
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_MOVE_STEPS, self._channel, payload)
        return bool(res.payload[0])
    
    def move_at_speed(self, speed: int) -> bool:
        """Move the stepper at a given speed in microsteps per second."""
        payload = struct.pack("<i", speed) # 4 bytes, little-endian signed integer
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_MOVE_AT_SPEED, self._channel, payload)
        return bool(res.payload[0])
    
    def set_speed_limits(self, min_speed: int, max_speed: int) -> bool:
        """Set the minimum and maximum speed for the stepper in microsteps per second."""
        payload = struct.pack("<II", min_speed, max_speed) # 8 bytes, two little-endian unsigned integers
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_SET_SPEED_LIMITS, self._channel, payload)
        return bool(res.payload[0])
    
    def set_acceleration(self, acceleration: int) -> bool:
        """Set the acceleration for the stepper in microsteps per second squared."""
        payload = struct.pack("<I", acceleration) # 4 bytes, little-endian unsigned integer
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_SET_ACCELERATION, self._channel, payload)
        return bool(res.payload[0])
    
    @property
    def stopped(self) -> bool:
        """Check if the stepper is stopped."""
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_IS_STOPPED, self._channel, b'')
        return bool(res.payload[0])
    
    @property
    def position(self) -> int:
        """Get the current position of the stepper in microsteps."""
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_GET_POSITION, self._channel, b'')
        return struct.unpack("<i", res.payload)[0] # 4 bytes, little-endian signed integer
    
    @position.setter
    def position(self, position: int) -> bool:
        """Set the current position of the stepper in microsteps."""
        payload = struct.pack("<i", position) # 4 bytes, little-endian signed integer
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_SET_POSITION, self._channel, payload)
        return bool(res.payload[0])
    
    @property
    def position_degrees(self) -> float:
        """Get the current position of the stepper in degrees."""
        microsteps = self.position
        steps = microsteps / self._microsteps
        degrees = (steps / self._steps_per_revolution) * 360.0
        return degrees
    
    @position_degrees.setter
    def position_degrees(self, degrees: float):
        """Set the current position of the stepper in degrees."""
        steps = (degrees / 360.0) * self._steps_per_revolution
        microsteps = int(round(steps * self._microsteps))
        self.position = microsteps

    def home(self, home_speed: int, home_pin : DigitalInputPin|int, home_pin_active_high=True):
        """Home the stepper using the specified home pin and speed.
        
        home_speed: Speed at which to home the stepper in microsteps per second. Positive values move in one direction, negative values move in the opposite direction.
        home_pin: DigitalInputPin object or integer representing the home pin channel.
        home_pin_active_high: Whether the home pin is active high (True) or active low (False).
        """
        if isinstance(home_pin, DigitalInputPin):
            # If a DigitalInputPin object is provided, use its channel. ONLY IF IT BELONGS TO THE SAME INTERFACE.
            if home_pin._dev != self._dev:
                raise ValueError("home_pin must belong to the same interface as the stepper")
            pin_channel = home_pin._channel
        else:
            pin_channel = home_pin
        
        payload = struct.pack("<IB?", home_speed, pin_channel, bool(home_pin_active_high)) # 4 bytes for speed, 1 byte for pin channel, 1 byte for active high/low
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_HOME, self._channel, payload)
        return bool(res.payload[0])
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable the stepper."""
        self._enabled = bool(value)
        payload = struct.pack("<?", self._enabled) # 1 byte, boolean
        self._dev.send_command(InterfaceCommandCode.STEPPER_DRV_SET_ENABLED, self._channel, payload)
    
    def set_microsteps(self, microsteps: int):
        """Set the microsteps for the stepper."""
        if microsteps not in (1, 2, 4, 8, 16, 32, 64, 128, 256):
            raise ValueError(f"Invalid microsteps value: {microsteps}.")        
        payload = struct.pack("<H", microsteps) # 2 bytes, little-endian unsigned integer
        self._dev.send_command(InterfaceCommandCode.STEPPER_DRV_SET_MICROSTEPS, self._channel, payload)
        self._microsteps = microsteps
    
    def set_current(self, irun: int, ihold: int, ihold_delay: int):
        payload = struct.pack("<BBB", irun, ihold, ihold_delay) # 3 bytes, three little-endian unsigned integers
        self._dev.send_command(InterfaceCommandCode.STEPPER_DRV_SET_CURRENT, self._channel, payload)

    def read_driver_register(self, address: int) -> int:
        payload = struct.pack("<B", address) # 1 byte, unsigned integer
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_DRV_READ_REGISTER, self._channel, payload)
        return struct.unpack("<I", res.payload)[0] # 4 bytes, little-endian unsigned integer
    
    def write_driver_register(self, address: int, value: int):
        payload = struct.pack("<BI", address, value) # 1 byte for address, 4 bytes for value
        self._dev.send_command(InterfaceCommandCode.STEPPER_DRV_WRITE_REGISTER, self._channel, payload)

    @property
    def steps_per_revolution(self):
        return self._steps_per_revolution
    
    @steps_per_revolution.setter
    def steps_per_revolution(self, value: int):
        if value <= 0:
            raise ValueError("steps_per_revolution must be a positive integer")
        self._steps_per_revolution = value
    
    @property
    def channel(self):
        return self._channel



class SorterInterface(MCUDevice):
    steppers : tuple[StepperMotor, ...]
    digital_inputs : tuple[DigitalInputPin, ...]
    digital_outputs : tuple[DigitalOutputPin, ...]

    def __init__(self, bus, address):
        super().__init__(bus, address)
        # Obtain the device information to populate the internal objects
        retries = 5
        while retries > 0:
            try:
                self._board_info = self.detect()
                break
            except Exception as e:
                logging.warning(f"Error initializing device: {e}. Retrying...")
                retries -= 1
                time.sleep(0.1)
        else:
            raise RuntimeError("Failed to initialize device.")
        # Populate the objects for all the capabilities based on the detected information
        digital_input_channels = range(self._board_info.get("digital_input_count", 0))
        digital_output_channels = range(self._board_info.get("digital_output_count", 0))
        stepper_channels = range(self._board_info.get("stepper_count", 0))
        self.digital_inputs = tuple(DigitalInputPin(self, ch) for ch in digital_input_channels)
        self.digital_outputs = tuple(DigitalOutputPin(self, ch) for ch in digital_output_channels)
        self.steppers = tuple(StepperMotor(self, ch) for ch in stepper_channels)
        # Read the device name from the board info, or use a default name based on the address if not provided
        self._name = self._board_info.get("device_name", f"SorterInterface_{address}")

    def shutdown(self):
        # Disable all steppers and set all digital outputs to low
        for stepper in self.steppers:
            stepper.enabled = False
        for dout in self.digital_outputs:
            dout.value = False

    @property
    def name(self):
        return self._name

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import random
    import time
    from .bus import MCUBus
    
    interfaces: dict[str, SorterInterface] = {}
    
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
        for device in devices:
            try:
                interface = SorterInterface(bus, device)
                interfaces[interface.name] = interface
                print(f"Initialized interface: {interface.name}")
            except Exception as e:
                logging.error(f"Error initializing device at address {device}: {e}")
                continue
        logging.info(f"Finished initializing interfaces: {list(interfaces.keys())}")
        start_time = time.monotonic()
        while True:
            now = time.monotonic()
            elapsed = now - start_time
            if elapsed > 1:
                for name, interface in interfaces.items():
                    logging.info(f"Interface {name}:")
                    for i, stepper in enumerate(interface.steppers):
                        logging.info(f"  Stepper {i}: position={stepper.position}, stopped={stepper.stopped}")
                    for i, dout in enumerate(interface.digital_outputs):
                        logging.info(f"  Digital Output {i}: value={dout.value}")
                    for i, din in enumerate(interface.digital_inputs):
                        logging.info(f"  Digital Input {i}: value={din.value}")
                start_time = now
            for name, interface in interfaces.items():
                for stepper in interface.steppers:
                    if not stepper.stopped:
                        continue
                    # Randomly decide to move the stepper
                    steps = random.randint(-1000, 1000)
                    logging.info(f"Moving stepper on interface {name} by {steps} steps")
                    stepper.move_steps(steps)
            time.sleep(0.01)
