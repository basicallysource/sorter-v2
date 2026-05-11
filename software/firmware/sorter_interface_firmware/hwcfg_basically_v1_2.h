// Basically V1-2 — reworked 5-stepper board (88-update-pcb)
// LED/24V-en: GPIO1 (ch0), GPIO6 (ch1) — AO3400A NMOS, 2 parallel pairs
// Hall inputs: GPIO3, GPIO2

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

const uint8_t TMC_UART_BUS_INDEX[]  = {0, 0, 0, 0, 1};
const uint8_t TMC_UART_ADDRESSES[]  = {0, 1, 2, 3, 0};

const int STEPPER_nEN_PINS[] = {0, 0, 0, 0, 0};

const uint8_t DIGITAL_INPUT_COUNT = 2;
const int digital_input_pins[] = {3, 2};

const uint8_t DIGITAL_OUTPUT_COUNT = 2;
const int digital_output_pins[] = {1, 6};
const int FAN0_OUTPUT_CHANNEL = -1;

i2c_inst_t* const I2C_PORT = i2c1;
const int I2C_SDA_PIN = 10;
const int I2C_SCL_PIN = 11;

const uint8_t SERVO_I2C_ADDRESS = 0x40;
