// Pico 2W (RP2350) breadboard — feeder + classification channel
// ENGINEER: Replace all pin numbers below with your actual wiring.
//
// IMPORTANT: This board is an RP2350 (Pico 2 W). Configure CMake with
//   -DPICO_BOARD=pico2_w
// otherwise the SDK builds an RP2040 binary that will not run here.

const char* const HW_ID = "pico2w_breadboard";

const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {/* CH0_STEP */ 0, /* CH1_STEP */ 0, /* CH2_STEP */ 0, /* CH3_STEP */ 0};
const uint8_t STEPPER_DIR_PINS[]  = {/* CH0_DIR  */ 0, /* CH1_DIR  */ 0, /* CH2_DIR  */ 0, /* CH3_DIR  */ 0};

// Feeder role: these exact names are required by the backend.
// CH0 → classification_channel (C4)
// CH1 → third_c_channel_rotor (C3)
// CH2 → second_c_channel_rotor (C2)
// CH3 → first_c_channel_rotor (C1 bulk)
#ifdef FIRMWARE_ROLE_DISTRIBUTION
const char* const STEPPER_NAMES[] = {
    "chute_stepper",
    "distribution_aux_1",
    "distribution_aux_2",
    "distribution_aux_3"
};
#else
const char* const STEPPER_NAMES[] = {
    "carousel",                // classification channel (C4) — backend aliases this
    "third_c_channel_rotor",
    "second_c_channel_rotor",
    "first_c_channel_rotor"
};
#endif

// Single UART bus for all 4 TMC2209 drivers.
// Preprocessor macro, not a const — gates #if TMC_UART_BUS_COUNT > 1.
#define TMC_UART_BUS_COUNT 1
uart_inst_t* const TMC_UART_BUSES[] = {uart0};
const int TMC_UART_BUS_TX_PINS[] = {/* TX_PIN */ 0};
const int TMC_UART_BUS_RX_PINS[] = {/* RX_PIN */ 0};
const int TMC_UART_BAUDRATE = 400000;

// TMC2209 UART addresses (0–3, set via MS1/MS2 pins on each driver)
const uint8_t TMC_UART_BUS_INDEX[] = {0, 0, 0, 0};
const uint8_t TMC_UART_ADDRESSES[] = {/* addr_ch0 */ 0, /* addr_ch1 */ 1, /* addr_ch2 */ 2, /* addr_ch3 */ 3};

// nEN tied low (always enabled) or wired per channel
const int STEPPER_nEN_PINS[] = {0, 0, 0, 0};

// DIAG pins NOT wired on breadboard — set all to -1 to disable StallGuard.
const int STEPPER_DIAG_PINS[] = {-1, -1, -1, -1};

// No endstops needed for classification_channel mode (optical spoke homing)
// Set to 0 unless physical hall/endstop sensors are wired.
const uint8_t DIGITAL_INPUT_COUNT = 0;
const int digital_input_pins[] = {0};

const uint8_t DIGITAL_OUTPUT_COUNT = 0;
const int digital_output_pins[] = {0};
const int FAN0_OUTPUT_CHANNEL = -1;

// I2C for servo expansion (PCA9685) — not needed if --disable servos is used,
// but the firmware still compiles it in. Wire or leave unconnected.
i2c_inst_t* const I2C_PORT = i2c1;
const int I2C_SDA_PIN = /* SDA_PIN */ 0;
const int I2C_SCL_PIN = /* SCL_PIN */ 0;

const uint8_t SERVO_I2C_ADDRESS = 0x40;
