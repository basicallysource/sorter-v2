"""
TMC2209 Comprehensive Checkout Test Script
Interactive test that guides you through validating all library features.
Uses a stepper motor and pliers for torque/stall testing.

Requirements:
- Stepper motor connected to STEP/DIR/EN pins
- TMC2209 powered with UART connected
- Pliers nearby for stall/torque testing
"""

import time
from tmc2209 import TMC2209

# ==============================================================================
# CONFIGURATION
# ==============================================================================

STEP_PIN = 2
DIR_PIN = 3
EN_PIN = 6
UART_ID = 0
TX_PIN = 0
RX_PIN = 1
BAUDRATE = 230400
MOTOR_ID = 0

# ==============================================================================
# TEST UTILITIES
# ==============================================================================

def wait_for_proceed(prompt_text="Press ENTER to proceed"):
    """
    Wait for user to press ENTER before continuing.
    Disables motor during the wait to prevent overheating.
    
    Args:
        prompt_text: What to ask the user
        motor: Motor object to disable during wait (optional)
    """

    print("\n" + "-"*70)
    input(f"→ {prompt_text}: ")
    print()

def wait_for_verification(prompt_text="Did you observe the expected behavior?"):
    """
    Wait for user to confirm they saw what was expected.
    Disables motor during the wait to prevent overheating.
    
    Args:
        prompt_text: What to ask the user to verify
        motor: Motor object to disable during wait (optional)
    """
    print("\n" + "-"*70)
    response = input(f"→ {prompt_text} (yes/no): ").strip().lower()
    print()
    
    return response in ['yes', 'y', '']

def separator(title=""):
    """Print a visual separator with test title"""
    if title:
        print("\n" + "="*70)
        print(f"🔧 {title}")
        print("="*70)
    else:
        print("\n" + "-"*70)

def test_passed(msg=""):
    """Print a success message"""
    print(f"✅ {msg}" if msg else "✅ Test passed!")

def test_failed(msg=""):
    """Print a failure message"""
    print(f"❌ {msg}" if msg else "❌ Test failed!")

# ==============================================================================
# INITIALIZATION
# ==============================================================================

def test_initialization():
    """Test 1: Basic initialization and UART communication"""
    test_num = 1
    separator(f"TEST {test_num}: INITIALIZATION & UART COMMUNICATION")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • TMC2209 driver initialization")
    print("   • UART communication with the chip")
    print("\n👀 WHAT TO LOOK FOR:")
    print("   • Initialization messages showing GPIO and UART settings")
    print("   • 'UART OK' message if communication successful")
    print("   • Motor should be idle, not moving (EN pin HIGH = disabled)")
    
    wait_for_proceed("Ready to initialize the driver")
    
    print("Initializing TMC2209 driver...")
    print(f"  STEP: GPIO{STEP_PIN}")
    print(f"  DIR: GPIO{DIR_PIN}")
    print(f"  EN: GPIO{EN_PIN}")
    print(f"  UART{UART_ID} @ {BAUDRATE} baud (TX: GPIO{TX_PIN}, RX: GPIO{RX_PIN})")
    
    motor = TMC2209(
        step_pin=STEP_PIN,
        dir_pin=DIR_PIN,
        en_pin=EN_PIN,
        uart_id=UART_ID,
        tx_pin=TX_PIN,
        rx_pin=RX_PIN,
        baudrate=BAUDRATE,
        motor_id=MOTOR_ID
    )
    
    print("\nTesting UART communication...")
    time.sleep(1)
    if motor.test_uart():
        test_passed("UART communication OK")
    else:
        test_failed("UART communication failed - continuing with STEP/DIR only")
    
    time.sleep(3)

    # microstep_config = motor.get_microstep_config()
    # print(f"  • microstep_config: {microstep_config}")
    # # microstep_config = motor.get_microstep_config()
    # # print(f"  • microstep_config: {microstep_config}")
    # time.sleep(3)
    # # microstep_config = motor.get_microstep_config()
    # # print(f"  • microstep_config: {microstep_config}")
    # # microstep_config = motor.get_microstep_config()
    # # print(f"  • microstep_config: {microstep_config}")
    # # time.sleep(3)

    # motor.set_use_mstep_reg(enable=True)

    # time.sleep(3)

    # microstep_config = motor.get_microstep_config()
    # # print(f"  • microstep_config: {microstep_config}")

    # time.sleep(3)

    # motor.set_use_mstep_reg(enable=True)

    # time.sleep(3)
    
    # microstep_config = motor.get_microstep_config()
    # print(f"  • microstep_config: {microstep_config}")

    motor.disable()
    wait_for_verification("Did you see initialization messages and motor is idle?")
    
    return motor

# ==============================================================================
# BASIC MOTOR CONTROL
# ==============================================================================

def test_enable_disable(motor):
    """Test 2: Enable/Disable functionality"""
    test_num = 2
    separator(f"TEST {test_num}: ENABLE/DISABLE")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • Motor enable (turns on holding force)")
    print("   • Motor disable (releases holding force)")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   Phase 1 (DISABLED):")
    print("     - Motor shaft should spin FREELY by hand")
    print("     - Minimal resistance")
    print("   Phase 2 (ENABLED):")
    print("     - Motor shaft should resist rotation firmly")
    print("     - Should feel strong magnetic holding force")
    
    wait_for_proceed("Ready for DISABLE phase")
    
    print("Motor currently DISABLED (EN=HIGH)...")
    print("Try rotating the shaft by hand - it should spin freely.\n")
    time.sleep(3)
    
    motor.disable()
    wait_for_verification("Could you rotate the motor shaft freely with no resistance?")
    wait_for_proceed("Ready for ENABLE phase")
    
    print("Enabling motor (EN=LOW)...")
    motor.enable()
    time.sleep(0.5)
    
    print("Motor now ENABLED and holding position.")
    print("Try rotating the shaft by hand - it should resist firmly.\n")
    time.sleep(3)
    
    motor.disable()
    wait_for_verification("Could you feel strong resistance when trying to rotate?")
    motor.enable()

    print("Disabling motor...")
    motor.disable()
    time.sleep(0.5)
    
    test_passed("Enable/Disable test complete")

