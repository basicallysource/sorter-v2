const char* const HW_ID = "skr_pico";

const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {14, 11, 6, 19};
const uint8_t STEPPER_DIR_PINS[] = {13, 10, 5, 28};

// Stepper channel wiring for this board family (SKR Pico)
// Channel 0: pins 14/13 (E0)
// Channel 1: pins 11/10 (X)
// Channel 2: pins 6/5   (Y)
// Channel 3: pins 19/28 (Z)

// Role-specific logical naming over identical channel wiring.
#ifdef FIRMWARE_ROLE_DISTRIBUTION
// Distribution role (example mapping)
// Channel 0: chute_stepper
// Channel 1: distribution_aux_1
// Channel 2: distribution_aux_2
// Channel 3: distribution_aux_3
const char* const STEPPER_NAMES[] = {
    "chute_stepper",
    "distribution_aux_1",
    "distribution_aux_2",
    "distribution_aux_3"
};
#else
// Feeder role
// Channel 0: c_channel_1_rotor (E0 port) — bulk agitator
// Channel 1: c_channel_2_rotor (X port)
// Channel 2: c_channel_3_rotor (Y port)
// Channel 3: carousel          (Z port)
const char* const STEPPER_NAMES[] = {
    "c_channel_1_rotor",
    "c_channel_2_rotor",
    "c_channel_3_rotor",
    "carousel"
};
#endif

// Preprocessor macro, not a const — gates `#if TMC_UART_BUS_COUNT > 1` (see v1_2).
#define TMC_UART_BUS_COUNT 1
uart_inst_t* const TMC_UART_BUSES[] = {uart1};
const int TMC_UART_BUS_TX_PINS[] = {8};
const int TMC_UART_BUS_RX_PINS[] = {9};
const int TMC_UART_BAUDRATE = 400000;
const uint8_t TMC_UART_BUS_INDEX[] = {0, 0, 0, 0};
const uint8_t TMC_UART_ADDRESSES[] = {3, 0, 2, 1};

const int STEPPER_nEN_PINS[] = {15, 12, 7, 2};
const int STEPPER_DIAG_PINS[] = {-1, -1, -1, -1};

const uint8_t DIGITAL_INPUT_COUNT = 4;
const int digital_input_pins[] = {4, 3, 25, 16};

const uint8_t DIGITAL_OUTPUT_COUNT = 5;
// SKR Pico output pins (BTT pinout): GPIO18 = FAN2, GPIO20 = FAN3, GPIO17 = FAN1
// (the fan header the firmware drives ON at boot), GPIO21 = HB (bed heater
// terminal), GPIO23 = HE (hotend heater terminal). All are N-FET low-side
// outputs passing the input supply rail; every pin boots LOW and then
// FAN0_OUTPUT_CHANNEL is driven HIGH. (The onboard WS2812 sits on GPIO24 and is
// not exposed as a digital output.)
const int digital_output_pins[] = {18, 20, 21, 23, 17};
const int FAN0_OUTPUT_CHANNEL = 4;
// The first LED_OUTPUT_COUNT digital outputs are the PWM LED drivers this board
// offers the host. The SKR Pico has no dedicated LED header; the two fan headers
// that boot LOW (GPIO18/GPIO20, channels 0-1) are the natural lamp ports — the
// boot-ON fan header (GPIO17) and the heater terminals are deliberately kept
// outside the LED range. Boards with none declare 0; a board that grows non-LED
// outputs keeps its LED channels first in digital_output_pins.
const uint8_t LED_OUTPUT_COUNT = 2;

i2c_inst_t* const I2C_PORT = i2c0;
const int I2C_SDA_PIN = 0;
const int I2C_SCL_PIN = 1;

const uint8_t SERVO_I2C_ADDRESS = 0x40; // Address of the PCA9685 controlling the servos
