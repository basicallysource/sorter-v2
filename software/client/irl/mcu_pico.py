"""RPi Pico MCU wrapper class that provides the same interface as the Arduino MCU class.

This wrapper translates Arduino-style text commands to high-level SorterInterface calls.
Rather than controlling individual pins, it routes stepper commands to the appropriate
StepperMotor objects in the SorterInterface.

Pin mappings are auto-detected from the Pico firmware hardware config files
(hwcfg_basically.h or hwcfg_skr_pico.h) with fallback to hardcoded defaults.
"""

import time
import queue
import threading
from typing import Callable
from global_config import GlobalConfig
from hardware.bus import MCUBus
from hardware.sorter_interface import SorterInterface
from .pico_pin_config import auto_configure_pico_pins


PICO_MCU_INIT_RETRY_COUNT = 5
PICO_MCU_INIT_RETRY_DELAY_MS = 100


class PicoMCU:
    """
    Wrapper for RPi Pico SorterInterface that provides Arduino MCU-compatible interface.
    
    Routes high-level stepper commands to SorterInterface StepperMotor objects.
    Ignores direct pin control commands since Pico firmware manages pins internally.
    """

    def __init__(self, gc: GlobalConfig, port: str):
        """
        Initialize the RPi Pico MCU via SorterInterface.
        
        Args:
            gc: GlobalConfig instance for logging
            port: Serial port path (e.g., "/dev/ttyACM0")
        """
        self.gc = gc
        self.port = port
        self.bus = None
        self.interface = None
        self.running = True
        self.callbacks = {}
        
        # Add command_queue and worker_thread for API compatibility with Arduino MCU
        self.command_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._dummy_worker, daemon=True)
        self.worker_thread.start()
        
        # Auto-detect pin mappings from firmware hardware config files
        stepper_pin_map, enable_pin_map = auto_configure_pico_pins()
        
        if stepper_pin_map and enable_pin_map:
            self._stepper_pin_map = stepper_pin_map
            self._enable_pin_to_stepper = enable_pin_map
            gc.logger.info("Auto-detected Pico pin configuration from firmware")
        else:
            # Fallback to default RAMPS 1.4 mappings for backward compatibility
            gc.logger.warning("Could not auto-detect Pico pins; using default RAMPS 1.4 mappings")
            self._stepper_pin_map = {
                (36, 34): 0,  # Carousel: step=36, dir=34, enable=30
                (26, 28): 1,  # Chute: step=26, dir=28, enable=24
                (46, 48): 2,  # First rotor: step=46, dir=48, enable=62
                (60, 61): 3,  # Second rotor: step=60, dir=61, enable=56
                (54, 55): 4,  # Third rotor: step=54, dir=55, enable=38
            }
            self._enable_pin_to_stepper = {
                30: (36, 34),  # Carousel enable
                24: (26, 28),  # Chute enable
                62: (46, 48),  # First rotor enable
                56: (60, 61),  # Second rotor enable
                38: (54, 55),  # Third rotor enable
            }
        
        # Track stepper enable states indexed by (step_pin, dir_pin) pair
        # Pico firmware manages pins internally; we just track state for compatibility
        self._stepper_enabled = {}
        
        # Initialize the bus and interface
        self._initialize_interface()
        
        gc.logger.info(f"Pico MCU initialized on {port}")

    def _initialize_interface(self) -> None:
        """Initialize MCUBus and SorterInterface."""
        for attempt in range(PICO_MCU_INIT_RETRY_COUNT):
            try:
                self.bus = MCUBus(port=self.port)
                devices = self.bus.scan_devices()
                
                if not devices:
                    raise RuntimeError("No Pico devices found on bus")
                
                # Initialize interface at first device address
                self.interface = SorterInterface(self.bus, devices[0])
                self.gc.logger.info(f"Pico interface initialized: {self.interface.name}")
                
                # Re-detect pin configuration based on actual board detected
                self._update_pin_config_from_interface()
                return
                
            except Exception as e:
                self.gc.logger.warning(f"Pico initialization attempt {attempt + 1} failed: {e}")
                if attempt < PICO_MCU_INIT_RETRY_COUNT - 1:
                    time.sleep(PICO_MCU_INIT_RETRY_DELAY_MS / 1000.0)
                else:
                    raise RuntimeError(f"Failed to initialize Pico MCU after {PICO_MCU_INIT_RETRY_COUNT} attempts")

    def _update_pin_config_from_interface(self) -> None:
        """Update pin configuration based on the detected board."""
        from .pico_pin_config import parse_hwcfg_file, build_stepper_pin_map, build_enable_pin_map
        from pathlib import Path
        
        # Determine which hwcfg file to use based on interface name
        firmware_dir = Path(__file__).parent.parent.parent / "firmware" / "sorter_interface_firmware"
        
        config_file = None
        if "MB" in self.interface.name or "Basically" in self.interface.name:
            config_file = firmware_dir / "hwcfg_basically.h"
            self.gc.logger.info("Detected Basically board - loading hwcfg_basically.h")
        elif "SKR" in self.interface.name or "SKRPico" in self.interface.name:
            config_file = firmware_dir / "hwcfg_skr_pico.h"
            self.gc.logger.info("Detected SKR Pico board - loading hwcfg_skr_pico.h")
        
        if config_file and config_file.exists():
            config = parse_hwcfg_file(str(config_file))
            if config:
                self._stepper_pin_map = build_stepper_pin_map(config)
                self._enable_pin_to_stepper = build_enable_pin_map(config)
                self.gc.logger.info(f"Stepper pin mappings loaded: {list(self._stepper_pin_map.keys())}")
                return
        
        self.gc.logger.warning("Could not load board-specific pin configuration")


    def _dummy_worker(self) -> None:
        """Dummy worker thread for API compatibility with Arduino MCU."""
        while self.running:
            time.sleep(0.1)

    def command(self, *args) -> None:
        """
        Process Arduino-style commands and translate them to high-level Pico interface.
        
        Supported commands:
        - P,pin,mode: pinMode (ignored - Pico firmware manages pins internally)
        - D,pin,value: digitalWrite (ignored for stepper enable pins; only logged)
        - T,step_pin,dir_pin,steps,delay_us,accel_start,accel_steps,decel_steps: Stepper move
        
        For stepper moves, the step_pin and dir_pin pair are used to identify the stepper,
        which is then controlled via high-level SorterInterface commands.
        """
        if not args or not self.running:
            return
        
        cmd = args[0]
        
        if cmd == "P":  # pinMode (ignored)
            # P,pin,mode -> configure pin (not needed for Pico)
            pin = args[1] if len(args) > 1 else None
            self.gc.logger.debug(f"Ignored pinMode command for pin {pin} (Pico manages pins internally)")
            
        elif cmd == "D":  # digitalWrite (routed or ignored)
            # D,pin,value -> digital write
            # For stepper enable pins, just track the state; don't control pins
            pin = args[1] if len(args) > 1 else None
            value = bool(args[2]) if len(args) > 2 else False
            self._handle_digital_write(pin, value)
            
        elif cmd == "T":  # Stepper move (trapezoid profile)
            # T,step_pin,dir_pin,steps,delay_us,accel_start,accel_steps,decel_steps
            if len(args) < 4:
                self.gc.logger.error(f"Invalid stepper command: {args}")
                return
            
            step_pin = int(args[1]) if len(args) > 1 else None
            dir_pin = int(args[2]) if len(args) > 2 else None
            steps = int(args[3]) if len(args) > 3 else 0
            extra_args = args[4:] if len(args) > 4 else []
            
            self._stepper_move_trapezoid(step_pin, dir_pin, steps, extra_args)
        
        else:
            self.gc.logger.warning(f"Unknown command: {cmd}")

    def _handle_digital_write(self, pin: int, value: bool) -> None:
        """
        Handle digitalWrite commands.
        
        For stepper enable pins, track the state and ignore direct pin control
        (Pico firmware manages enable/disable internally). For other pins,
        log them for debugging but don't control them.
        """
        if pin is None:
            return
        
        # Check if this is a stepper enable pin
        stepper_pins = self._enable_pin_to_stepper.get(pin)
        
        if stepper_pins:
            # Track enable state for compatibility
            self._stepper_enabled[stepper_pins] = value
            self.gc.logger.debug(
                f"Stepper enable: pins {stepper_pins} enable pin {pin} = {value} "
                f"(managed internally by Pico firmware)"
            )
        else:
            # Non-stepper I/O
            self.gc.logger.debug(f"digitalWrite: pin {pin} = {value} (not mapped)")

    def _stepper_move_trapezoid(self, step_pin: int, dir_pin: int, steps: int, extra_args: list) -> None:
        """
        Execute a stepper move command using high-level SorterInterface.
        
        Routes the command to the appropriate StepperMotor object based on pin pair.
        The trapezoid profile parameters (accel, decel) are ignored for now but
        could be extended in the Pico firmware.
        
        Args:
            step_pin: Arduino step pin number
            dir_pin: Arduino direction pin number
            steps: Number of microsteps to move
            extra_args: [delay_us, accel_start_delay_us, accel_steps, decel_steps]
        """
        if step_pin is None or dir_pin is None:
            self.gc.logger.error(f"Invalid stepper move: step_pin={step_pin}, dir_pin={dir_pin}")
            return
        
        try:
            # Look up which stepper channel this pin pair maps to
            stepper_channel = self._stepper_pin_map.get((step_pin, dir_pin))
            
            if stepper_channel is None:
                self.gc.logger.warning(
                    f"Stepper pin pair ({step_pin}, {dir_pin}) not mapped. "
                    f"Available mappings: {list(self._stepper_pin_map.keys())}"
                )
                return
            
            # Check if stepper channel is valid
            if stepper_channel >= len(self.interface.steppers):
                self.gc.logger.error(
                    f"Stepper channel {stepper_channel} out of range. "
                    f"Available channels: 0-{len(self.interface.steppers) - 1}"
                )
                return
            
            # Get the stepper motor object
            stepper = self.interface.steppers[stepper_channel]
            
            # Only move if enabled (for compatibility with Arduino behavior)
            if self._stepper_enabled.get((step_pin, dir_pin), True):
                # Move the stepper using high-level command
                if steps != 0:
                    self.gc.logger.debug(
                        f"Stepper move attempting: pins ({step_pin},{dir_pin}) → channel {stepper_channel}, "
                        f"steps {steps}"
                    )
                    try:
                        result = stepper.move_steps(steps)
                        self.gc.logger.debug(
                            f"Stepper move succeeded: pins ({step_pin},{dir_pin}) → channel {stepper_channel}, "
                            f"steps {steps}"
                        )
                    except Exception as move_error:
                        self.gc.logger.warning(
                            f"Stepper move failed: pins ({step_pin},{dir_pin}), steps {steps}: {move_error}"
                        )
                else:
                    self.gc.logger.debug(f"Stepper no-op: steps = {steps}")
            else:
                self.gc.logger.debug(
                    f"Stepper move ignored: pins ({step_pin},{dir_pin}) disabled"
                )
                
        except Exception as e:
            self.gc.logger.error(f"Error in stepper move: {e}")

    def registerCallback(self, message_type: str, callback: Callable) -> None:
        """Register a callback for a message type (for compatibility with Arduino MCU)."""
        self.callbacks[message_type] = callback

    def flush(self) -> None:
        """Flush any pending commands (for compatibility)."""
        # Pico interface sends commands immediately, so nothing to flush
        pass

    def close(self) -> None:
        """Close the MCU connection."""
        self.gc.logger.info("Closing Pico MCU connection...")
        self.running = False
        
        try:
            if self.interface:
                self.interface.shutdown()
            if self.bus and self.bus._serial:
                self.bus._serial.close()
        except Exception as e:
            self.gc.logger.error(f"Error closing Pico MCU: {e}")