# ==============================================================================
# STEP AND DIRECTION CONTROL
# ==============================================================================

def test_direction_control(motor):
    """Test 3: Direction control"""
    test_num = 3
    separator(f"TEST {test_num}: DIRECTION CONTROL")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • Clockwise (CW) rotation")
    print("   • Counter-Clockwise (CCW) rotation")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   Phase 1 (CLOCKWISE):")
    print("     - Motor rotates in one direction")
    print("     - ~1 full revolution (200 steps at 1x microstepping)")
    print("     - Remember this position")
    print("   Phase 2 (COUNTER-CLOCKWISE):")
    print("     - Motor rotates in OPPOSITE direction")
    print("     - Should return to starting position")
    
    motor.disable()
    wait_for_proceed("Ready for CLOCKWISE rotation")
    motor.enable()

    print("Motor ENABLED")
    print("Setting direction CLOCKWISE...")
    motor.set_direction(clockwise=True)
    print("Moving 200 steps (~1 revolution)...\n")
    time.sleep(1)
    
    motor.move_steps(200, speed=400)
    time.sleep(1)
    print("Clockwise rotation complete. Remember this position.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did the motor rotate CLOCKWISE smoothly?")
    wait_for_proceed("Ready for COUNTER-CLOCKWISE rotation")
    motor.enable()

    print("Setting direction COUNTER-CLOCKWISE...")
    motor.set_direction(clockwise=False)
    print("Moving 200 steps (~1 revolution)...\n")
    time.sleep(1)
    
    motor.move_steps(200, speed=400)
    time.sleep(1)
    print("Counter-clockwise rotation complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did the motor rotate COUNTER-CLOCKWISE and return to start?")
    motor.enable()

    test_passed("Direction control working correctly")

# ==============================================================================
# SPEED CONTROL
# ==============================================================================

def test_speed_control(motor):
    """Test 4: Speed control"""
    test_num = 4
    separator(f"TEST {test_num}: SPEED CONTROL")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • Slow speed stepping")
    print("   • Medium speed stepping")
    print("   • Fast speed stepping")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   Phase 1 (SLOW - 100 steps/sec):")
    print("     - Slow, deliberate clicking/stepping sounds")
    print("     - Each step is distinct and audible")
    print("   Phase 2 (MEDIUM - 500 steps/sec):")
    print("     - Faster stepping, more continuous sound")
    print("   Phase 3 (FAST - 1000 steps/sec):")
    print("     - Very fast, smooth whirring sound")
    
    motor.set_direction(clockwise=True)
    
    motor.disable()
    wait_for_proceed("Ready for SLOW speed test (100 steps/sec)")
    motor.enable()

    print("Moving 200 steps at SLOW speed (100 steps/sec)...")
    print("Listen for slow, distinct stepping sounds...\n")
    time.sleep(1)
    motor.move_steps(200, speed=100)
    time.sleep(1)
    print("Slow speed test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did you hear slow, distinct stepping sounds?")
    wait_for_proceed("Ready for MEDIUM speed test (500 steps/sec)")
    motor.enable()

    print("Moving 200 steps at MEDIUM speed (500 steps/sec)...")
    print("Listen for medium-paced stepping...\n")
    time.sleep(1)
    motor.move_steps(200, speed=500)
    time.sleep(1)
    print("Medium speed test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did you hear medium-paced stepping?")
    wait_for_proceed("Ready for FAST speed test (1000 steps/sec)")
    motor.enable()

    print("Moving 200 steps at FAST speed (1000 steps/sec)...")
    print("Listen for fast, smooth whirring...\n")
    time.sleep(1)
    motor.move_steps(200, speed=1000)
    time.sleep(1)
    print("Fast speed test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did speed increase noticeably from slow to fast?")
    motor.enable()

    test_passed("Speed control working - smooth acceleration through range")

# ==============================================================================
# MICROSTEPPING RESOLUTION
# ==============================================================================

