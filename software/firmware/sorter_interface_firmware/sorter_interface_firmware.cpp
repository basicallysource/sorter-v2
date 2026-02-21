/*
 * Sorter Interface Firmware
 * Copyright (C) 2026 Jose I Romero
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

#include "hardware/timer.h"
#include "pico/multicore.h"
#include "pico/stdlib.h"
#include <array>
#include <stdio.h>
#include <string.h>
#include <utility>

#include "PCA9685.h"
#include "Servo.h"
#include "Stepper.h"
#include "TMC2209.h"
#include "TMC_UART.h"

#include "message.h"

void CMDH_init(const BusMessage *msg, BusMessage *resp);
void CMDH_ping(const BusMessage *msg, BusMessage *resp);

const struct CommandTable baseCmdTable = { //
    .prefix = NULL,
    .commands = {{
        {"INIT", "", "s", 0, NULL, CMDH_init},
        {"PING", "", "", 255, NULL, CMDH_ping},
    }}};

void CMDH_stepper_move_steps(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_move_at_speed(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_set_speed_limits(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_set_acceleration(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_is_stopped(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_get_position(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_set_position(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_home(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_drv_set_enabled(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_drv_set_microsteps(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_drv_set_current(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_drv_read_register(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_drv_write_register(const BusMessage *msg, BusMessage *resp);
bool VAL_stepper_channel(uint8_t channel);

const struct CommandTable stepperCmdTable = {
    .prefix = "STEPPER",
    .commands = {{
        {"MOVE_STEPS", "i", "?", 4, VAL_stepper_channel, CMDH_stepper_move_steps},
        {"MOVE_AT_SPEED", "i", "?", 4, VAL_stepper_channel, CMDH_stepper_move_at_speed},
        {"SET_SPEED_LIMITS", "II", "", 8, VAL_stepper_channel, CMDH_stepper_set_speed_limits},
        {"SET_ACCELERATION", "I", "", 4, VAL_stepper_channel, CMDH_stepper_set_acceleration},
        {"IS_STOPPED", "", "B", 0, VAL_stepper_channel, CMDH_stepper_is_stopped},
        {"GET_POSITION", "", "i", 0, VAL_stepper_channel, CMDH_stepper_get_position},
        {"SET_POSITION", "i", "", 4, VAL_stepper_channel, CMDH_stepper_set_position},
        {"HOME", "iB?", "", 6, VAL_stepper_channel, CMDH_stepper_home},
    }}};

const struct CommandTable stepperDrvCmdTable = {
    .prefix = "STEPPER_DRV",
    .commands = {{
        {"SET_ENABLED", "?", "", 1, VAL_stepper_channel, CMDH_stepper_drv_set_enabled},
        {"SET_MICROSTEPS", "H", "", 2, VAL_stepper_channel, CMDH_stepper_drv_set_microsteps},
        {"SET_CURRENT", "BBB", "", 3, VAL_stepper_channel, CMDH_stepper_drv_set_current},
        {NULL, NULL, NULL, 0, NULL, NULL},
        {NULL, NULL, NULL, 0, NULL, NULL},
        {NULL, NULL, NULL, 0, NULL, NULL},
        {NULL, NULL, NULL, 0, NULL, NULL},
        {NULL, NULL, NULL, 0, NULL, NULL},
        {"READ_REGISTER", "B", "I", 1, VAL_stepper_channel, CMDH_stepper_drv_read_register},
        {"WRITE_REGISTER", "BI", "", 5, VAL_stepper_channel, CMDH_stepper_drv_write_register},
    }}};

void CMDH_digital_read(const BusMessage *msg, BusMessage *resp);
void CMDH_digital_write(const BusMessage *msg, BusMessage *resp);
bool VAL_digital_out_channel(uint8_t channel);
bool VAL_digital_in_channel(uint8_t channel);

const struct CommandTable digitalIoCmdTable = { //
    .prefix = "DIGITAL_IO",
    .commands = {{
        {"READ", "", "?", 0, VAL_digital_in_channel, CMDH_digital_read},
        {"WRITE", "?", "", 1, VAL_digital_out_channel, CMDH_digital_write},
    }}};

void CMDH_servo_move_to(const BusMessage *msg, BusMessage *resp);
void CMDH_servo_set_speed_limits(const BusMessage *msg, BusMessage *resp);
void CMDH_servo_set_acceleration(const BusMessage *msg, BusMessage *resp);
void CMDH_servo_get_position(const BusMessage *msg, BusMessage *resp);
void CMDH_servo_is_stopped(const BusMessage *msg, BusMessage *resp);
void CMDH_servo_stop(const BusMessage *msg, BusMessage *resp);
void CMDH_servo_set_enabled(const BusMessage *msg, BusMessage *resp);
void CMDH_servo_set_duty_limits(const BusMessage *msg, BusMessage *resp);
bool VAL_servo_channel(uint8_t channel);

const struct CommandTable servoCmdTable = {
    .prefix = "SERVO",
    .commands = {{
        {"MOVE_TO", "I", "?", 4, VAL_servo_channel, CMDH_servo_move_to},
        {"SET_SPEED_LIMITS", "II", "", 8, VAL_servo_channel, CMDH_servo_set_speed_limits},
        {"SET_ACCELERATION", "I", "", 4, VAL_servo_channel, CMDH_servo_set_acceleration},
        {"GET_POSITION", "", "I", 0, VAL_servo_channel, CMDH_servo_get_position},
        {"IS_STOPPED", "", "?", 0, VAL_servo_channel, CMDH_servo_is_stopped},
        {"STOP", "", "", 0, VAL_servo_channel, CMDH_servo_stop},
        {"SET_ENABLED", "?", "", 1, VAL_servo_channel, CMDH_servo_set_enabled},
        {"SET_DUTY_LIMITS", "II", "", 8, VAL_servo_channel, CMDH_servo_set_duty_limits},
    }}};

const MasterCommandTable command_tables = {
    {&baseCmdTable, &stepperCmdTable, &stepperDrvCmdTable, &digitalIoCmdTable, &servoCmdTable}};

// #define MAIN_TRACE_ENABLED

#ifdef MAIN_TRACE_ENABLED
#define TRACE_PIN 8
#define TRACE_INIT()                                                                                                   \
    gpio_init(TRACE_PIN);                                                                                              \
    gpio_set_dir(TRACE_PIN, GPIO_OUT);
#define TRACE_HIGH() gpio_put(TRACE_PIN, 1)
#define TRACE_LOW() gpio_put(TRACE_PIN, 0)
#else
#define TRACE_INIT()
#define TRACE_HIGH()
#define TRACE_LOW()
#endif

// Board configuration
// This needs to be unique for each board and should be loaded from a config file or something in the future, but
// hardcoded for now.
// clang-format off

#ifndef INIT_DEVICE_NAME
#define INIT_DEVICE_NAME "FEEDER MB"
#endif

#ifndef INIT_DEVICE_ADDRESS
#define INIT_DEVICE_ADDRESS 0x00
#endif

char DEVICE_NAME[16] = INIT_DEVICE_NAME;
uint8_t DEVICE_ADDRESS = INIT_DEVICE_ADDRESS;

#ifdef HARDWARE_SKR_PICO
#include "hwcfg_skr_pico.h"
#else
#include "hwcfg_basically.h"
#endif

// End board configuration

TMC_UART_Bus tmc_bus(TMC_UART);

// Create the objects at compile time from the configuration constants.

template <size_t... I>
static std::array<TMC2209, STEPPER_COUNT> make_tmc_array(std::index_sequence<I...>) {
    return {TMC2209(&tmc_bus, TMC_UART_ADDRESSES[I])...};
}

static auto tmc_drivers = make_tmc_array(std::make_index_sequence<STEPPER_COUNT>{});

template <size_t... I>
static std::array<Stepper, STEPPER_COUNT> make_stepper_array(std::index_sequence<I...>) {
    return {Stepper(STEPPER_STEP_PINS[I], STEPPER_DIR_PINS[I])...};
}

static auto steppers = make_stepper_array(std::make_index_sequence<STEPPER_COUNT>{});

std::atomic<uint8_t> SERVO_COUNT = 0; // Number of servos controlled by the PCA9685, should be <= 16
PCA9685 servo_controller(SERVO_I2C_ADDRESS, I2C_PORT);
std::array<Servo, 16> servos{}; // Create 16 servo objects, but only the first SERVO_COUNT will be used

// clang-format on

/**
 * \brief Dump the board configuration as a JSON string for use by the driver software.
 * This is used for auto-detecting the board and its capabilities.
 *
 * \param buf Buffer to write the json string to
 * \param buf_size Size of the buffer in bytes
 * \return Number of bytes written to the buffer, excluding the null terminator
 */
