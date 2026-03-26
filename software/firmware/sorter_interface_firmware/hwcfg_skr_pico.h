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

uart_inst_t* const TMC_UART = uart1;
const int TMC_UART_TX_PIN = 8;
const int TMC_UART_RX_PIN = 9;
const int TMC_UART_BAUDRATE = 400000;
const uint8_t TMC_UART_ADDRESSES[] = {3, 0, 2, 1};

const int STEPPER_nEN_PINS[] = {15, 12, 7, 2};

const uint8_t DIGITAL_INPUT_COUNT = 4;
const int digital_input_pins[] = {4, 3, 25, 16};

const uint8_t DIGITAL_OUTPUT_COUNT = 5;
const int digital_output_pins[] = {21, 23, 17, 18, 20}; // [0]=neopixel, [1]=HE0, [2]=FAN0, [3]=FAN1, [4]=FAN2

i2c_inst_t* const I2C_PORT = i2c0;
const int I2C_SDA_PIN = 0;
const int I2C_SCL_PIN = 1;

const uint8_t SERVO_I2C_ADDRESS = 0x40; // Address of the PCA9685 controlling the servos