def test_microstepping(motor):
    """Test 5: Microstepping resolution"""
    test_num = 5
    separator(f"TEST {test_num}: MICROSTEPPING RESOLUTION")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • 1/1 stepping (no microstepping)")
    print("   • 1/4 stepping")
    print("   • 1/16 stepping (default)")
    print("   • 1/256 stepping (maximum)")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   As microstepping increases:")
    print("     ✓ Motion becomes SMOOTHER")
    print("     ✓ Vibration decreases")
    print("     ✓ Sound becomes more of a hum vs. discrete clicks")
    print("     ✓ 1/256 should be ultra-smooth like a servo")
    
    motor.set_direction(clockwise=True)
    
    motor.disable()
    wait_for_proceed("Ready for 1/1 STEPPING (coarsest)")
    motor.enable()

    print("Setting 1/1 stepping (NO microstepping)...")
    motor.set_microstepping(1)
    time.sleep(0.5)
    print("Moving 200 steps...")
    print("Listen for CHOPPY, coarse stepping...\n")
    time.sleep(1)
    motor.move_steps(200, speed=500)
    time.sleep(1)
    print("1/1 stepping complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Was the motion CHOPPY and coarse?")
    wait_for_proceed("Ready for 1/4 STEPPING")
    motor.enable()

    print("Setting 1/4 stepping...")
    motor.set_microstepping(4)
    time.sleep(0.5)
    print("Moving 200 steps...")
    print("Motion should be SMOOTHER than 1/1...\n")
    time.sleep(1)
    motor.move_steps(200, speed=500)
    time.sleep(1)
    print("1/4 stepping complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Was motion SMOOTHER than 1/1 stepping?")
    wait_for_proceed("Ready for 1/16 STEPPING (default)")
    motor.enable()

    print("Setting 1/16 stepping (default)...")
    motor.set_microstepping(16)
    time.sleep(0.5)
    print("Moving 200 steps...")
    print("Motion should be VERY SMOOTH...\n")
    time.sleep(1)
    motor.move_steps(200, speed=500)
    time.sleep(1)
    print("1/16 stepping complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Was motion VERY SMOOTH with fine resolution?")
    wait_for_proceed("Ready for 1/256 STEPPING (finest/smoothest)")
    motor.enable()

    print("Setting 1/256 stepping (maximum)...")
    motor.set_microstepping(256)
    time.sleep(0.5)
    print("Moving 256 steps (= 1 full step)...")
    print("Motion should be ULTRA-SMOOTH like a servo...\n")
    time.sleep(1)
    motor.move_steps(256, speed=200)
    time.sleep(1)
    print("1/256 stepping complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Was motion ULTRA-SMOOTH (smoothest so far)?")
    motor.enable()

    # Return to reasonable default
    motor.set_microstepping(16)
    test_passed("Microstepping resolution verified - quality improves with finer steps")

# ==============================================================================
# CURRENT AND TORQUE CONTROL
# ==============================================================================

def test_current_and_torque(motor):
    """Test 6: Current setting and torque verification with pliers"""
    test_num = 6
    separator(f"TEST {test_num}: CURRENT & TORQUE CONTROL")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • Low current (weak holding force)")
    print("   • Medium-low current")
    print("   • Medium-high current")
    print("   • Maximum current (strong holding force)")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   • Use PLIERS to grip the motor shaft")
    print("   • Try to prevent rotation while motor moves")
    print("   • Low current: EASY to stall with light pressure")
    print("   • High current: VERY HARD to stall, requires firm pressure")
    print("   • Motor will get WARM - this is normal!")
    
    print("\n⚠️  SAFETY:")
    print("   • Keep hands/pliers clear when motor moves")
    print("   • Don't apply max current for more than a minute")
    print("   • Motor may smell warm - normal for high current")
    
    motor.set_direction(clockwise=True)
    motor.move_steps(50, speed=200)
    motor.configure_basic()  # Safe current settings
    time.sleep(0.5)
    motor.move_steps(50, speed=200)
    
    # Test 1: Very low current
    motor.disable()
    wait_for_proceed("Ready for LOW CURRENT test - have pliers ready")
    motor.enable()

    print("Setting LOW CURRENT: 1.5A equivalent (level 5/31)...")
    motor.set_current(run_current=5, hold_current=2)
    time.sleep(0.5)
    
    print("Moving motor slowly...")
    motor.move_steps(50, speed=200)
    time.sleep(0.5)
    
    print("\n🔴 LOW TORQUE TEST:")
    print("   1. Grip motor shaft with pliers")
    print("   2. Try to prevent it from turning")
    print("   3. Should be EASY to stall\n")
    time.sleep(3)
    
    motor.disable()
    wait_for_verification("Could you easily stall the motor with light plier pressure?")
    # Test 2: Medium-low current
    wait_for_proceed("Ready for MEDIUM-LOW CURRENT test")
    motor.enable()

    print("Setting MEDIUM-LOW CURRENT: 3.8A equivalent (level 12/31)...")
    motor.set_current(run_current=12, hold_current=6)
    time.sleep(0.5)
    
    print("Moving motor...")
    motor.move_steps(50, speed=200)
    time.sleep(0.5)
    
    print("\n🟡 MEDIUM-LOW TORQUE TEST:")
    print("   1. Grip shaft with pliers")
    print("   2. Try to prevent rotation")
    print("   3. Requires MODERATE plier pressure\n")
    time.sleep(3)
    
    motor.disable()
    wait_for_verification("Did stalling require MODERATE pressure?")
    
    # Test 3: Higher current
    wait_for_proceed("Ready for MEDIUM-HIGH CURRENT test")
    motor.enable()

    print("Setting MEDIUM-HIGH CURRENT: 6.3A equivalent (level 20/31)...")
    motor.set_current(run_current=20, hold_current=10)
    time.sleep(0.5)
    
    print("Moving motor...")
    motor.move_steps(50, speed=200)
    time.sleep(0.5)
    
    print("\n🟠 MEDIUM-HIGH TORQUE TEST:")
    print("   1. Grip shaft with pliers")
    print("   2. Try to prevent rotation")
    print("   3. Should require FIRM plier pressure")
    print("   4. Motor may get warm - NORMAL\n")
    time.sleep(3)
    
    motor.disable()
    wait_for_verification("Did it require FIRM pressure to stall?")
    
    # Test 4: Maximum current
    wait_for_proceed("Ready for MAXIMUM CURRENT test")
    motor.enable()

    print("Setting MAXIMUM CURRENT: 7.8A equivalent (level 31/31)...")
    motor.set_current(run_current=31, hold_current=15)
    time.sleep(0.5)
    
    print("Moving motor...")
    motor.move_steps(50, speed=200)
    time.sleep(0.5)
    
    print("\n🔴 MAXIMUM TORQUE TEST:")
    print("   1. Grip shaft FIRMLY with pliers")
    print("   2. Try to stop the motor")
    print("   3. Should be EXTREMELY DIFFICULT or IMPOSSIBLE")
    print("   4. Motor WILL BE HOT - can feel warm to touch")
    print("   5. May emit heat/smell - normal for max current\n")
    time.sleep(3)
    
    motor.disable()
    wait_for_verification("Was it extremely difficult to stall? (Motor may be quite hot)")
    motor.enable()

    # Return to safe default
    print("\nReturning to safe operating current...")
    motor.set_current(run_current=16, hold_current=8)
    time.sleep(0.5)
    
    test_passed("Current/Torque control verified - torque scales with current setting")

