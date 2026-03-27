"""Implementation of the Sorter Interface hardware drivers"""

# Copyright (c) 2026 Jose I. Romero
#
# Licensed under the MIT License. See LICENSE file in the project root for full license information.


import time
from .bus import MCUDevice, BaseCommandCode
import struct
from global_config import GlobalConfig

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
    SERVO_MOVE_TO = 0x40
    SERVO_SET_SPEED_LIMITS = 0x41
    SERVO_SET_ACCELERATION = 0x42
    SERVO_GET_POSITION = 0x43
    SERVO_IS_STOPPED = 0x44
    SERVO_STOP = 0x45
    SERVO_SET_ENABLED = 0x46
    SERVO_SET_DUTY_LIMITS = 0x47
    SERVO_MOVE_TO_AND_RELEASE = 0x48


class DigitalInputPin:
    def __init__(self, device: MCUDevice, channel: int, gc: GlobalConfig):
        self._dev = device
        self._channel = channel
        self._gc = gc

    @property
    def value(self):
        res = self._dev.send_command(InterfaceCommandCode.DIGITAL_READ, self._channel, b'')
        return bool(res.payload[0])
    
    @property
    def channel(self):
        return self._channel
    
class DigitalOutputPin:
    def __init__(self, device: MCUDevice, channel: int, gc: GlobalConfig):
        self._dev = device
        self._channel = channel
        self._value = False
        self._enabled = True
        self._gc = gc

    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, value: bool):
        self._value = bool(value)
        self._gc.logger.info(f"DigitalOutput ch{self._channel}: set value={self._value}")
        payload = struct.pack("<?", self._value) # 1 byte, boolean
        self._dev.send_command(InterfaceCommandCode.DIGITAL_WRITE, self._channel, payload)
    
    @property
    def channel(self):
        return self._channel

