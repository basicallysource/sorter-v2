const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {11, 6, 19, 14};
const uint8_t STEPPER_DIR_PINS[] = {10, 5, 28, 13};

// Stepper channel wiring for this board family (SKR Pico)
// Channel 0: pins 11/10
// Channel 1: pins 6/5
// Channel 2: pins 19/28
// Channel 3: pins 14/13

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
// Channel 1: first_c_channel_rotor
// Channel 2: second_c_channel_rotor
// Channel 3: third_c_channel_rotor
const char* const STEPPER_NAMES[] = {
    "carousel",
    "first_c_channel_rotor",
    "second_c_channel_rotor",
    "third_c_channel_rotor"
};
#endif

uart_inst_t* const TMC_UART = uart1;
const int TMC_UART_TX_PIN = 8;
const int TMC_UART_RX_PIN = 9;
const int TMC_UART_BAUDRATE = 400000;
const uint8_t TMC_UART_ADDRESSES[] = {0, 2, 1, 3};

const int STEPPER_nEN_PINS[] = {12, 7, 2, 15};

const uint8_t DIGITAL_INPUT_COUNT = 4;
const int digital_input_pins[] = {4, 3, 25, 16};

const uint8_t DIGITAL_OUTPUT_COUNT = 5;
const int digital_output_pins[] = {21, 23, 17, 18, 20}; // [0]=neopixel, [1]=HE0, [2]=FAN0, [3]=FAN1, [4]=FAN2

i2c_inst_t* const I2C_PORT = i2c0;
const int I2C_SDA_PIN = 0;
const int I2C_SCL_PIN = 1;

const uint8_t SERVO_I2C_ADDRESS = 0x40; // Address of the PCA9685 controlling the servos