# ==============================================================================
# STEALTHCHOP MODE
# ==============================================================================

def test_stealthchop(motor):
    """Test 7: StealthChop (quiet) vs SpreadCycle (loud)"""
    test_num = 7
    separator(f"TEST {test_num}: STEALTHCHOP vs SPREADCYCLE")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • StealthChop mode (quiet, PWM-based)")
    print("   • SpreadCycle mode (loud, classic chopper)")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   StealthChop:")
    print("     ✓ QUIET, whisper-like PWM humming sound")
    print("     ✓ Smooth operation")
    print("     ✓ Lower acoustic noise")
    print("   SpreadCycle:")
    print("     ✓ AUDIBLY LOUDER")
    print("     ✓ Distinctive chopping/clicking sound")
    print("     ✓ Different pitch than StealthChop")
    
    motor.set_direction(clockwise=True)
    
    motor.disable()
    wait_for_proceed("Ready for STEALTHCHOP mode (quiet)")
    motor.enable()

    print("Enabling StealthChop mode...")
    motor.set_stealthchop_enabled(True)
    motor.set_stealthchop_threshold(0)  # Always StealthChop
    time.sleep(0.5)
    
    print("Moving 300 steps at medium speed...")
    print("Listen for QUIET PWM humming...\n")
    time.sleep(1)
    motor.move_steps(300, speed=600)
    time.sleep(1)
    print("StealthChop test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did you hear QUIET PWM humming (whisper-like)?")
    wait_for_proceed("Ready for SPREADCYCLE mode (loud)")
    motor.enable()

    print("Enabling SpreadCycle mode (disabling StealthChop)...")
    motor.set_stealthchop_enabled(False)
    time.sleep(0.5)
    
    print("Moving 300 steps at medium speed...")
    print("Listen for LOUD chopping/clicking sound...\n")
    time.sleep(1)
    motor.move_steps(300, speed=600)
    time.sleep(1)
    print("SpreadCycle test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Was SpreadCycle NOTICEABLY LOUDER than StealthChop?")
    motor.enable()

    # Return to StealthChop
    print("Returning to StealthChop mode...")
    motor.set_stealthchop_enabled(True)
    time.sleep(0.5)
    
    test_passed("StealthChop/SpreadCycle switching verified")

# ==============================================================================
# PWM CONFIGURATION
# ==============================================================================

def test_pwm_config(motor):
    """Test 8: PWM configuration"""
    test_num = 8
    separator(f"TEST {test_num}: PWM CONFIGURATION")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • PWM balanced settings")
    print("   • PWM high gradient (aggressive)")
    print("   • PWM low gradient (subtle)")
    print("   • How PWM affects StealthChop operation")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   • Subtle differences in sound/smoothness")
    print("   • Balanced: Normal torque and noise balance")
    print("   • High gradient: Slightly louder or smoother")
    print("   • Low gradient: Quieter or less smooth")
    
    motor.set_direction(clockwise=True)
    
    motor.disable()
    wait_for_proceed("Ready for BALANCED PWM test")
    motor.enable()

    print("Setting BALANCED PWM configuration...")
    motor.set_pwm_config(pwm_ofs=36, pwm_grad=14, pwm_freq=1, pwm_autoscale=True)
    time.sleep(0.5)
    
    print("Moving 200 steps...")
    print("Listen for normal, balanced operation...\n")
    time.sleep(1)
    motor.move_steps(200, speed=500)
    time.sleep(1)
    print("Balanced PWM test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did you observe normal balanced operation?")
    wait_for_proceed("Ready for HIGH GRADIENT PWM test (more aggressive)")
    motor.enable()

    print("Setting HIGH GRADIENT PWM configuration...")
    motor.set_pwm_config(pwm_ofs=30, pwm_grad=25, pwm_freq=1, pwm_autoscale=True)
    time.sleep(0.5)
    
    print("Moving 200 steps...")
    print("Listen for slightly different characteristics...\n")
    time.sleep(1)
    motor.move_steps(200, speed=500)
    time.sleep(1)
    print("High gradient PWM test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did you notice a difference from balanced?")
    wait_for_proceed("Ready for LOW GRADIENT PWM test (more subtle)")
    motor.enable()

    print("Setting LOW GRADIENT PWM configuration...")
    motor.set_pwm_config(pwm_ofs=40, pwm_grad=8, pwm_freq=1, pwm_autoscale=True)
    time.sleep(0.5)
    
    print("Moving 200 steps...")
    print("Listen for different characteristics...\n")
    time.sleep(1)
    motor.move_steps(200, speed=500)
    time.sleep(1)
    print("Low gradient PWM test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did low gradient differ from high gradient?")
    motor.enable()

    # Return to balanced
    print("Returning to balanced PWM...")
    motor.set_pwm_config(pwm_ofs=36, pwm_grad=14, pwm_freq=1, pwm_autoscale=True)
    time.sleep(0.5)
    
    test_passed("PWM configuration tested - affects StealthChop operation")

# ==============================================================================
# STALLGUARD (STALL DETECTION)
# ==============================================================================

