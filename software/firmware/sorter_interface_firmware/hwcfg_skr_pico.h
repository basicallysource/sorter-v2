const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {11, 6, 19, 14};
const uint8_t STEPPER_DIR_PINS[] = {10, 5, 28, 13};

// Stepper channel name mapping for this board (SKR Pico)
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