int dump_configuration(char *buf, size_t buf_size) {
    int n_bytes;
    n_bytes =
        snprintf(buf, buf_size,
                 "{\"firmware_version\":\"1.0\",\"device_name\":\"%s\",\"device_address\":%d,"
                 "\"stepper_count\":%d,\"digital_input_count\":%d,\"digital_output_count\":%d,"
                 "\"servo_count\":%d}",
                 DEVICE_NAME, DEVICE_ADDRESS, STEPPER_COUNT, DIGITAL_INPUT_COUNT, DIGITAL_OUTPUT_COUNT, SERVO_COUNT.load());
    return n_bytes;
}

/** \brief Initialize all hardware components, including GPIOs, UART, stepper drivers, etc.
 *
 * This function is called once at startup to set up the hardware for operation. It configures the TMC2209 drivers,
 * initializes the stepper objects, and sets up the GPIO pins for digital inputs and outputs.
 *
 * If called again, it will return the hardware to a known state.
 */
void initialize_hardware() {
    // Initialize TMC UART bus
    tmc_bus.setupComm(TMC_UART_BAUDRATE, TMC_UART_TX_PIN, TMC_UART_RX_PIN);
    // Initialize TMC2209 drivers and steppers
    for (int i = 0; i < STEPPER_COUNT; i++) {
        // tmc_drivers[i].enableDriver(true);
        steppers[i].initialize();
        steppers[i].setAcceleration(20000);
        steppers[i].setSpeedLimits(16, 4000);
        tmc_drivers[i].initialize();
        tmc_drivers[i].enableDriver(true);
        tmc_drivers[i].setCurrent(16, 4, 10);
        tmc_drivers[i].setMicrosteps(MICROSTEP_8);
        tmc_drivers[i].enableStealthChop(true);
    }
    // Global enable for stepper drivers
    for (int i = 0; i < STEPPER_COUNT; i++) {
        gpio_init(STEPPER_nEN_PINS[i]);
        gpio_set_dir(STEPPER_nEN_PINS[i], GPIO_OUT);
        gpio_put(STEPPER_nEN_PINS[i], 0); // Enable stepper drivers
    }
    // Initialize digital inputs
    for (int i = 0; i < DIGITAL_INPUT_COUNT; i++) {
        gpio_init(digital_input_pins[i]);
        gpio_set_dir(digital_input_pins[i], GPIO_IN);
        gpio_pull_up(digital_input_pins[i]);
    }
    // Initialize digital outputs
    for (int i = 0; i < DIGITAL_OUTPUT_COUNT; i++) {
        gpio_init(digital_output_pins[i]);
        gpio_set_dir(digital_output_pins[i], GPIO_OUT);
        gpio_put(digital_output_pins[i], 0);
    }
    // Initialize i2c
    i2c_init(i2c0, 400000);
    gpio_set_function(I2C_SDA_PIN, GPIO_FUNC_I2C);
    gpio_set_function(I2C_SCL_PIN, GPIO_FUNC_I2C);
    gpio_pull_up(I2C_SDA_PIN);
    gpio_pull_up(I2C_SCL_PIN);
    // Initialize servo controller and servos
    bool sc_present = servo_controller.initialize();
    if (sc_present) {
        SERVO_COUNT = 16;
        for (int i = 0; i < SERVO_COUNT; i++) {
            servos[i].setEnabled(false);
            servo_controller.setPWM(i, 0); // Set all servos to 0 duty cycle (should be safe for all servos)
        }
    } else {
        SERVO_COUNT = 0;
    }
}

