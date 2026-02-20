const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {11, 6, 19, 14};
const uint8_t STEPPER_DIR_PINS[] = {10, 5, 28, 13};

uart_inst_t* const TMC_UART = uart1;
const int TMC_UART_TX_PIN = 8;
const int TMC_UART_RX_PIN = 9;
const int TMC_UART_BAUDRATE = 400000;

const int STEPPER_nEN_PINS[] = {12, 7, 2, 15};

const uint8_t DIGITAL_INPUT_COUNT = 4;
const int digital_input_pins[] = {4, 3, 25, 16};

const uint8_t DIGITAL_OUTPUT_COUNT = 2;
const int digital_output_pins[] = {21, 23};

i2c_inst_t* const I2C_PORT = i2c0;
const int I2C_SDA_PIN = 0;
const int I2C_SCL_PIN = 1;

const uint8_t SERVO_I2C_ADDRESS = 0x40; // Address of the PCA9685 controlling the servos

