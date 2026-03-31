const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {28, 26, 21, 19};
const uint8_t STEPPER_DIR_PINS[] = {27, 22, 20, 18};

// Stepper channel wiring for this board family (Basically / FEEDER MB layout)
// Channel 0: pins 28/27
// Channel 1: pins 26/22
// Channel 2: pins 21/20
// Channel 3: pins 19/18

// Default build is for feeder role
// Uncomment the following line to build for distribution role:
// #define FIRMWARE_ROLE_DISTRIBUTION

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
// Channel 0: carousel
// Channel 1: third_c_channel_rotor
// Channel 2: second_c_channel_rotor
// Channel 3: first_c_channel_rotor
const char* const STEPPER_NAMES[] = {
    "carousel",
    "third_c_channel_rotor",
    "second_c_channel_rotor",
    "first_c_channel_rotor"
};
#endif

uart_inst_t* const TMC_UART = uart0;
const int TMC_UART_TX_PIN = 16;
const int TMC_UART_RX_PIN = 17;
const int TMC_UART_BAUDRATE = 400000;
// TMC2209 UART slave addresses per channel (sequential on Basically board)
const uint8_t TMC_UART_ADDRESSES[] = {0, 1, 2, 3};

const int STEPPER_nEN_PINS[] = {0, 0, 0, 0};
const int STEPPER_DIAG_PINS[] = {1, -1, -1, -1}; // GPIO per channel, -1 = not wired

const uint8_t DIGITAL_INPUT_COUNT = 4;
const int digital_input_pins[] = {9, 8, 13, 12};

const uint8_t DIGITAL_OUTPUT_COUNT = 2;
const int digital_output_pins[] = {14, 15};

i2c_inst_t* const I2C_PORT = i2c1;
const int I2C_SDA_PIN = 10;
const int I2C_SCL_PIN = 11;

const uint8_t SERVO_I2C_ADDRESS = 0x40; // Address of the PCA9685 controlling the servos