void CMDH_init(const BusMessage *msg, BusMessage *resp) {
    initialize_hardware();
    resp->payload_length = dump_configuration((char *)resp->payload, MAX_PAYLOAD_SIZE);
}

void CMDH_ping(const BusMessage *msg, BusMessage *resp) {
    // Echo back the payload from the message into the response
    memcpy(resp->payload, msg->payload, msg->payload_length);
    resp->payload_length = msg->payload_length;
}

bool VAL_stepper_channel(uint8_t channel) { return channel < STEPPER_COUNT; }

void CMDH_stepper_move_steps(const BusMessage *msg, BusMessage *resp) {
    int32_t distance;
    memcpy(&distance, msg->payload, sizeof(distance));
    bool result = steppers[msg->channel].moveSteps(distance);
    resp->payload[0] = result ? 1 : 0;
    resp->payload_length = 1;
}

void CMDH_stepper_move_at_speed(const BusMessage *msg, BusMessage *resp) {
    int32_t speed;
    memcpy(&speed, msg->payload, sizeof(speed));
    bool result = steppers[msg->channel].moveAtSpeed(speed);
    resp->payload[0] = result ? 1 : 0;
    resp->payload_length = 1;
}

bool VAL_digital_out_channel(uint8_t channel) { return channel < DIGITAL_OUTPUT_COUNT; }