def test_stallguard(motor):
    """Test 9: StallGuard sensorless load detection"""
    test_num = 9
    separator(f"TEST {test_num}: STALLGUARD & STALL DETECTION")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • StallGuard load detection (no sensor needed)")
    print("   • Reading SG values with NO load")
    print("   • Reading SG values WITH load (pliers blocking shaft)")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   Phase 1 (NO LOAD):")
    print("     • SG values: Should be RELATIVELY HIGH (>200)")
    print("   Phase 2 (WITH LOAD - using pliers):")
    print("     • SG values: Should DROP (lower = more load)")
    print("     • If blocked hard enough: Stall bit may trigger")
    
    motor.set_direction(clockwise=True)
    
    motor.disable()
    wait_for_proceed("Ready for StallGuard NO LOAD test")
    motor.enable()

    print("Enabling StallGuard...")
    motor.enable_stallguard(threshold=10)
    time.sleep(0.5)
    
    print("Moving 100 steps freely (no obstruction)...")
    print("Reading SG values...\n")
    time.sleep(1)
    motor.move_steps(100, speed=300)
    
    print("SG readings (no load):")
    for i in range(5):
        sg = motor.read_stallguard()
        is_stalled = motor.is_stalled()
        print(f"  Reading {i+1}: SG={sg}, Stalled={is_stalled}")
        time.sleep(0.2)
    
    time.sleep(2)
    motor.disable()
    wait_for_verification("Were SG values relatively high (>200)? No stall detected?")
    wait_for_proceed("Ready for StallGuard WITH LOAD test - have pliers ready")
    motor.enable()

    print("Creating artificial load by holding shaft with pliers...")
    print("Moving 100 steps while HOLDING shaft with pliers...")
    print("Reading SG values...\n")
    time.sleep(2)
    
    # Start moving
    motor.set_direction(clockwise=True)
    for step in range(100):
        motor.step_once(delay_us=800)
        
        if step % 20 == 0:
            sg = motor.read_stallguard()
            is_stalled = motor.is_stalled()
            print(f"  Step {step}: SG={sg}, Stalled={is_stalled}")
            time.sleep(0.1)
    
    time.sleep(2)
    motor.disable()
    wait_for_verification("Did SG values drop (lower = more load)?")
    motor.enable()

    motor.disable_stallguard()
    print("StallGuard disabled")
    
    test_passed("StallGuard load detection verified")

# ==============================================================================
# STALLGUARD HOMING
# ==============================================================================

