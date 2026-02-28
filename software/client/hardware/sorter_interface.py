"""Implementation of the Sorter Interface hardware drivers"""

# Copyright (c) 2026 Jose I. Romero
#
# Licensed under the MIT License. See LICENSE file in the project root for full license information.


import logging
import time
from .bus import MCUDevice, BaseCommandCode
from blob_manager import getStepperPosition, setStepperPosition, getServoPosition, setServoPosition
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
    STEPPER_DRV_READ_REGISTER = 0x28
    STEPPER_DRV_WRITE_REGISTER = 0x29
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
        self._name = f"stepper_{channel}"
        # Track position via blob_manager for persistence
        self._current_position_steps = getStepperPosition(self._name)

    def move_degrees(self, degrees: float) -> bool:
        """
        Move the stepper by a given number of degrees (positive or negative).
        Uses steps_per_revolution to calculate the number of steps.
        """
        steps = int(round((degrees / 360.0) * self._steps_per_revolution * self._microsteps))
        return self.move_steps(steps)
    
    def move_steps(self, steps: int, delay_us: int = 0, accel_start_delay_us: int = 0, 
                   accel_steps: int = 0, decel_steps: int = 0) -> bool:
        """
        Move the stepper by a given number of microsteps (positive or negative).
        
        Args:
            steps: Number of microsteps to move
            delay_us: Fixed delay between steps in microseconds (0 for default)
            accel_start_delay_us: Starting delay for acceleration ramp (0 for default)
            accel_steps: Number of steps to accelerate (0 for no acceleration)
            decel_steps: Number of steps to decelerate (0 for no deceleration)
        """
        if steps == 0:
            return True
        payload = struct.pack("<i", steps) # 4 bytes, little-endian signed integer
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_MOVE_STEPS, self._channel, payload)
        # Update persistent position
        self._current_position_steps += steps
        setStepperPosition(self._name, self._current_position_steps)
        return bool(res.payload[0])
    
    def move_at_speed(self, speed: int) -> bool:
        """Move the stepper at a given speed in microsteps per second."""
        payload = struct.pack("<i", speed) # 4 bytes, little-endian signed integer
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_MOVE_AT_SPEED, self._channel, payload)
        return bool(res.payload[0])

    def move_steps_blocking(self, steps: int, timeout_ms: int = 5000) -> bool:
        """
        Move the stepper by a given number of microsteps and wait for completion.
        
        Args:
            steps: Number of microsteps to move
            timeout_ms: Maximum time to wait in milliseconds
            
        Returns:
            True if move completed successfully, False if timeout
        """
        if steps == 0:
            return True
        
        self.move_steps(steps)
        
        # Wait for stepper to stop, with timeout
        import time
        start_time = time.time()
        timeout_sec = timeout_ms / 1000.0
        
        while time.time() - start_time < timeout_sec:
            if self.stopped:
                return True
            time.sleep(0.01)  # Poll every 10ms
        
        return False  # Timeout
    
    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        """Set the minimum and maximum speed for the stepper in microsteps per second."""
        payload = struct.pack("<II", min_speed, max_speed) # 8 bytes, two little-endian unsigned integers
        self._dev.send_command(InterfaceCommandCode.STEPPER_SET_SPEED_LIMITS, self._channel, payload)
    
    def set_acceleration(self, acceleration: int) -> None:
        """Set the acceleration for the stepper in microsteps per second squared."""
        payload = struct.pack("<I", acceleration)  # 4 bytes, little-endian unsigned integer
        self._dev.send_command(InterfaceCommandCode.STEPPER_SET_ACCELERATION, self._channel, payload)
    
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
    def position(self, position: int):
        """Set the current position of the stepper in microsteps."""
        payload = struct.pack("<i", position) # 4 bytes, little-endian signed integer
        self._dev.send_command(InterfaceCommandCode.STEPPER_SET_POSITION, self._channel, payload)
    
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
        
        payload = struct.pack("<iB?", home_speed, pin_channel, bool(home_pin_active_high)) # 4 bytes for speed (signed), 1 byte for pin channel, 1 byte for active high/low
        self._dev.send_command(InterfaceCommandCode.STEPPER_HOME, self._channel, payload)
    
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
    
    @property
    def current_position_steps(self) -> int:
        """Get the current position in microsteps."""
        return self._current_position_steps
    
    @property
    def total_steps_per_rev(self) -> int:
        """Get the total microsteps per revolution (considering microsteps)."""
        return self._steps_per_revolution * self._microsteps

    def set_name(self, name: str) -> None:
        """Set a human-readable name for persistent position tracking."""
        self._name = name
        self._current_position_steps = getStepperPosition(name)
    
    def estimateMoveStepsMs(self, steps: int, max_speed: int = 5000) -> int:
        """
        Estimate the time (in milliseconds) it will take to move a given number of steps.
        
        This is a rough approximation assuming constant acceleration and deceleration.
        
        Args:
            steps: Number of steps to move
            max_speed: Maximum speed in microsteps per second (default 5000)
        
        Returns:
            Estimated time in milliseconds
        """
        if steps == 0:
            return 0
        steps = abs(steps)
        # Very rough estimate: assume we can do max_speed microsteps per second
        # This doesn't account for acceleration/deceleration ramps
        estimated_seconds = steps / max_speed
        return max(1, int(estimated_seconds * 1000))