class StepperMotor:
    def __init__(self, device: MCUDevice, channel: int, gc: GlobalConfig):
        self._dev = device
        self._channel = channel
        self._steps_per_revolution = 200
        self._microsteps = 8
        self._enabled = True
        self._name = f"stepper_{channel}"
        self._hardware_name = self._name
        self._direction_inverted = False
        self._current_position_steps = 0
        self._gc = gc

    def _logical_to_physical_steps(self, value: int) -> int:
        return -value if self._direction_inverted else value

    def _physical_to_logical_steps(self, value: int) -> int:
        return -value if self._direction_inverted else value

    def move_degrees(self, degrees: float) -> bool:
        """
        Move the stepper by a given number of degrees (positive or negative).
        Uses steps_per_revolution to calculate the number of steps.
        """
        steps = self.microsteps_for_degrees(degrees)
        return self.move_steps(steps)

    def move_steps(self, steps: int) -> bool:
        """Move the stepper by a given number of microsteps (positive or negative)."""
        if steps == 0:
            return True
        physical_steps = self._logical_to_physical_steps(steps)
        self._gc.logger.info(
            f"Stepper '{self._name}' (hw='{self._hardware_name}') ch{self._channel}: "
            f"move_steps logical={steps} physical={physical_steps} microsteps "
            f"({self.degrees_for_microsteps(steps):.2f}°), pos_before={self._current_position_steps}, "
            f"inverted={self._direction_inverted}"
        )
        payload = struct.pack("<i", physical_steps) # 4 bytes, little-endian signed integer
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_MOVE_STEPS, self._channel, payload)
        success = len(res.payload) > 0 and bool(res.payload[0])
        if success:
            self._current_position_steps += steps
        else:
            self._gc.logger.error(f"Stepper '{self._name}' ch{self._channel}: move_steps({steps}) FAILED")
        return success
    
    def move_at_speed(self, speed: int) -> bool:
        """Move the stepper at a given speed in microsteps per second."""
        physical_speed = self._logical_to_physical_steps(speed)
        self._gc.logger.info(
            f"Stepper '{self._name}' (hw='{self._hardware_name}') ch{self._channel}: "
            f"move_at_speed logical={speed} physical={physical_speed} µsteps/s, "
            f"inverted={self._direction_inverted}"
        )
        payload = struct.pack("<i", physical_speed) # 4 bytes, little-endian signed integer
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_MOVE_AT_SPEED, self._channel, payload)
        success = bool(res.payload[0])
        if not success:
            self._gc.logger.error(f"Stepper '{self._name}' ch{self._channel}: move_at_speed({speed}) FAILED")
        return success
    
    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        """Set the minimum and maximum speed for the stepper in microsteps per second."""
        self._gc.logger.info(f"Stepper '{self._name}' ch{self._channel}: set_speed_limits min={min_speed} max={max_speed} µsteps/s")
        payload = struct.pack("<II", min_speed, max_speed) # 8 bytes, two little-endian unsigned integers
        self._dev.send_command(InterfaceCommandCode.STEPPER_SET_SPEED_LIMITS, self._channel, payload)

    def set_acceleration(self, acceleration: int) -> None:
        """Set the acceleration for the stepper in microsteps per second squared."""
        self._gc.logger.info(f"Stepper '{self._name}' ch{self._channel}: set_acceleration={acceleration} µsteps/s²")
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
        return self._physical_to_logical_steps(struct.unpack("<i", res.payload)[0])

    @position.setter
    def position(self, position: int):
        """Set the current position of the stepper in microsteps."""
        self._gc.logger.info(f"Stepper '{self._name}' ch{self._channel}: set_position={position} microsteps ({self.degrees_for_microsteps(position):.2f}°)")
        payload = struct.pack("<i", self._logical_to_physical_steps(position))
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
        
        physical_speed = self._logical_to_physical_steps(home_speed)
        self._gc.logger.info(
            f"Stepper '{self._name}' (hw='{self._hardware_name}') ch{self._channel}: "
            f"home logical_speed={home_speed} physical_speed={physical_speed} µsteps/s, "
            f"pin={pin_channel}, active_high={home_pin_active_high}, inverted={self._direction_inverted}"
        )
        payload = struct.pack("<iB?", physical_speed, pin_channel, bool(home_pin_active_high)) # 4 bytes for speed (signed), 1 byte for pin channel, 1 byte for active high/low
        self._dev.send_command(InterfaceCommandCode.STEPPER_HOME, self._channel, payload)
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable the stepper."""
        self._enabled = bool(value)
        self._gc.logger.info(f"Stepper '{self._name}' ch{self._channel}: set_enabled={self._enabled}")
        payload = struct.pack("<?", self._enabled) # 1 byte, boolean
        self._dev.send_command(InterfaceCommandCode.STEPPER_DRV_SET_ENABLED, self._channel, payload)
    
    def set_microsteps(self, microsteps: int):
        """Set the microsteps for the stepper."""
        if microsteps not in (1, 2, 4, 8, 16, 32, 64, 128, 256):
            raise ValueError(f"Invalid microsteps value: {microsteps}.")
        self._gc.logger.info(f"Stepper '{self._name}' ch{self._channel}: set_microsteps={microsteps}")
        payload = struct.pack("<H", microsteps) # 2 bytes, little-endian unsigned integer
        self._dev.send_command(InterfaceCommandCode.STEPPER_DRV_SET_MICROSTEPS, self._channel, payload)
        self._microsteps = microsteps
    
    def set_current(self, irun: int, ihold: int, ihold_delay: int):
        self._gc.logger.info(f"Stepper '{self._name}' ch{self._channel}: set_current irun={irun} ihold={ihold} ihold_delay={ihold_delay}")
        payload = struct.pack("<BBB", irun, ihold, ihold_delay) # 3 bytes, three little-endian unsigned integers
        self._dev.send_command(InterfaceCommandCode.STEPPER_DRV_SET_CURRENT, self._channel, payload)

    def read_driver_register(self, address: int) -> int:
        self._gc.logger.info(f"Stepper '{self._name}' ch{self._channel}: read_driver_register addr=0x{address:02X}")
        payload = struct.pack("<B", address) # 1 byte, unsigned integer
        res = self._dev.send_command(InterfaceCommandCode.STEPPER_DRV_READ_REGISTER, self._channel, payload)
        val = struct.unpack("<I", res.payload)[0] # 4 bytes, little-endian unsigned integer
        self._gc.logger.info(f"Stepper '{self._name}' ch{self._channel}: read_driver_register addr=0x{address:02X} -> 0x{val:08X}")
        return val

    def write_driver_register(self, address: int, value: int):
        self._gc.logger.info(f"Stepper '{self._name}' ch{self._channel}: write_driver_register addr=0x{address:02X} value=0x{value:08X}")
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
        """Set a human-readable name for this stepper."""
        self._name = name

    def set_hardware_name(self, name: str) -> None:
        """Set the physical firmware-reported name for this stepper."""
        self._hardware_name = name

    @property
    def hardware_name(self) -> str:
        return self._hardware_name

    def set_direction_inverted(self, inverted: bool) -> None:
        self._direction_inverted = bool(inverted)
        self._gc.logger.info(
            f"Stepper '{self._name}' (hw='{self._hardware_name}') ch{self._channel}: "
            f"set_direction_inverted={self._direction_inverted}"
        )

    @property
    def direction_inverted(self) -> bool:
        return self._direction_inverted

    def move_steps_blocking(self, steps: int, timeout_ms: int = 5000) -> bool:
        """Move the stepper by a given number of microsteps and wait for completion."""
        if steps == 0:
            return True
        self.move_steps(steps)
        start_time = time.time()
        timeout_sec = timeout_ms / 1000.0
        while time.time() - start_time < timeout_sec:
            if self.stopped:
                return True
            time.sleep(0.01)
        return False

    def move_degrees_blocking(self, degrees: float, timeout_ms: int = 5000) -> bool:
        """Move by degrees and wait for completion."""
        steps = self.microsteps_for_degrees(degrees)
        return self.move_steps_blocking(steps, timeout_ms=timeout_ms)

    def estimateMoveStepsMs(self, steps: int, max_speed: int = 5000) -> int:
        """Estimate the time (in milliseconds) it will take to move a given number of steps."""
        if steps == 0:
            return 0
        steps = abs(steps)
        estimated_seconds = steps / max_speed
        return max(1, int(estimated_seconds * 1000))

    def estimateMoveDegreesMs(self, degrees: float, max_speed: int = 5000) -> int:
        """Estimate movement time for a move specified in degrees."""
        steps = self.microsteps_for_degrees(degrees)
        return self.estimateMoveStepsMs(steps, max_speed=max_speed)

    def microsteps_for_degrees(self, degrees: float) -> int:
        """Convert degrees to microsteps using current motor configuration."""
        return int(
            round((degrees / 360.0) * self._steps_per_revolution * self._microsteps)
        )

    def degrees_for_microsteps(self, steps: int) -> float:
        """Convert microsteps to degrees using current motor configuration."""
        return (float(steps) / (self._steps_per_revolution * self._microsteps)) * 360.0


class ServoMotor:
    def __init__(self, device: MCUDevice, channel: int, gc: GlobalConfig):
        self._dev = device
        self._channel = channel
        self._name = f"servo_{channel}"
        self._current_angle = 0
        self._open_angle = 0
        self._closed_angle = 72
        # Track enabled state locally; the firmware does not provide a GET for enabled.
        self._enabled = False
        self._gc = gc

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        bool_value = bool(value)
        self._gc.logger.info(f"Servo '{self._name}' ch{self._channel}: set_enabled={bool_value}")
        payload = struct.pack("<?", bool_value) # 1 byte, boolean
        self._dev.send_command(InterfaceCommandCode.SERVO_SET_ENABLED, self._channel, payload)
        self._enabled = bool_value

    def move_to(self, angle: int) -> bool:
        """Move the servo to a given angle in degrees (0-180)."""
        if not 0 <= angle <= 180:
            raise ValueError(f"Servo angle must be 0-180, got {angle}")
        if not self._enabled:
            self.enabled = True
        self._gc.logger.info(f"Servo '{self._name}' ch{self._channel}: move_to {angle}° (from {self._current_angle}°)")
        payload = struct.pack("<H", angle * 10)  # Convert degrees to 0.1° units, 2 bytes uint16
        res = self._dev.send_command(InterfaceCommandCode.SERVO_MOVE_TO, self._channel, payload)
        self._current_angle = angle
        return bool(res.payload[0])

    def move_to_and_release(self, angle: int) -> bool:
        """Move the servo to a given angle and auto-disable upon arrival.

        The servo will move to the target angle and then automatically stop
        sending PWM once it reaches the position, preventing damage from
        continuous holding torque.
        """
        if not 0 <= angle <= 180:
            raise ValueError(f"Servo angle must be 0-180, got {angle}")
        if not self._enabled:
            self.enabled = True
        self._gc.logger.info(f"Servo '{self._name}' ch{self._channel}: move_to_and_release {angle}° (from {self._current_angle}°)")
        payload = struct.pack("<H", angle * 10)  # Convert degrees to 0.1° units, 2 bytes uint16
        res = self._dev.send_command(InterfaceCommandCode.SERVO_MOVE_TO_AND_RELEASE, self._channel, payload)
        self._current_angle = angle
        self._enabled = False  # Will be disabled once the move completes
        return bool(res.payload[0])

    @property
    def position(self) -> int:
        """Get the current position of the servo in tenths of degrees."""
        res = self._dev.send_command(InterfaceCommandCode.SERVO_GET_POSITION, self._channel, b'')
        return struct.unpack("<H", res.payload)[0] # 2 bytes, little-endian unsigned integer

    def stop(self):
        """Stop the servo immediately"""
        self._gc.logger.info(f"Servo '{self._name}' ch{self._channel}: stop (was at {self._current_angle}°)")
        self._dev.send_command(InterfaceCommandCode.SERVO_STOP, self._channel, b'')

    @property
    def stopped(self) -> bool:
        """Check if the servo is stopped."""
        res = self._dev.send_command(InterfaceCommandCode.SERVO_IS_STOPPED, self._channel, b'')
        return bool(res.payload[0])

    def open(self, open_angle: int | None = None) -> None:
        """Move servo to open position."""
        target = open_angle if open_angle is not None else self._open_angle
        self.move_to_and_release(target)

    def close(self, closed_angle: int | None = None) -> None:
        """Move servo to closed position."""
        target = closed_angle if closed_angle is not None else self._closed_angle
        self.move_to_and_release(target)

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

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        """Set the minimum and maximum speed for the servo in tenths of degrees per second."""
        if min_speed < 0 or max_speed < 0:
            raise ValueError("Speed limits must be non-negative")
        if min_speed >= max_speed:
            raise ValueError("min_speed must be less than max_speed")
        self._gc.logger.info(f"Servo '{self._name}' ch{self._channel}: set_speed_limits min={min_speed} max={max_speed} 0.1°/s")
        payload = struct.pack("<HH", min_speed, max_speed) # 4 bytes, two little-endian unsigned integers
        self._dev.send_command(InterfaceCommandCode.SERVO_SET_SPEED_LIMITS, self._channel, payload)

    def set_acceleration(self, acceleration: int) -> None:
        """Set the acceleration for the servo in tenths of degrees per second squared."""
        self._gc.logger.info(f"Servo '{self._name}' ch{self._channel}: set_acceleration={acceleration} 0.1°/s²")
        payload = struct.pack("<H", acceleration)  # 2 bytes, little-endian unsigned integer
        self._dev.send_command(InterfaceCommandCode.SERVO_SET_ACCELERATION, self._channel, payload)

    def set_duty_limits(self, min_duty_us: int, max_duty_us: int) -> None:
        """Set the minimum and maximum duty cycle for the servo in microseconds.

         min_duty_us: Pulse width in microseconds (e.g. 1000 for 1ms) for the minimum position (0 degrees)
         max_duty_us: Pulse width in microseconds (e.g. 2000 for 2ms) for the maximum position (180 degrees)
        """
        if min_duty_us < 0 or max_duty_us < 0:
            raise ValueError("Duty limits must be non-negative")
        if min_duty_us >= max_duty_us:
            raise ValueError("min_duty_us must be less than max_duty_us")
        if max_duty_us > 20000:
            raise ValueError("max_duty_us must be less than or equal to 20000 (20ms period)")
        # Convert pulse widths (in microseconds) to PCA9685 12-bit counts (0-4095)
        # assuming a 20ms period (50Hz): counts = (pulse_us / 20000us) * 4095.
        min_duty = int((min_duty_us / 20000.0) * 4095)
        max_duty = int((max_duty_us / 20000.0) * 4095)
        self._gc.logger.info(f"Servo '{self._name}' ch{self._channel}: set_duty_limits {min_duty_us}µs-{max_duty_us}µs (counts {min_duty}-{max_duty})")
        payload = struct.pack("<HH", min_duty, max_duty)  # 4 bytes, two little-endian unsigned integers
        self._dev.send_command(InterfaceCommandCode.SERVO_SET_DUTY_LIMITS, self._channel, payload)

    def set_name(self, name: str) -> None:
        """Set a human-readable name for this servo."""
        self._name = name

    def set_preset_angles(self, open_angle: int, closed_angle: int) -> None:
        """Set the open and closed preset angles."""
        self._open_angle = open_angle
        self._closed_angle = closed_angle

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

    def __init__(self, bus, address, gc: GlobalConfig):
        super().__init__(bus, address)
        self._gc = gc
        # Obtain the device information to populate the internal objects
        retries = 5
        while retries > 0:
            try:
                self._board_info = self.detect()
                break
            except Exception as e:
                gc.logger.warning(f"Error initializing device: {e}. Retrying...")
                retries -= 1
                time.sleep(0.1)
        else:
            raise RuntimeError("Failed to initialize device.")
        # Populate the objects for all the capabilities based on the detected information
        digital_input_channels = range(self._board_info.get("digital_input_count", 0))
        digital_output_channels = range(self._board_info.get("digital_output_count", 0))
        stepper_channels = range(self._board_info.get("stepper_count", 0))
        servo_channels = range(self._board_info.get("servo_count", 0))
        self.digital_inputs = tuple(DigitalInputPin(self, ch, gc) for ch in digital_input_channels)
        self.digital_outputs = tuple(DigitalOutputPin(self, ch, gc) for ch in digital_output_channels)
        self.steppers = tuple(StepperMotor(self, ch, gc) for ch in stepper_channels)
        self.servos = tuple(ServoMotor(self, ch, gc) for ch in servo_channels)
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
    import logging as _logging
    import random
    import time
    from .bus import MCUBus
    from global_config import mkGlobalConfig

    _logging.basicConfig(level=_logging.INFO)
    _gc = mkGlobalConfig()

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
                interface = SorterInterface(bus, device, _gc)
                interfaces[interface.name] = interface
                print(f"Initialized interface: {interface.name}")
            except Exception as e:
                _logging.error(f"Error initializing device at address {device}: {e}")
                continue
        _logging.info(f"Finished initializing interfaces: {list(interfaces.keys())}")
        start_time = time.monotonic()
        while True:
            now = time.monotonic()
            elapsed = now - start_time
            if elapsed > 1:
                for name, interface in interfaces.items():
                    _logging.info(f"Interface {name}:")
                    for i, stepper in enumerate(interface.steppers):
                        _logging.info(f"  Stepper {i}: position={stepper.position}, stopped={stepper.stopped}")
                    for i, dout in enumerate(interface.digital_outputs):
                        _logging.info(f"  Digital Output {i}: value={dout.value}")
                    for i, din in enumerate(interface.digital_inputs):
                        _logging.info(f"  Digital Input {i}: value={din.value}")
                start_time = now
            for name, interface in interfaces.items():
                if interface.servos and all(servo.stopped for servo in interface.servos):
                    for servo in interface.servos:
                        servo.enabled = True
                        servo.set_speed_limits(100, 20000) # Set speed limits to 10-2000 degrees per second
                        servo.set_acceleration(2000)
                        angle = random.choice([0, 90, 180]) # Move to either 0, 90, or 180 degrees
                        _logging.info(f"Moving servo {servo.channel} on interface {name} to {angle} degrees")
                        servo.move_to_and_release(angle)

                for stepper in interface.steppers:
                    if not stepper.stopped:
                        continue
                    # Randomly decide to move the stepper
                    steps = random.randint(-1000, 1000)
                    _logging.info(f"Moving stepper {stepper.channel} on interface {name} by {steps} steps")
                    stepper.move_steps(steps)
            time.sleep(0.01)