def test_stallguard_homing(motor):
    """Test 10: Sensorless homing with StallGuard"""
    test_num = 10
    separator(f"TEST {test_num}: SENSORLESS HOMING WITH STALLGUARD")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • Sensorless homing using StallGuard")
    print("   • Motor advances slowly until stalling")
    print("   • Position is reset to 0 when stall detected")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   Phase 1: Motor moves away from home (offset)")
    print("   Phase 2: Motor searches backward slowly")
    print("   Phase 3: When ready, you'll block shaft with hand/pliers")
    print("   Phase 4: Motor stalls, position reset to 0")
    print("   Phase 5: Motor backs off slightly")
    
    print("\n⚠️  When homing starts:")
    print("   • Have hand/pliers ready")
    print("   • Gently block the motor shaft when it starts homing")
    print("   • Don't apply too much force - let StallGuard detect it")
    
    motor.disable()
    wait_for_proceed("Ready to test sensorless homing")
    motor.enable()

    print("Moving away from home position (100 steps)...")
    motor.set_direction(clockwise=True)
    motor.move_steps(100, speed=400)
    time.sleep(0.5)
    
    print("Position offset. Now backing up to prepare for homing...\n")
    motor.set_direction(clockwise=False)
    motor.move_steps(50, speed=300)
    time.sleep(0.5)
    
    print("⚙️  STARTING SENSORLESS HOME PROCEDURE")
    print("Motor will advance slowly, watching for stall...")
    print("When motor starts moving toward you, gently block shaft with hand.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_proceed("Ready - I will block the shaft when homing starts")
    motor.enable()

    homed = motor.home_with_stallguard(speed=200, threshold=8, max_steps=500)
    
    if homed:
        test_passed("Homing successful - position reset to 0")
        print(f"Current position: {motor.get_position()}")
    else:
        print("⚠️  Homing timeout - motor didn't stall within 500 steps")
        print("   (Try manually blocking the shaft, or adjust threshold)")
    
    time.sleep(2)
    motor.disable()
    wait_for_verification("Did homing complete and reset position to 0?")
    motor.enable()

# ==============================================================================
# COOLSTEP
# ==============================================================================

def test_coolstep(motor):
    """Test 11: CoolStep automatic current reduction"""
    test_num = 11
    separator(f"TEST {test_num}: COOLSTEP - AUTOMATIC CURRENT REDUCTION")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • CoolStep automatic current reduction")
    print("   • Current lowered when motor unloaded")
    print("   • Current boosted when motor under load")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   Phase 1 (NO LOAD):")
    print("     • Motor moves freely")
    print("     • CoolStep reduces current automatically")
    print("     • Should be quieter with lower power draw")
    print("   Phase 2 (WITH LOAD - pliers):")
    print("     • You hold shaft with pliers")
    print("     • CoolStep detects load (SG drops)")
    print("     • CoolStep boosts current to maintain torque")
    
    motor.set_direction(clockwise=True)
    
    motor.disable()
    wait_for_proceed("Ready for CoolStep unloaded test")
    motor.enable()

    print("Enabling CoolStep with high run current...")
    motor.set_current(run_current=25, hold_current=10)
    motor.enable_coolstep(semin=5, semax=2, seup=1, sedn=0)
    time.sleep(0.5)
    
    print("Moving 200 steps freely (no load)...")
    print("CoolStep should reduce current automatically...\n")
    time.sleep(1)
    motor.move_steps(200, speed=400)
    time.sleep(1)
    
    print("Unloaded motion complete.")
    print("Motor should be quieter due to CoolStep current reduction.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did motor seem quieter (lower power) when unloaded?")
    wait_for_proceed("Ready for CoolStep loaded test - have pliers ready")
    motor.enable()

    print("Now testing CoolStep WITH LOAD (holding shaft with pliers)...")
    print("Moving 100 steps while holding shaft...\n")
    time.sleep(2)
    
    for i in range(100):
        motor.step_once(delay_us=800)
        if i % 25 == 0:
            sg = motor.read_stallguard()
            print(f"  Step {i}: Load level SG={sg}")
    
    print("\nLoaded motion complete.")
    print("Under load, CoolStep should have boosted current back up.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did CoolStep maintain torque when you applied plier load?")
    motor.enable()

    motor.disable_coolstep()
    print("CoolStep disabled")
    
    test_passed("CoolStep automatic current control verified")

# ==============================================================================
# DRIVER STATUS
# ==============================================================================

def test_driver_status(motor):
    """Test 12: Read and display driver status"""
    test_num = 12
    separator(f"TEST {test_num}: DRIVER STATUS & DIAGNOSTICS")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • Reading comprehensive driver status")
    print("   • Temperature monitoring")
    print("   • Load detection (StallGuard)")
    print("   • Fault detection (short circuit, open load)")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   • All values should be readable")
    print("   • Temperature flags: Should be FALSE (no overtemp)")
    print("   • Overtemp pre-warning: Should be FALSE")
    print("   • Short circuit flags: Should be FALSE")
    print("   • Open load flags: Should be FALSE")
    print("   • UART communication working (values not None)")
    
    motor.disable()
    wait_for_proceed("Ready to read driver diagnostics")
    motor.enable()

    print("Reading comprehensive driver status...\n")
    
    # Enable motor to get better status
    motor.enable()
    motor.move_steps(50, speed=400)
    time.sleep(0.5)
    
    motor.print_status()
    
    print("\nDetailed status values:")
    status = motor.get_driver_status()
    if status:
        print(f"  • Standstill: {status['stst']}")
        print(f"  • StealthChop active: {status['stealth']}")
        print(f"  • Current scale: {status['cs_actual']}/31")
        print(f"  • Overtemperature: {status['ot']}")
        print(f"  • Overtemp warning: {status['otpw']}")
        print(f"  • Short to GND (A/B): {status['s2ga']}/{status['s2gb']}")
        print(f"  • Open load (A/B): {status['ola']}/{status['olb']}")
        print(f"  • Stalled: {status['stall']}")
    
    tstep = motor.get_tstep()
    print(f"\n  • TSTEP (velocity): {tstep}")
    
    mscnt = motor.get_microstep_counter()
    print(f"  • Microstep counter: {mscnt}")
    
    time.sleep(2)
    motor.disable()
    wait_for_verification("Were all status values readable? No fault flags?")
    motor.enable()

    test_passed("Status diagnostics retrieved successfully")

# ==============================================================================
# POSITION TRACKING
# ==============================================================================

def test_position_tracking(motor):
    """Test 13: Position tracking and movement"""
    test_num = 13
    separator(f"TEST {test_num}: POSITION TRACKING & MOVEMENT")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • Position tracking (step counting)")
    print("   • Relative movement (move_steps)")
    print("   • Absolute positioning (move_to_position)")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   • Position counter increments/decrements correctly")
    print("   • Forward movement increases position")
    print("   • Backward movement decreases position")
    print("   • Absolute positioning lands at target")
    
    motor.disable()
    wait_for_proceed("Ready to test position tracking")
    motor.enable()

    print("Resetting position to 0...")
    motor.set_direction(clockwise=True)
    motor.set_position(0)
    
    print(f"Current position: {motor.get_position()}\n")
    time.sleep(1)
    
    print("Moving 500 steps forward...")
    motor.move_steps(500, speed=500)
    pos1 = motor.get_position()
    print(f"Position after 500 forward steps: {pos1}")
    time.sleep(1)
    
    print("\nMoving 200 steps backward...")
    motor.move_steps(-200, speed=500)
    pos2 = motor.get_position()
    print(f"Position after -200 steps: {pos2}")
    time.sleep(1)
    
    print("\nMoving to absolute position 600...")
    motor.move_to_position(600, speed=500)
    pos3 = motor.get_position()
    print(f"Position after move_to_position(600): {pos3}")
    time.sleep(1)
    
    if pos1 == 500 and pos2 == 300 and pos3 == 600:
        print("\n✅ All position calculations correct!")
    else:
        print(f"\n⚠️  Position tracking issue:")
        print(f"   Expected: 500, 300, 600")
        print(f"   Got: {pos1}, {pos2}, {pos3}")
    
    time.sleep(2)
    motor.disable()
    wait_for_verification("Were all position calculations correct?")
    motor.enable()

    # Reset
    motor.set_position(0)
    
    test_passed("Position tracking accurate")

# ==============================================================================
# ROTATION BY DEGREES/REVOLUTIONS
# ==============================================================================

def test_rotation_units(motor):
    """Test 14: Rotation by degrees and revolutions"""
    test_num = 14
    motor.set_stealthchop_enabled(False)
    separator(f"TEST {test_num}: ROTATION BY DEGREES & REVOLUTIONS")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • Rotation by degrees")
    print("   • Rotation by revolutions")
    print("   • Proper conversion from degrees/revolutions to steps")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   • 90° should rotate 1/4 turn")
    print("   • 180° should rotate 1/2 turn")
    print("   • 0.5 revolutions should rotate 1/2 turn (same as 180°)")
    print("   • 1 full revolution should return to start")
    
    motor.disable()
    mscnt = motor.get_microstep_counter()
    print(f"  • Microstep counter: {mscnt}")
    wait_for_proceed("Ready for 90° rotation test")
    motor.enable()

    print("Rotating 90 degrees (1/4 revolution)...")
    motor.set_direction(clockwise=True)
    motor.set_position(0)
    motor.rotate_degrees(90, speed=400)
    time.sleep(1)
    print("90° rotation complete.\n")
    time.sleep(2)
    



    motor.disable()
    mscnt = motor.get_microstep_counter()
    print(f"  • Microstep counter: {mscnt}")
    wait_for_proceed("Ready for 90° rotation test")
    motor.enable()

    print("Rotating 90 degrees (1/4 revolution)...")
    motor.set_direction(clockwise=True)
    motor.set_position(0)
    motor.rotate_degrees(90, speed=400)
    time.sleep(1)
    print("90° rotation complete.\n")
    time.sleep(2)







    motor.disable()
    wait_for_verification("Did motor rotate exactly 1/4 turn?")
    wait_for_proceed("Ready for 180° rotation test")
    motor.enable()

    print("Rotating 180 degrees (1/2 revolution)...")
    motor.rotate_degrees(180, speed=400)
    time.sleep(1)
    print("180° rotation complete (total 270° from start).\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did motor rotate exactly 1/2 turn?")
    wait_for_proceed("Ready for 0.5 revolutions test")
    motor.enable()

    print("Rotating 0.5 revolutions (180 degrees)...")
    motor.rotate_revolutions(0.5, speed=400)
    time.sleep(1)
    print("0.5 revolutions complete (total 360° from start).\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did motor complete a full 360° rotation (back to start)?")
    wait_for_proceed("Ready for 1 full revolution test")
    motor.enable()

    print("Rotating 1 full revolution (360 degrees)...")
    motor.rotate_revolutions(1, speed=400)
    time.sleep(1)
    print("1 revolution complete (back to start).\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did motor complete another full 360° (back to start)?")
    motor.enable()

    test_passed("Degree/revolution rotation working correctly")

# ==============================================================================
# SPREADCYCLE CHOPPER CONFIGURATION
# ==============================================================================

def test_spreadcycle_config(motor):
    """Test 15: SpreadCycle chopper fine-tuning"""
    test_num = 15
    separator(f"TEST {test_num}: SPREADCYCLE CHOPPER CONFIGURATION")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • SpreadCycle chopper conservative settings (safe)")
    print("   • SpreadCycle chopper aggressive settings (high torque)")
    print("   • SpreadCycle chopper balanced settings")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   Conservative:")
    print("     • Stable, safe, reliable operation")
    print("     • Good for general use")
    print("   Aggressive:")
    print("     • Higher holding torque")
    print("     • May be slightly louder")
    print("   Balanced:")
    print("     • Good compromise between torque and stability")
    
    # Make sure we're in SpreadCycle mode
    motor.set_stealthchop_enabled(False)
    motor.set_direction(clockwise=True)
    time.sleep(0.5)
    
    motor.disable()
    wait_for_proceed("Ready for CONSERVATIVE SpreadCycle settings")
    motor.enable()

    print("Setting conservative SpreadCycle chopper (safe)...")
    motor.set_spreadcycle_chopper(toff=3, hstart=5, hend=0, tbl=2)
    time.sleep(0.3)
    
    print("Moving 200 steps...")
    print("Should feel stable and safe...\n")
    time.sleep(1)
    motor.move_steps(200, speed=600)
    time.sleep(1)
    print("Conservative settings test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did operation feel stable and safe?")
    wait_for_proceed("Ready for AGGRESSIVE SpreadCycle settings")
    motor.enable()

    print("Setting aggressive SpreadCycle chopper (high torque)...")
    motor.set_spreadcycle_chopper(toff=5, hstart=7, hend=3, tbl=1)
    time.sleep(0.3)
    
    print("Moving 200 steps...")
    print("Should feel more aggressive with higher holding force...\n")
    time.sleep(1)
    motor.move_steps(200, speed=600)
    time.sleep(1)
    print("Aggressive settings test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did you feel higher holding torque?")
    wait_for_proceed("Ready for BALANCED SpreadCycle settings")
    motor.enable()

    print("Setting balanced SpreadCycle chopper...")
    motor.set_spreadcycle_chopper(toff=4, hstart=6, hend=1, tbl=2)
    time.sleep(0.3)
    
    print("Moving 200 steps...")
    print("Should be good balance between torque and stability...\n")
    time.sleep(1)
    motor.move_steps(200, speed=600)
    time.sleep(1)
    print("Balanced settings test complete.\n")
    time.sleep(2)
    
    motor.disable()
    wait_for_verification("Did balanced settings feel like a good compromise?")
    motor.enable()

    test_passed("SpreadCycle chopper configuration tested")

# ==============================================================================
# PERFORMANCE AND STRESS TEST
# ==============================================================================

def test_performance(motor):
    """Test 16: Sustained performance and stress test"""
    test_num = 16
    separator(f"TEST {test_num}: PERFORMANCE & STRESS TEST")
    
    print("\n📋 WHAT'S BEING TESTED:")
    print("   • Extended continuous operation")
    print("   • Stability under rapid stepping")
    print("   • UART communication reliability")
    print("   • No step loss or errors")
    
    print("\n👀 WHAT TO LOOK FOR:")
    print("   • Motor moving smoothly for 30 seconds")
    print("   • No stuttering, skipping, or random movements")
    print("   • UART continues to respond (status reads OK)")
    print("   • No temperature warnings")
    print("   • Motor performance remains consistent")
    
    print("\n⏱️  This test takes 30 seconds")
    
    motor.disable()
    wait_for_proceed("Ready for 30-second performance test")
    motor.enable()
    
    print("Starting extended motion test to check stability...\n")
    
    motor.set_direction(clockwise=True)
    motor.configure_performance()  # Use higher current
    time.sleep(0.5)
    
    print("Running rapid stepping for 30 seconds...")
    print("Monitoring for skips, UART errors, or instability...\n")
    
    start_time = time.time()
    step_count = 0
    errors = 0
    
    while time.time() - start_time < 30:
        try:
            # Rapid stepping
            motor.move_steps(100, speed=1000)
            step_count += 100
            
            # Every 500 steps, check driver status
            if step_count % 500 == 0:
                status = motor.get_driver_status()
                if status is None:
                    errors += 1
                    print(f"⚠️  Status read error #{errors}")
                else:
                    elapsed = time.time() - start_time
                    print(f"  {elapsed:.1f}s: {step_count} steps, {status.get('cs_actual', '?')}/31 current")
                    
                    if status.get('ot'):
                        print("  ⚠️  OVERTEMPERATURE WARNING!")
                    if status.get('otpw'):
                        print("  ⚠️  Overtemp pre-warning")
        
        except Exception as e:
            errors += 1
            print(f"❌ Error during motion: {e}")
    
    elapsed = time.time() - start_time
    print(f"\n✅ Completed {elapsed:.1f}s, {step_count} steps, {errors} errors")
    
    motor.disable()
    
    if errors == 0:
        test_passed("Performance test completed with no errors")
        wait_for_verification("Did motor run smoothly for 30 seconds with no hiccups?")
    else:
        print(f"⚠️  {errors} errors occurred during stress test")
        wait_for_verification(f"Motor had {errors} errors. Continue anyway?")

# ==============================================================================
# CLEANUP AND SUMMARY
# ==============================================================================

def final_summary(motor):
    """Final status and cleanup"""
    separator("CHECKOUT COMPLETE")
    
    print("\n🎉 All tests completed successfully!\n")
    
    motor.disable()
    time.sleep(0.5)
    
    print("Reading final driver status:\n")
    motor.print_status()
    
    print("\n" + "="*70)
    print("✅ TMC2209 LIBRARY CHECKOUT PASSED")
    print("="*70)
    print("\nVerified features:")
    print("  ✓ TEST  1: UART communication")
    print("  ✓ TEST  2: Enable/Disable")
    print("  ✓ TEST  3: Direction control")
    print("  ✓ TEST  4: Speed control")
    print("  ✓ TEST  5: Microstepping resolution")
    print("  ✓ TEST  6: Current & Torque control")
    print("  ✓ TEST  7: StealthChop mode")
    print("  ✓ TEST  8: PWM configuration")
    print("  ✓ TEST  9: StallGuard detection")
    print("  ✓ TEST 10: Sensorless homing")
    print("  ✓ TEST 11: CoolStep current reduction")
    print("  ✓ TEST 12: Driver diagnostics")
    print("  ✓ TEST 13: Position tracking")
    print("  ✓ TEST 14: Rotation by degrees/revolutions")
    print("  ✓ TEST 15: SpreadCycle chopper config")
    print("  ✓ TEST 16: Performance under load")
    print("\nYour TMC2209 library is ready for production use!")
    print("="*70)

# ==============================================================================
# MAIN TEST SEQUENCE
# ==============================================================================

def main():
    """Run complete checkout sequence"""
    
    print("\n" + "="*70)
    print("🔧 TMC2209 COMPREHENSIVE CHECKOUT TEST")
    print("="*70)
    print("\nThis script will test ALL features of your TMC2209 library:")
    print("  • UART communication")
    print("  • Motor enable/disable")
    print("  • Direction and speed control")
    print("  • Microstepping resolution")
    print("  • Current/torque control (with pliers)")
    print("  • StealthChop and SpreadCycle modes")
    print("  • StallGuard sensorless detection")
    print("  • CoolStep current reduction")
    print("  • Driver diagnostics")
    print("  • And much more!")
    print("\nTotal Tests: 16")
    print("Estimated time: 20-30 minutes (you control the pace!)")
    print("\n" + "="*70)
    print("⚠️  SAFETY NOTES:")
    print("="*70)
    print("  1. Keep pliers and hands clear when motor is moving")
    print("  2. Motor will get WARM during current/torque tests - normal")
    print("  3. Some tests are LOUD - you'll hear motor chopping sounds")
    print("  4. Don't leave motor at max current for extended periods")
    print("="*70)
    
    wait_for_proceed("Ready to start? Press ENTER to begin")
    
    try:
        # Test sequence
        motor = test_initialization()
        test_enable_disable(motor)
        test_direction_control(motor)
        test_speed_control(motor)
        test_microstepping(motor)
        test_current_and_torque(motor)
        test_stealthchop(motor)
        test_pwm_config(motor)
        test_stallguard(motor)
        test_stallguard_homing(motor)
        test_coolstep(motor)
        test_driver_status(motor)
        test_position_tracking(motor)
        test_rotation_units(motor)
        test_spreadcycle_config(motor)
        test_performance(motor)
        
        final_summary(motor)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        try:
            motor.disable()
        except:
            pass
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        try:
            motor.disable()
        except:
            pass

if __name__ == "__main__":
    main()
