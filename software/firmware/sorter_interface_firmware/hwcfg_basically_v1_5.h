// Basically V1-5 — 5-stepper board with serial bus servos instead of PWM servos.
// No PCA9685 and no I2C: GP10 and GP11 are stepper pins here.
// LED/24V-en: GPIO27 (ch0, ports 1 and 2), GPIO28 (ch1, ports 3 and 4) — AO3400A NMOS
// Hall input: GPIO3
// GPIO7 and GPIO19 go to the host header's isolated UART and stay unused for now:
// the host talks to this board over USB.

const char* const HW_ID = "basically_v1_5";

const uint8_t STEPPER_COUNT = 5;
const uint8_t STEPPER_STEP_PINS[] = {9, 10, 12, 14, 1};
const uint8_t STEPPER_DIR_PINS[]  = {8, 21, 11, 13, 0};

// Same names per channel as V1-2, so a machine moves between the boards unchanged.
#ifdef FIRMWARE_ROLE_DISTRIBUTION
const char* const STEPPER_NAMES[] = {
    "chute_stepper",       // ch0 — A2 — STEP=GP9,  DIR=GP8  — uart0 addr0
    "c_channel_1_rotor",   // ch1 — A3 — STEP=GP10, DIR=GP21 — uart0 addr1
    "c_channel_3_rotor",   // ch2 — A4 — STEP=GP12, DIR=GP11 — uart0 addr2
    "carousel",            // ch3 — A5 — STEP=GP14, DIR=GP13 — uart0 addr3
    "c_channel_2_rotor"    // ch4 — A6 — STEP=GP1,  DIR=GP0  — uart1 addr0
};
#else
const char* const STEPPER_NAMES[] = {
    "carousel",
    "third_c_channel_rotor",
    "second_c_channel_rotor",
    "first_c_channel_rotor",
    "fifth_stepper"
};
#endif

// Preprocessor macro, not a const — gates `#if TMC_UART_BUS_COUNT > 1` (see v1_2).
#define TMC_UART_BUS_COUNT 2
uart_inst_t* const TMC_UART_BUSES[] = {uart0, uart1};
const int TMC_UART_BUS_TX_PINS[] = {16, 4};
const int TMC_UART_BUS_RX_PINS[] = {17, 5};
const int TMC_UART_BAUDRATE = 400000;

const uint8_t TMC_UART_BUS_INDEX[]  = {0, 0, 0, 0, 1};
const uint8_t TMC_UART_ADDRESSES[]  = {0, 1, 2, 3, 0};

// Four drivers share UART0, and TMC2209 section 4.3 asks for SENDDELAY of at
// least 2 with more than one node on a line. Written to each before the first read.
#define TMC_UART0_SENDDELAY 2

const int STEPPER_nEN_PINS[] = {15, 15, 15, 15, 15};
const int STEPPER_DIAG_PINS[] = {26, 22, 20, 18, 6};

const uint8_t DIGITAL_INPUT_COUNT = 1;
const int digital_input_pins[] = {3};

const uint8_t DIGITAL_OUTPUT_COUNT = 2;
const int digital_output_pins[] = {27, 28};
const int FAN0_OUTPUT_CHANNEL = -1;
const uint8_t LED_OUTPUT_COUNT = 2;
