#ifdef HW_BASICALLY_V1

const uint8_t STEPPER_COUNT = 5;
const uint8_t STEPPER_STEP_PINS[] = {28, 26, 21, 19, 8};
const uint8_t STEPPER_DIR_PINS[]  = {27, 22, 20, 18, 7};

#ifdef FIRMWARE_ROLE_DISTRIBUTION
const char* const STEPPER_NAMES[] = {
    "chute_stepper",
    "distribution_aux_1",
    "distribution_aux_2",
    "distribution_aux_3",
    "fifth_stepper"
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

const uint8_t TMC_UART_BUS_COUNT = 2;
uart_inst_t* const TMC_UART_BUSES[] = {uart0, uart1};
const int TMC_UART_BUS_TX_PINS[] = {16, 4};
const int TMC_UART_BUS_RX_PINS[] = {17, 5};
const int TMC_UART_BAUDRATE = 400000;

// Per-stepper TMC2209 UART bus index (into TMC_UART_BUSES) and slave address.
// Stepper 4 (the new fifth driver) is alone on UART1.
const uint8_t TMC_UART_BUS_INDEX[]  = {0, 1, 2, 3, 0};
const uint8_t TMC_UART_ADDRESSES[]  = {0, 1, 2, 3, 0};

const int STEPPER_nEN_PINS[] = {0, 0, 0, 0, 0};

const uint8_t DIGITAL_INPUT_COUNT = 0;
const int digital_input_pins[] = {};

const uint8_t DIGITAL_OUTPUT_COUNT = 2;
const int digital_output_pins[] = {14, 15};

i2c_inst_t* const I2C_PORT = i2c1;
const int I2C_SDA_PIN = 10;
const int I2C_SCL_PIN = 11;

const uint8_t SERVO_I2C_ADDRESS = 0x40;

#else

const uint8_t STEPPER_COUNT = 4;
const uint8_t STEPPER_STEP_PINS[] = {28, 26, 21, 19};
const uint8_t STEPPER_DIR_PINS[] = {27, 22, 20, 18};

#ifdef FIRMWARE_ROLE_DISTRIBUTION
const char* const STEPPER_NAMES[] = {
    "chute_stepper",
    "distribution_aux_1",
    "distribution_aux_2",
    "distribution_aux_3"
};
#else
const char* const STEPPER_NAMES[] = {
    "carousel",
    "third_c_channel_rotor",
    "second_c_channel_rotor",
    "first_c_channel_rotor"
};
#endif

const uint8_t TMC_UART_BUS_COUNT = 1;
uart_inst_t* const TMC_UART_BUSES[] = {uart0};
const int TMC_UART_BUS_TX_PINS[] = {16};
const int TMC_UART_BUS_RX_PINS[] = {17};
const int TMC_UART_BAUDRATE = 400000;

const uint8_t TMC_UART_BUS_INDEX[] = {0, 0, 0, 0};
const uint8_t TMC_UART_ADDRESSES[] = {0, 1, 2, 3};

const int STEPPER_nEN_PINS[] = {0, 0, 0, 0};

const uint8_t DIGITAL_INPUT_COUNT = 4;
const int digital_input_pins[] = {9, 8, 13, 12};

const uint8_t DIGITAL_OUTPUT_COUNT = 2;
const int digital_output_pins[] = {14, 15};

i2c_inst_t* const I2C_PORT = i2c1;
const int I2C_SDA_PIN = 10;
const int I2C_SCL_PIN = 11;

const uint8_t SERVO_I2C_ADDRESS = 0x40;

#endif
