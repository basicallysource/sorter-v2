"""
TMC2209 Register Write/Read Test with Valid Values
"""

import time
from tmc2209 import TMC2209

motor = TMC2209(
    step_pin=2,
    dir_pin=3,
    en_pin=6,
    uart_id=0,
    tx_pin=0,
    rx_pin=1,
    baudrate=230400,
    motor_id=0
)

print("\n=== TMC2209 UART Checkout Test ===\n")
input(f"Press ENTER to begin the checkout test...")

# Test GCONF write/read
print("\n=== Testing GCONF Write/Read ===")

# Read current GCONF
gconf_before = motor.read_int(motor.GCONF)
print("GCONF before: 0x{:08X}".format(gconf_before if gconf_before else 0))

# Write a new value (enable internal voltage reference)
test_gconf = 0x00000001
print("Writing GCONF: 0x{:08X}".format(test_gconf))
motor.write_reg(motor.GCONF, test_gconf)
time.sleep_ms(200)

# Read it back
gconf_after = motor.read_int(motor.GCONF)
print("GCONF after: 0x{:08X}".format(gconf_after if gconf_after else 0))

if gconf_after == test_gconf:
    print("✓ GCONF write successful!")
else:
    print("⚠ GCONF write failed or value changed")

# Now try CHOPCONF
print("\n=== Testing CHOPCONF Write/Read ===")

chopconf_before = motor.read_int(motor.CHOPCONF)
print("CHOPCONF before: 0x{:08X}".format(chopconf_before if chopconf_before else 0))

# Write new CHOPCONF (microsteps = 16, TOFF=3)
test_chopconf = 0x10000053
print("Writing CHOPCONF: 0x{:08X}".format(test_chopconf))
motor.write_reg(motor.CHOPCONF, test_chopconf)
time.sleep_ms(200)

chopconf_after = motor.read_int(motor.CHOPCONF)
print("CHOPCONF after: 0x{:08X}".format(chopconf_after if chopconf_after else 0))

if chopconf_after == test_chopconf:
    print("✓ CHOPCONF write successful!")
else:
    print("⚠ CHOPCONF value: 0x{:08X}".format(chopconf_after if chopconf_after else 0))

# Test IHOLD_IRUN with correct bit positions
print("\n=== Testing IHOLD_IRUN (Corrected) ===")

# IHOLD_IRUN register format:
# Bits [4:0]   = IHOLD (0-31)
# Bits [11:8]  = IHOLDDELAY (0-15) 
# Bits [20:16] = IRUN (0-31)

ihold = 10
iholddelay = 1  
irun = 20

# Correct calculation
test_value = (irun << 16) | (iholddelay << 8) | ihold  # Fixed: IRUN at bit 16, not 8!
print("Writing IHOLD_IRUN: IRUN={}, IHOLDDELAY={}, IHOLD={}".format(irun, iholddelay, ihold))
print("  Register value: 0x{:08X}".format(test_value))

motor.write_reg(motor.IHOLD_IRUN, test_value)
time.sleep_ms(200)

read_value = motor.read_int(motor.IHOLD_IRUN)

if read_value is not None:
    read_ihold = read_value & 0x1F
    read_iholddelay = (read_value >> 8) & 0x0F
    read_irun = (read_value >> 16) & 0x1F
    
    print("Read back: 0x{:08X}".format(read_value))
    print("  IRUN={}, IHOLDDELAY={}, IHOLD={}".format(read_irun, read_iholddelay, read_ihold))
    
    if read_ihold == ihold and read_iholddelay == iholddelay and read_irun == irun:
        print("✓ IHOLD_IRUN write PASSED!")

print("\n=== Full Motor Initialization Test ===")

# Step 1: Configure GCONF for internal voltage reference
print("1. Configuring GCONF...")
motor.write_reg(motor.GCONF, 0x00000001)  # I_scale_analog = 1
time.sleep_ms(50)

# Step 2: Set TPOWERDOWN (delay before power down)
print("2. Setting TPOWERDOWN...")
motor.write_reg(motor.TPOWERDOWN, 10)  # ~2 seconds delay
time.sleep_ms(50)

# Step 3: Now set IHOLD_IRUN
print("3. Setting IHOLD_IRUN...")
ihold = 10
iholddelay = 1  
irun = 20
test_value = (irun << 16) | (iholddelay << 8) | ihold
print("  Writing: 0x{:08X}".format(test_value))
motor.write_reg(motor.IHOLD_IRUN, test_value)
time.sleep_ms(200)

# Step 4: Read back
read_value = motor.read_int(motor.IHOLD_IRUN)
print("4. Reading back IHOLD_IRUN...")
print("  Value: 0x{:08X}".format(read_value if read_value else 0))

if read_value and read_value != 0:
    read_ihold = read_value & 0x1F
    read_iholddelay = (read_value >> 8) & 0x0F
    read_irun = (read_value >> 16) & 0x1F
    print("  IRUN={}, IHOLDDELAY={}, IHOLD={}".format(read_irun, read_iholddelay, read_ihold))
    print("✓ IHOLD_IRUN configured!")
else:
    print("⚠ IHOLD_IRUN still reads zero")
    print("  This may be normal - register might only activate during motion")
    print("  Try moving the motor and reading again")