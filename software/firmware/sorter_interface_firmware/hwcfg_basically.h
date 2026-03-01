const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {28, 26, 21, 19};
const uint8_t STEPPER_DIR_PINS[] = {27, 22, 20, 18};

// Stepper channel name mapping for this board (FEEDER MB)
// Channel 0: carousel
// Channel 1: third_c_channel_rotor (pins 26/22 are wired to 3rd rotor)
// Channel 2: second_c_channel_rotor
// Channel 3: first_c_channel_rotor (pins 19/18 are wired to 1st rotor)
const char* const STEPPER_NAMES[] = {
    "first_c_channel_rotor",
    "second_c_channel_rotor",
    "third_c_channel_rotor",
    "carousel"
};

uart_inst_t* const TMC_UART = uart0;
const int TMC_UART_TX_PIN = 16;
const int TMC_UART_RX_PIN = 17;
const int TMC_UART_BAUDRATE = 400000;
// TMC2209 UART slave addresses per channel (sequential on Basically board)
const uint8_t TMC_UART_ADDRESSES[] = {0, 1, 2, 3};

const int STEPPER_nEN_PINS[] = {0, 0, 0, 0};

const uint8_t DIGITAL_INPUT_COUNT = 4;
const int digital_input_pins[] = {9, 8, 13, 12};

const uint8_t DIGITAL_OUTPUT_COUNT = 2;
const int digital_output_pins[] = {14, 15};

i2c_inst_t* const I2C_PORT = i2c1;
const int I2C_SDA_PIN = 10;
const int I2C_SCL_PIN = 11;

const uint8_t SERVO_I2C_ADDRESS = 0x40; // Address of the PCA9685 controlling the servos

