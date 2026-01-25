"""
Full-Featured TMC2209 Stepper Motor Driver Class
Supports both STEP/DIR control and UART configuration
Based on working UART implementation and TMC2209 datasheet
"""

import machine
import time

class register:
    def __init__(self, address, size):
        self.address = address
        self.size = size

class TMC2209:
    """
    Complete TMC2209 stepper motor driver with UART support
    """
    
    # Register              address, size (bits)
    GCONF =         register( 0x00, 10)
    GSTAT =         register( 0x01, 3)
    IFCNT =         register( 0x02, 8)
    SLAVECONF =     register( 0x03, 4)
    IOIN =          register( 0x06, 18)
    IHOLD_IRUN =    register( 0x10, 14)
    TPOWERDOWN =    register( 0x11, 8)
    TSTEP =         register( 0x12, 20)
    TPWMTHRS =      register( 0x13, 20)
    TCOOLTHRS =     register( 0x14, 20)
    SGTHRS =        register( 0x40, 8)
    SG_RESULT =     register( 0x41, 10)
    COOLCONF =      register( 0x42, 16)
    MSCNT =         register( 0x6A, 10)
    MSCURACT =      register( 0x6B, 18)
    CHOPCONF =      register( 0x6C, 32)
    DRV_STATUS =    register( 0x6F, 32)
    PWMCONF =       register( 0x70, 22)
    PWM_SCALE =     register( 0x71, 17)
    PWM_AUTO =      register( 0x72, 16)
    
    def __init__(self, step_pin, dir_pin, en_pin, 
                 uart_id=0, tx_pin=0, rx_pin=1, baudrate=230400,
                 motor_id=0, steps_per_rev=200):
        """
        Initialize TMC2209 driver
        
        Args:
            step_pin: GPIO pin for STEP
            dir_pin: GPIO pin for DIR
            en_pin: GPIO pin for EN (enable)
            uart_id: UART peripheral (0 or 1)
            tx_pin: TX GPIO pin for UART
            rx_pin: RX GPIO pin for UART
            baudrate: UART baudrate (230400 recommended, 115200 also works)
            motor_id: TMC2209 slave address (0-3)
            steps_per_rev: Full steps per revolution (default 200 for 1.8° motors)
        """
        # Setup GPIO pins
        self.step = machine.Pin(step_pin, machine.Pin.OUT)
        self.dir = machine.Pin(dir_pin, machine.Pin.OUT)
        self.en = machine.Pin(en_pin, machine.Pin.OUT)
        
        # Initialize pins
        self.step.value(0)
        self.dir.value(0)
        self.en.value(1)  # Disabled initially (active low)
        
        # Motor parameters
        self.steps_per_rev = steps_per_rev
        self.current_position = 0
        self.microsteps = 16  # Default microstepping
        
        # UART setup - match working test_uart.py exactly
        self.uart = machine.UART(uart_id, baudrate=baudrate, bits=8, parity=None, stop=1,
                                tx=machine.Pin(tx_pin), rx=machine.Pin(rx_pin))
        
        self.motor_id = motor_id
        self.comm_pause = 500 / baudrate  # ms
        
        print("\n=== TMC2209 Initialized ===")
        print("  STEP: GPIO{}, DIR: GPIO{}, EN: GPIO{}".format(step_pin, dir_pin, en_pin))
        print("  UART{} at {} baud (TX: GPIO{}, RX: GPIO{})".format(
            uart_id, baudrate, tx_pin, rx_pin))
        print("  Motor ID: {}".format(motor_id))
        print("  Comm Pause: {:.3f}ms".format(self.comm_pause))
    
    # ============================================================================
    # UART Communication Functions
    # ============================================================================
    
    def _calc_crc(self, data):
        """Calculate CRC8-ATM for TMC2209 UART"""
        crc = 0
        for byte in data:
            for _ in range(8):
                if (crc >> 7) ^ (byte & 0x01):
                    crc = ((crc << 1) ^ 0x07) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
                byte = byte >> 1
        return crc
    
    def write_reg(self, reg, value):
        """
        Write to TMC2209 register via UART
        
        Args:
            reg_addr: Register address
            value: 32-bit value to write
        """
        reg_addr = reg.address
        
        # Build write datagram
        frame = bytearray([
            0x55,  # Sync
            self.motor_id,
            reg_addr | 0x80,  # Write bit
            (value >> 24) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
            0
        ])
        frame[7] = self._calc_crc(frame[:7])
        
        self.uart.write(frame)
        time.sleep(self.comm_pause / 1000)
    
    def read_reg(self, reg):
        """
        Read from TMC2209 register via UART
        
        Returns: 4-byte value or None if failed
        """
        reg_addr = reg.address
        
        # Build read request
        frame = bytearray([0x55, self.motor_id, reg_addr, 0])
        frame[3] = self._calc_crc(frame[:3])
        
        self.uart.write(frame)
        time.sleep(self.comm_pause / 1000)
        
        # Read response (12 bytes expected)
        if self.uart.any():
            response = self.uart.read()
            time.sleep(self.comm_pause / 1000)
            
            if len(response) >= 11:
                # Extract data bytes [7:11]
                return response[7:11]
        
        return None
    
    def read_int(self, reg):
        """
        Read register and return as integer
        
        Returns: Integer value or None if failed
        """
        data = self.read_reg(reg)
        if data and len(data) >= 4:
            value = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
            # Mask the value to only include valid bits based on register size
            mask = (1 << reg.size) - 1
            return value & mask
        return None
    
    def test_uart(self):
        """Test UART communication"""
        ioin = self.read_int(self.IOIN)
        if ioin is not None:
            print("UART OK - IOIN: 0x{:08X}".format(ioin))
            return True
        else:
            print("UART communication failed")
            return False
    
    # ============================================================================
    # Basic Motor Control
    # ============================================================================
    
    def enable(self):
        """Enable the motor driver"""
        self.en.value(0)  # Active low
        time.sleep_ms(10)
    
    def disable(self):
        """Disable the motor driver"""
        self.en.value(1)  # Active low
    
    def set_direction(self, clockwise=True):
        """Set rotation direction"""
        self.dir.value(1 if clockwise else 0)
    
    def step_once(self, delay_us=1000):
        """Execute a single step pulse"""
        self.step.value(1)
        time.sleep_us(2)
        self.step.value(0)
        time.sleep_us(delay_us)
    
    def move_steps(self, steps, speed=500):
        """
        Move a specific number of steps
        
        Args:
            steps: Number of steps (negative for reverse)
            speed: Steps per second
        """
        if steps == 0:
            return
        
        self.set_direction(steps > 0)
        steps = abs(steps)
        delay = int(1000000 / speed)
        
        for _ in range(steps):
            self.step_once(delay)
            self.current_position += 1 if self.dir.value() else -1
    
    def rotate_degrees(self, degrees, speed=500):
        """Rotate by degrees"""
        steps = int((degrees / 360) * self.steps_per_rev * self.microsteps)
        self.move_steps(steps, speed)
    
    def rotate_revolutions(self, revolutions, speed=500):
        """Rotate by full revolutions"""
        steps = int(revolutions * self.steps_per_rev * self.microsteps)
        self.move_steps(steps, speed)
    
    def move_to_position(self, target_position, speed=500):
        """Move to absolute position"""
        steps = target_position - self.current_position
        self.move_steps(steps, speed)
    
    def set_position(self, position):
        """Set current position value (doesn't move motor)"""
        self.current_position = position
    
    def get_position(self):
        """Get current position in steps"""
        return self.current_position
    
    # ============================================================================
    # UART Configuration Functions
    # ============================================================================
    
    def set_current(self, run_current=16, hold_current=8, hold_delay=10):
        """
        Set motor current
        
        Args:
            run_current: Running current (0-31, 31=100%)
            hold_current: Holding current (0-31)
            hold_delay: Delay before reducing to hold current (0-15)
        """
        value = (hold_delay << 16) | (run_current << 8) | hold_current
        self.write_reg(self.IHOLD_IRUN, value)
        print("Current set: IRUN={}, IHOLD={}, IHOLDDELAY={}".format(
            run_current, hold_current, hold_delay))
    
    def set_microstepping(self, microsteps=16):
        """
        Set microstepping resolution
        
        Args:
            microsteps: 1, 2, 4, 8, 16, 32, 64, 128, or 256
        """
        mres_map = {256: 0, 128: 1, 64: 2, 32: 3, 16: 4, 8: 5, 4: 6, 2: 7, 1: 8}
        
        if microsteps not in mres_map:
            print("Invalid microsteps. Use: 1, 2, 4, 8, 16, 32, 64, 128, 256")
            return
        
        mres = mres_map[microsteps]
        self.microsteps = microsteps
        
        # Read current CHOPCONF
        chopconf = self.read_int(self.CHOPCONF)
        if chopconf is None:
            chopconf = 0x10000053  # Default value
        
        # Clear MRES bits [27:24] and set new value
        chopconf = (chopconf & ~(0xF << 24)) | (mres << 24)
        
        self.write_reg(self.CHOPCONF, chopconf)
        print("Microstepping set to 1/{}".format(microsteps))

    def set_stealthchop_enabled(self, enabled=True):
        """Enable or disable StealthChop mode"""
        gconf = self.read_int(self.GCONF)
        if gconf is None:
            gconf = 0x00000001  # Default
        
        if enabled:
            gconf &= ~(1 << 2)  # Clear en_spreadcycle bit
            print("StealthChop enabled")
        else:
            gconf |= (1 << 2)  # Set en_spreadcycle bit
            print("SpreadCycle enabled")
        
        self.write_reg(self.GCONF, gconf)
    
    def set_stealthchop_threshold(self, threshold=0):
        """
        Set upper velocity for StealthChop mode
        
        Args:
            threshold: TSTEP threshold (0=StealthChop only, high=switch to SpreadCycle)
        """
        self.write_reg(self.TPWMTHRS, threshold)
        if threshold == 0:
            print("StealthChop threshold: always StealthChop")
        else:
            print("StealthChop threshold set to {}".format(threshold))
    
    def set_spreadcycle_chopper(self, toff=3, hstart=5, hend=0, tbl=2):
        """
        Configure SpreadCycle chopper
        
        Args:
            toff: Off time (2-15, controls chopper frequency)
            hstart: Hysteresis start (0-7)
            hend: Hysteresis end (0-15)
            tbl: Blank time (0-3: 16/24/32/40 clocks)
        """
        chopconf = self.read_int(self.CHOPCONF)
        if chopconf is None:
            chopconf = 0x10000053
        
        # Clear and set TOFF [3:0]
        chopconf = (chopconf & ~0xF) | (toff & 0xF)
        
        # Clear and set HSTRT [6:4]
        chopconf = (chopconf & ~(0x7 << 4)) | ((hstart & 0x7) << 4)
        
        # Clear and set HEND [10:7]
        chopconf = (chopconf & ~(0xF << 7)) | ((hend & 0xF) << 7)
        
        # Clear and set TBL [16:15]
        chopconf = (chopconf & ~(0x3 << 15)) | ((tbl & 0x3) << 15)
        
        self.write_reg(self.CHOPCONF, chopconf)
        print("SpreadCycle: TOFF={}, HSTART={}, HEND={}, TBL={}".format(
            toff, hstart, hend, tbl))
    
    def set_pwm_config(self, pwm_ofs=36, pwm_grad=14, pwm_freq=1, pwm_autoscale=True):
        """
        Configure StealthChop PWM
        
        Args:
            pwm_ofs: User defined amplitude offset (0-255)
            pwm_grad: User defined amplitude gradient (0-255)
            pwm_freq: PWM frequency (0-3)
            pwm_autoscale: Enable automatic current scaling
        """
        pwmconf = self.read_int(self.PWMCONF)
        if pwmconf is None:
            pwmconf = 0xC10D0024  # Default
        
        # Set PWM_OFS [7:0]
        pwmconf = (pwmconf & ~0xFF) | (pwm_ofs & 0xFF)
        
        # Set PWM_GRAD [15:8]
        pwmconf = (pwmconf & ~(0xFF << 8)) | ((pwm_grad & 0xFF) << 8)
        
        # Set pwm_freq [17:16]
        pwmconf = (pwmconf & ~(0x3 << 16)) | ((pwm_freq & 0x3) << 16)
        
        # Set pwm_autoscale [18]
        if pwm_autoscale:
            pwmconf |= (1 << 18)
        else:
            pwmconf &= ~(1 << 18)
        
        # Set pwm_autograd [19] - same as autoscale typically
        if pwm_autoscale:
            pwmconf |= (1 << 19)
        else:
            pwmconf &= ~(1 << 19)
        
        self.write_reg(self.PWMCONF, pwmconf)
        print("PWM config: OFS={}, GRAD={}, FREQ={}, AUTOSCALE={}".format(
            pwm_ofs, pwm_grad, pwm_freq, pwm_autoscale))
    
    # ============================================================================
    # StallGuard Functions
    # ============================================================================
    
    def enable_stallguard(self, threshold=10):
        """
        Enable StallGuard for sensorless homing
        
        Args:
            threshold: StallGuard threshold (0-255, lower=more sensitive)
        """
        # Set threshold
        self.write_reg(self.SGTHRS, threshold)
        
        # Enable StallGuard by setting TCOOLTHRS
        # Use high value so it's always active
        self.write_reg(self.TCOOLTHRS, 0xFFFFF)
        
        print("StallGuard enabled with threshold={}".format(threshold))
    
    def disable_stallguard(self):
        """Disable StallGuard"""
        self.write_reg(self.SGTHRS, 0)
        self.write_reg(self.TCOOLTHRS, 0)
        print("StallGuard disabled")
    
    def read_stallguard(self):
        """Read StallGuard result (0-1023, lower=higher load)"""
        sg = self.read_int(self.SG_RESULT)
        if sg is not None:
            return sg & 0x3FF  # 10-bit result
        return None
    
    def is_stalled(self):
        """Check if motor is stalled"""
        status = self.read_int(self.DRV_STATUS)
        if status is not None:
            return bool(status & (1 << 24))  # stallGuard bit
        return False
    
    def home_with_stallguard(self, speed=200, threshold=10, max_steps=10000):
        """
        Perform sensorless homing using StallGuard
        
        Args:
            speed: Homing speed (steps/sec)
            threshold: StallGuard sensitivity
            max_steps: Maximum steps before timeout
            
        Returns: True if homing successful, False if timeout
        """
        print("\nHoming with StallGuard...")
        
        # Enable StallGuard
        self.enable_stallguard(threshold)
        time.sleep_ms(100)
        
        # Set direction
        self.set_direction(False)
        
        delay = int(1000000 / speed)
        
        for i in range(max_steps):
            self.step_once(delay)
            
            # Check for stall every 10 steps
            if i % 10 == 0:
                if self.is_stalled():
                    print("Stall detected at step {}".format(i))
                    self.current_position = 0
                    time.sleep_ms(10)
                    
                    # Back off
                    self.set_direction(True)
                    for _ in range(50):
                        self.step_once(delay * 2)
                    
                    print("Homing complete!")
                    return True
        
        print("Homing timeout")
        return False
    
    # ============================================================================
    # CoolStep Functions
    # ============================================================================
    
    def enable_coolstep(self, semin=5, semax=2, seup=1, sedn=0):
        """
        Enable CoolStep for automatic current reduction
        
        Args:
            semin: Minimum StallGuard value (0-15, 0=disable)
            semax: Maximum StallGuard value (0-15)
            seup: Current increment steps (0-3: 1/2/4/8)
            sedn: Current decrement steps (0-3: 1/2/8/32)
        """
        # COOLCONF register
        coolconf = (sedn << 13) | (seup << 5) | (semax << 8) | semin
        self.write_reg(self.COOLCONF, coolconf)
        
        # Set TCOOLTHRS - CoolStep active above this velocity
        self.write_reg(self.TCOOLTHRS, 0xFFFFF)
        
        print("CoolStep enabled: SEMIN={}, SEMAX={}, SEUP={}, SEDN={}".format(
            semin, semax, seup, sedn))
    
    def disable_coolstep(self):
        """Disable CoolStep"""
        self.write_reg(self.COOLCONF, 0)
        print("CoolStep disabled")
    
    # ============================================================================
    # Status and Diagnostics
    # ============================================================================
    
    def get_driver_status(self):
        """Get comprehensive driver status"""
        status = self.read_int(self.DRV_STATUS)
        if status is None:
            return None
        
        return {
            'stst': bool(status & (1 << 31)),  # Standstill
            'stealth': bool(status & (1 << 30)),  # StealthChop active
            'cs_actual': (status >> 16) & 0x1F,  # Actual current scale
            'ot': bool(status & (1 << 1)),  # Overtemperature
            'otpw': bool(status & (1 << 0)),  # Overtemperature pre-warning
            's2ga': bool(status & (1 << 2)),  # Short to ground A
            's2gb': bool(status & (1 << 3)),  # Short to ground B
            's2vsa': bool(status & (1 << 4)),  # Short to VS A
            's2vsb': bool(status & (1 << 5)),  # Short to VS B
            'ola': bool(status & (1 << 6)),  # Open load A
            'olb': bool(status & (1 << 7)),  # Open load B
            'stall': bool(status & (1 << 24))  # StallGuard
        }
    
    def get_tstep(self):
        """Get time between steps (velocity measurement)"""
        return self.read_int(self.TSTEP)
    
    def get_microstep_counter(self):
        """Get current microstep position (0-1023)"""
        return self.read_int(self.MSCNT)
    




    def set_use_mstep_reg(self, enable=True):
        """Enable or disable StealthChop mode"""
        gconf = self.read_int(self.GCONF)
        if gconf is None:
            gconf = 0x00000001  # Default
        
        print(f"Current GCONF 0: {gconf:08X}")
        if enable:
            gconf |= (1 << 7)  # Set en_spreadcycle bit
            print("use mstep_reg enabled")
        else:
            gconf &= ~(1 << 7)  # Clear en_spreadcycle bit
            print("use mstep_reg disabled")

        print(f"New GCONF: {gconf:08X}")
        
        self.write_reg(self.GCONF, gconf)
    
    def get_microstep_config(self, enable=True):
        # """Get microstep configuration"""
        # gconf = self.read_int(self.GCONF)
        # if gconf is None:
        #     return 11
        
        # print(f"Current GCONF 1: {gconf:08X}")
        # # mstep = gconf & (1 << 7)
        # # print(f"mstep: {gconf:08X}")
        # # mstep_en = bool(gconf & (1 << 7))
        # # mstep_en = bool((gconf >> 7) & 1)
        

        # chopconf = self.read_int(self.CHOPCONF)
        # if chopconf is None:
        #     return 12
        
        # mres = (chopconf >> 24) & 0x7
        # print(mres)
        # mres_map = {0: 256, 1: 128, 2: 64, 3: 32, 4: 16, 5: 8, 6: 4, 7: 2, 8: 1}
        # # if(not mstep_en):
        # #     return 13  # Full step
        # # else:
        # return mres_map.get(mres, 14)
        """Enable or disable StealthChop mode"""
        gconf = self.read_int(self.GCONF)
        if gconf is None:
            gconf = 0x00000001  # Default
        
        print(f"Current GCONF 0: {gconf:08X}")
        if enable:
            gconf |= (1 << 7)  # Set en_spreadcycle bit
            print("use mstep_reg enabled")
        else:
            gconf &= ~(1 << 7)  # Clear en_spreadcycle bit
            print("use mstep_reg disabled")

        print(f"New GCONF: {gconf:08X}")
        
        self.write_reg(self.GCONF, gconf)




    
    def print_status(self):
        """Print detailed driver status"""
        status = self.get_driver_status()
        if status is None:
            print("Failed to read driver status")
            return
        
        print("\n=== TMC2209 Status ===")
        print("Standstill: {}".format(status['stst']))
        print("StealthChop mode: {}".format(status['stealth']))
        print("Current scale: {}/31".format(status['cs_actual']))
        print("Overtemp: {}, Pre-warning: {}".format(status['ot'], status['otpw']))
        print("Short to GND: A={}, B={}".format(status['s2ga'], status['s2gb']))
        print("Short to VS: A={}, B={}".format(status['s2vsa'], status['s2vsb']))
        print("Open load: A={}, B={}".format(status['ola'], status['olb']))
        print("Stalled: {}".format(status['stall']))
    
    # ============================================================================
    # Initialization and Configuration
    # ============================================================================
    
    def configure_basic(self):
        """Basic configuration for most applications"""
        print("\n=== Configuring TMC2209 ===")
        
        # Enable driver
        self.enable()
        
        # Set current (adjust for your motor)
        self.set_current(run_current=2, hold_current=1)
        
        # Set microstepping
        self.set_microstepping(16)
        
        # Enable StealthChop
        self.set_stealthchop_enabled(True)
        
        # Configure PWM for StealthChop
        self.set_pwm_config(pwm_autoscale=True)
        
        print("Basic configuration complete!")
    
    def configure_performance(self):
        """High-performance configuration with hybrid mode"""
        print("\n=== Configuring for Performance ===")
        
        self.enable()
        self.set_current(run_current=25, hold_current=10)
        self.set_microstepping(16)
        
        # Enable StealthChop for low speeds
        self.set_stealthchop_enabled(True)
        
        # Switch to SpreadCycle at higher speeds
        self.set_stealthchop_threshold(500)
        
        # Configure SpreadCycle
        self.set_spreadcycle_chopper(toff=5, hstart=4, hend=1, tbl=2)
        
        # Configure StealthChop PWM
        self.set_pwm_config(pwm_autoscale=True)
        
        print("Performance configuration complete!")
    
    def configure_quiet(self):
        """Ultra-quiet configuration (StealthChop only)"""
        print("\n=== Configuring for Quiet Operation ===")
        
        self.enable()
        self.set_current(run_current=15, hold_current=5)
        self.set_microstepping(256)  # Finest resolution
        
        # StealthChop only
        self.set_stealthchop_enabled(True)
        self.set_stealthchop_threshold(0)  # Never switch to SpreadCycle
        
        # Configure PWM
        self.set_pwm_config(pwm_autoscale=True)
        
        print("Quiet configuration complete!")


# Example usage
if __name__ == "__main__":
    print("="*60)
    print("TMC2209 Full-Featured Example")
    print("="*60)

    time.sleep(5)
    
    # Initialize motor with correct baudrate
    motor = TMC2209(
        step_pin=2,
        dir_pin=3,
        en_pin=6,
        uart_id=0,
        tx_pin=0,
        rx_pin=1,
        baudrate=230400,  # Use 230400 like test_uart.py
        motor_id=0
    )
    
    # Test UART
    if motor.test_uart():
        # Configure for basic operation
        motor.configure_basic()
        
        # Test movement
        print("\nTesting basic movement...")
        motor.rotate_revolutions(1, speed=400)
        time.sleep(1)
        
        # Print status
        motor.print_status()
    else:
        print("\nUART not available - using STEP/DIR only")
        motor.enable()
        motor.rotate_revolutions(1, speed=400)