bool VAL_digital_in_channel(uint8_t channel) { return channel < DIGITAL_INPUT_COUNT; }

void CMDH_digital_read(const BusMessage *msg, BusMessage *resp) {
    int pin = digital_input_pins[msg->channel];
    bool value = gpio_get(pin);
    resp->payload[0] = value ? 1 : 0;
    resp->payload_length = 1;
}

void CMDH_digital_write(const BusMessage *msg, BusMessage *resp) {
    int pin = digital_output_pins[msg->channel];
    bool value = msg->payload[0] != 0;
    gpio_put(pin, value ? 1 : 0);
    resp->payload_length = 0;
}

void CMDH_stepper_set_speed_limits(const BusMessage *msg, BusMessage *resp) {
    uint32_t min_speed, max_speed;
    memcpy(&min_speed, msg->payload, sizeof(min_speed));
    memcpy(&max_speed, msg->payload + sizeof(min_speed), sizeof(max_speed));
    steppers[msg->channel].setSpeedLimits(min_speed, max_speed);
    resp->payload_length = 0;
}

void CMDH_stepper_set_acceleration(const BusMessage *msg, BusMessage *resp) {
    uint32_t acceleration;
    memcpy(&acceleration, msg->payload, sizeof(acceleration));
    steppers[msg->channel].setAcceleration(acceleration);
    resp->payload_length = 0;
}

void CMDH_stepper_is_stopped(const BusMessage *msg, BusMessage *resp) {
    bool is_stopped = steppers[msg->channel].isStopped();
    resp->payload[0] = is_stopped ? 1 : 0;
    resp->payload_length = 1;
}

void CMDH_stepper_get_position(const BusMessage *msg, BusMessage *resp) {
    int32_t position = steppers[msg->channel].getPosition();
    memcpy(resp->payload, &position, sizeof(position));
    resp->payload_length = sizeof(position);
}

void CMDH_stepper_set_position(const BusMessage *msg, BusMessage *resp) {
    int32_t position;
    memcpy(&position, msg->payload, sizeof(position));
    steppers[msg->channel].setPosition(position);
    resp->payload_length = 0;
}

void CMDH_stepper_home(const BusMessage *msg, BusMessage *resp) {
    int32_t home_speed;
    memcpy(&home_speed, msg->payload, sizeof(home_speed));
    uint8_t home_pin = msg->payload[4];
    bool home_pin_polarity = msg->payload[5] != 0;
    steppers[msg->channel].home(home_speed, home_pin, home_pin_polarity);
    resp->payload_length = 0;
}

