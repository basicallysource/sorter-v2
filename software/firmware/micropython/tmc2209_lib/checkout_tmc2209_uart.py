

print("\n=== TMC2209 UART Checkout Test ===\n")
input(f"Press ENTER to begin the checkout test...")
"""
TMC2209 Register Checkout Test
Tests write/read functionality for all writable registers
"""

import time
from tmc2209 import TMC2209

# Initialize TMC2209
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

print("\n" + "="*70)
print("TMC2209 REGISTER WRITE/READ CHECKOUT")
print("="*70)

# Test UART first
print("\n=== Testing UART Communication ===")
if not motor.test_uart():
    print("✗ UART communication failed!")
    exit(1)

print("✓ UART communication working!\n")

# Enable driver
motor.enable()
time.sleep_ms(100)

# Define test cases: (register_name, address, test_value, description)
test_cases = [
    ("GCONF", motor.GCONF, 0x00000001, "Global configuration"),
    ("GSTAT", motor.GSTAT, 0x00000007, "Global status (write 1 to clear)"),
    ("SLAVECONF", motor.SLAVECONF, 0x00000000, "Slave configuration"),
    ("IHOLD_IRUN", motor.IHOLD_IRUN, 0x00140A0A, "Motor currents"),
    ("TPOWERDOWN", motor.TPOWERDOWN, 0x0000000A, "Power down delay"),
    ("TPWMTHRS", motor.TPWMTHRS, 0x000001F4, "StealthChop threshold"),
    ("TCOOLTHRS", motor.TCOOLTHRS, 0x000001F4, "CoolStep threshold"),
    ("SGTHRS", motor.SGTHRS, 0x00000040, "StallGuard threshold"),
    ("COOLCONF", motor.COOLCONF, 0x00000000, "CoolStep configuration"),
    ("CHOPCONF", motor.CHOPCONF, 0x10000053, "Chopper configuration"),
    ("PWMCONF", motor.PWMCONF, 0xC10D0024, "PWM configuration"),
]

results = []

print("="*70)
print("Testing {} registers...".format(len(test_cases)))
print("="*70)

for reg_name, reg_addr, test_value, description in test_cases:
    print("\n--- {} (0x{:02X}): {} ---".format(reg_name, reg_addr, description))
    
    # Read original value
    original = motor.read_int(reg_addr)
    if original is not None:
        print("  Original value: 0x{:08X}".format(original))
    else:
        print("  ✗ Failed to read original value")
        results.append((reg_name, "READ_FAIL", None, None))
        continue
    
    # Write test value
    print("  Writing test value: 0x{:08X}".format(test_value))
    motor.write_reg(reg_addr, test_value)
    time.sleep_ms(100)
    
    # Read back
    readback = motor.read_int(reg_addr)
    if readback is not None:
        print("  Read back: 0x{:08X}".format(readback))
        
        if readback == test_value:
            print("  ✓ WRITE/READ SUCCESS")
            results.append((reg_name, "SUCCESS", test_value, readback))
        else:
            print("  ⚠ VALUE MISMATCH (may be normal for some registers)")
            results.append((reg_name, "MISMATCH", test_value, readback))
    else:
        print("  ✗ Failed to read back")
        results.append((reg_name, "READBACK_FAIL", test_value, None))
    
    # Restore original value
    if original is not None:
        print("  Restoring original value...")
        motor.write_reg(reg_addr, original)
        time.sleep_ms(50)

# Read-only registers test
print("\n" + "="*70)
print("TESTING READ-ONLY REGISTERS")
print("="*70)

readonly_regs = [
    ("IFCNT", motor.IFCNT, "Interface transmission counter"),
    ("IOIN", motor.IOIN, "Input pin states"),
    ("TSTEP", motor.TSTEP, "Actual measured time between steps"),
    ("SG_RESULT", motor.SG_RESULT, "StallGuard result"),
    ("MSCNT", motor.MSCNT, "Microstep counter"),
    ("MSCURACT", motor.MSCURACT, "Actual microstep current"),
    ("DRV_STATUS", motor.DRV_STATUS, "Driver status flags"),
    ("PWM_SCALE", motor.PWM_SCALE, "PWM scale sum"),
    ("PWM_AUTO", motor.PWM_AUTO, "PWM automatic scale"),
]

for reg_name, reg_addr, description in readonly_regs:
    print("\n--- {} (0x{:02X}): {} ---".format(reg_name, reg_addr, description))
    value = motor.read_int(reg_addr)
    if value is not None:
        print("  Value: 0x{:08X}".format(value))
        print("  ✓ READ SUCCESS (read-only)")
        results.append((reg_name, "READONLY", None, value))
    else:
        print("  ✗ READ FAILED")
        results.append((reg_name, "READ_FAIL", None, None))

# Summary
print("\n" + "="*70)
print("CHECKOUT SUMMARY")
print("="*70)

success_count = 0
mismatch_count = 0
fail_count = 0
readonly_count = 0

print("\nWritable Registers:")
for reg_name, status, test_val, read_val in results:
    if status == "READONLY":
        continue
    
    if status == "SUCCESS":
        print("  ✓ {}: PASS".format(reg_name))
        success_count += 1
    elif status == "MISMATCH":
        print("  ⚠ {}: MISMATCH (wrote 0x{:08X}, read 0x{:08X})".format(
            reg_name, test_val, read_val))
        mismatch_count += 1
    else:
        print("  ✗ {}: FAIL ({})".format(reg_name, status))
        fail_count += 1

print("\nRead-Only Registers:")
for reg_name, status, test_val, read_val in results:
    if status != "READONLY":
        continue
    
    print("  ✓ {}: OK (0x{:08X})".format(reg_name, read_val))
    readonly_count += 1

print("\n" + "="*70)
print("TOTALS:")
print("  Writable registers tested: {}".format(success_count + mismatch_count + fail_count))
print("    ✓ Perfect writes: {}".format(success_count))
print("    ⚠ Mismatches: {}".format(mismatch_count))
print("    ✗ Failures: {}".format(fail_count))
print("  Read-only registers: {}".format(readonly_count))
print("="*70)

if mismatch_count > 0:
    print("\nNOTE: Mismatches may be normal for registers with:")
    print("  - Read-only bits that hardware modifies")
    print("  - Reserved bits that are always 0")
    print("  - Bits that require specific conditions to change")

motor.disable()
print("\nCheckout complete!")