const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {28, 26, 21, 19};
const uint8_t STEPPER_DIR_PINS[] = {27, 22, 20, 18};

uart_inst_t* const TMC_UART = uart0;
const int TMC_UART_TX_PIN = 16;
const int TMC_UART_RX_PIN = 17;
const int TMC_UART_BAUDRATE = 400000;

const int STEPPER_nEN_PINS[] = {0, 0, 0, 0};

const uint8_t DIGITAL_INPUT_COUNT = 4;
const int digital_input_pins[] = {9, 8, 13, 12};

const uint8_t DIGITAL_OUTPUT_COUNT = 2;
const int digital_output_pins[] = {14, 15};

i2c_inst_t* const I2C_PORT = i2c1;
const int I2C_SDA_PIN = 10;
const int I2C_SCL_PIN = 11;

const uint8_t SERVO_I2C_ADDRESS = 0x40; // Address of the PCA9685 controlling the servos