void CMDH_stepper_drv_set_enabled(const BusMessage *msg, BusMessage *resp) {
    bool enabled = msg->payload[0] != 0;
    tmc_drivers[msg->channel].enableDriver(enabled);
    resp->payload_length = 0;
}

void CMDH_stepper_drv_set_microsteps(const BusMessage *msg, BusMessage *resp) {
    uint16_t arg_microsteps;
    memcpy(&arg_microsteps, msg->payload, sizeof(arg_microsteps));
    TMC2209_Microstep microsteps;
    switch (arg_microsteps) {
    case 256:
        microsteps = MICROSTEP_256;
        break;
    case 128:
        microsteps = MICROSTEP_128;
        break;
    case 64:
        microsteps = MICROSTEP_64;
        break;
    case 32:
        microsteps = MICROSTEP_32;
        break;
    case 16:
        microsteps = MICROSTEP_16;
        break;
    case 8:
        microsteps = MICROSTEP_8;
        break;
    case 4:
        microsteps = MICROSTEP_4;
        break;
    case 2:
        microsteps = MICROSTEP_2;
        break;
    case 1:
        microsteps = MICROSTEP_FULL;
        break;
    default:
        resp->command = msg->command | 0x80; // Set error bit
        resp->payload_length =
            snprintf((char *)resp->payload, MAX_PAYLOAD_SIZE, "Invalid microstep value %u", arg_microsteps);
        return;
    }
    tmc_drivers[msg->channel].setMicrosteps(microsteps);
    resp->payload_length = 0;
}

void CMDH_stepper_drv_set_current(const BusMessage *msg, BusMessage *resp) {
    uint8_t run_current = msg->payload[0];
    uint8_t hold_current = msg->payload[1];
    uint8_t hold_delay = msg->payload[2];
    tmc_drivers[msg->channel].setCurrent(run_current, hold_current, hold_delay);
    resp->payload_length = 0;
}

void CMDH_stepper_drv_read_register(const BusMessage *msg, BusMessage *resp) {
    uint8_t reg = msg->payload[0];
    uint32_t value;
    int result = tmc_drivers[msg->channel].readRegister(reg, &value);
    if (result != 0) {
        resp->command = msg->command | 0x80; // Set error bit
        resp->payload_length = snprintf((char *)resp->payload, MAX_PAYLOAD_SIZE, "Failed to read register %d", reg);
        return;
    }
    memcpy(resp->payload, &value, sizeof(value));
    resp->payload_length = sizeof(value);
}

void CMDH_stepper_drv_write_register(const BusMessage *msg, BusMessage *resp) {
    uint8_t reg = msg->payload[0];
    uint32_t value;
    memcpy(&value, msg->payload + 1, sizeof(value));
    tmc_drivers[msg->channel].writeRegister(reg, value);
    resp->payload_length = 0;
}

void CMDH_servo_move_to(const BusMessage *msg, BusMessage *resp) {
    uint16_t position;
    memcpy(&position, msg->payload, sizeof(position));
    bool result = servos[msg->channel].moveTo(position);
    resp->payload[0] = result ? 1 : 0;
    resp->payload_length = 1;
}

void CMDH_servo_set_speed_limits(const BusMessage *msg, BusMessage *resp) {
    uint16_t min_speed, max_speed;
    memcpy(&min_speed, msg->payload, sizeof(min_speed));
    memcpy(&max_speed, msg->payload + sizeof(min_speed), sizeof(max_speed));
    servos[msg->channel].setSpeedLimits(min_speed, max_speed);
    resp->payload_length = 0;
}

void CMDH_servo_set_acceleration(const BusMessage *msg, BusMessage *resp) {
    uint32_t acceleration;
    memcpy(&acceleration, msg->payload, sizeof(acceleration));
    servos[msg->channel].setAcceleration(acceleration);
    resp->payload_length = 0;
}

void CMDH_servo_get_position(const BusMessage *msg, BusMessage *resp) {
    uint16_t position = servos[msg->channel].getCurrentPosition();
    memcpy(resp->payload, &position, sizeof(position));
    resp->payload_length = sizeof(position);
}