class ServoMotor:
    """Servo motor controlled through I2C PCA9685 servo driver."""

    def __init__(self, device: MCUDevice, channel: int):
        self._dev = device
        self._channel = channel
        self._current_angle = 0
        self._name = f"servo_{channel}"
        self._open_angle = 0
        self._closed_angle = 72
        # Load persisted position
        self._current_angle = getServoPosition(self._name)

    def move_to(self, angle: int) -> bool:
        """
        Move the servo to a given angle.
        
        Args:
            angle: Target angle in degrees (typically 0-180)
        
        Returns:
            True if successful
        """
        if not 0 <= angle <= 180:
            raise ValueError(f"Servo angle must be 0-180, got {angle}")
        
        payload = struct.pack("<B", angle)  # 1 byte, unsigned integer
        res = self._dev.send_command(InterfaceCommandCode.SERVO_MOVE_TO, self._channel, payload)
        self._current_angle = angle
        setServoPosition(self._name, angle)
        return bool(res.payload[0])

    def open(self, open_angle: int = None) -> None:
        """Move servo to open position."""
        target = open_angle if open_angle is not None else self._open_angle
        self.move_to(target)

    def close(self, closed_angle: int = None) -> None:
        """Move servo to closed position."""
        target = closed_angle if closed_angle is not None else self._closed_angle
        self.move_to(target)

    def toggle(self) -> None:
        """Toggle between open and closed."""
        if self._current_angle == self._open_angle:
            self.close()
        else:
            self.open()

    def isOpen(self) -> bool:
        """Check if servo is in open position."""
        return self._current_angle == self._open_angle

    def isClosed(self) -> bool:
        """Check if servo is in closed position."""
        return self._current_angle == self._closed_angle

    def set_name(self, name: str) -> None:
        """Set a human-readable name for persistent position tracking."""
        self._name = name
        self._current_angle = getServoPosition(name)

    def set_preset_angles(self, open_angle: int, closed_angle: int) -> None:
        """Set the open and closed preset angles."""
        self._open_angle = open_angle
        self._closed_angle = closed_angle

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        """Set the minimum and maximum speed for the servo."""
        payload = struct.pack("<II", min_speed, max_speed)
        self._dev.send_command(InterfaceCommandCode.SERVO_SET_SPEED_LIMITS, self._channel, payload)

    def set_acceleration(self, acceleration: int) -> None:
        """Set the acceleration for the servo."""
        payload = struct.pack("<I", acceleration)
        self._dev.send_command(InterfaceCommandCode.SERVO_SET_ACCELERATION, self._channel, payload)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the servo."""
        payload = struct.pack("<?", enabled)
        self._dev.send_command(InterfaceCommandCode.SERVO_SET_ENABLED, self._channel, payload)

    @property
    def angle(self) -> int:
        """Get the current servo angle."""
        return self._current_angle

    @property
    def channel(self):
        return self._channel

    @property
    def angle(self) -> int:
        """Get the current servo angle."""
        return self._current_angle

    @property
    def channel(self):
        return self._channel


class SorterInterface(MCUDevice):
    steppers : tuple[StepperMotor, ...]
    servos: tuple[ServoMotor, ...]
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
        servo_count = self._board_info.get("servo_count", 0)
        if servo_count == 0:
            # If firmware reports 0 servos, default to 4 for basic compatibility with PCA9685
            servo_count = 4
        servo_channels = range(servo_count)
        
        self.digital_inputs = tuple(DigitalInputPin(self, ch) for ch in digital_input_channels)
        self.digital_outputs = tuple(DigitalOutputPin(self, ch) for ch in digital_output_channels)
        self.steppers = tuple(StepperMotor(self, ch) for ch in stepper_channels)
        self.servos = tuple(ServoMotor(self, ch) for ch in servo_channels)
        
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