void CMDH_servo_is_stopped(const BusMessage *msg, BusMessage *resp) {
    bool is_stopped = servos[msg->channel].isStopped();
    resp->payload[0] = is_stopped ? 1 : 0;
    resp->payload_length = 1;
}

void CMDH_servo_stop(const BusMessage *msg, BusMessage *resp) {
    servos[msg->channel].stopMotion();
    resp->payload_length = 0;
}

void CMDH_servo_set_enabled(const BusMessage *msg, BusMessage *resp) {
    bool enabled = msg->payload[0] != 0;
    servos[msg->channel].setEnabled(enabled);
    resp->payload_length = 0;
}

void CMDH_servo_set_duty_limits(const BusMessage *msg, BusMessage *resp) {
    uint16_t min_duty, max_duty;
    memcpy(&min_duty, msg->payload, sizeof(min_duty));
    memcpy(&max_duty, msg->payload + sizeof(min_duty), sizeof(max_duty));
    servos[msg->channel].setDutyCycleLimits(min_duty, max_duty);
    resp->payload_length = 0;
}

bool VAL_servo_channel(uint8_t channel) { return channel < SERVO_COUNT; }

const uint32_t STEP_TICK_PERIOD_US = 1000000 / STEP_TICK_RATE_HZ;
const uint32_t MOTION_UPDATE_PERIOD_US = 1000000 / STEP_MOTION_UPDATE_RATE_HZ;

void core1_stepgen_isr(uint alarm_num) {
    TRACE_HIGH();
    // Core 1 step generator interrupt service routine, called at STEP_TICK_RATE_HZ
    hardware_alarm_set_target(alarm_num, time_us_64() + STEP_TICK_PERIOD_US);

    for (int i = 0; i < STEPPER_COUNT; i++) {
        steppers[i].stepgen_tick();
    }
    TRACE_LOW();
}

void core1_motion_update_isr(uint alarm_num) {
    TRACE_HIGH();
    // Core 1 motion update interrupt service routine, called at STEP_MOTION_UPDATE_RATE_HZ
    hardware_alarm_set_target(alarm_num, time_us_64() + MOTION_UPDATE_PERIOD_US);

    for (int i = 0; i < STEPPER_COUNT; i++) {
        steppers[i].motion_update_tick();
    }
    TRACE_LOW();
}

const int SERVO_UPDATE_PERIOD_US = 1000000 / SERVO_UPDATE_RATE_HZ;

void core1_entry() {
    // Core 1 main loop, this deals with high speed real-time tasks like stepper control.
    TRACE_INIT();
    // Setup step generator timer interrupt
    hardware_alarm_claim(0);
    hardware_alarm_set_target(0, time_us_64() + STEP_TICK_PERIOD_US);
    hardware_alarm_set_callback(0, core1_stepgen_isr);
    // Setup motion update timer interrupt
    hardware_alarm_claim(1);
    hardware_alarm_set_target(1, time_us_64() + MOTION_UPDATE_PERIOD_US);
    hardware_alarm_set_callback(1, core1_motion_update_isr);

    uint32_t last_servo_update_time = time_us_32();

    while (true) {
        // Update servos in our free time
        uint32_t now = time_us_32();
        if (now - last_servo_update_time >= SERVO_UPDATE_PERIOD_US) {
            for (int i = 0; i < SERVO_COUNT; i++) {
                servos[i].update();
                servo_controller.setPWM(i, servos[i].getCurrentDuty());
            }
            last_servo_update_time = now;
        }
    }
}

int main() {
    stdio_init_all();
    initialize_hardware();
    // Initialize Core 1
    multicore_launch_core1(core1_entry);

    BusMessageProcessor msg_processor(DEVICE_ADDRESS, command_tables, [](const char *data, int length) {
        stdio_put_string(data, length, false, false);
    });
    // Main loop, this deals with communications and high level command processing
    while (true) {
        // Read characters from USB if available and feed to the message processor
        while (true) {
            int c = stdio_getchar_timeout_us(0);
            if (c == PICO_ERROR_TIMEOUT)
                break; // No more characters to read
            msg_processor.processIncomingData((char)c);
            msg_processor.processQueuedMessage();
        }
    }
}
