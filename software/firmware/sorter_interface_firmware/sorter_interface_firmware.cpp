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
#include "pico/bootrom.h"

#include "message.h"

void CMDH_init(const BusMessage *msg, BusMessage *resp);
void CMDH_ping(const BusMessage *msg, BusMessage *resp);
void CMDH_reboot_bootloader(const BusMessage *msg, BusMessage *resp);
void CMDH_get_observability(const BusMessage *msg, BusMessage *resp);
void CMDH_get_version(const BusMessage *msg, BusMessage *resp);

const struct CommandTable baseCmdTable = { //
    .prefix = NULL,
    .commands = {{
        {"INIT", "", "s", 0, NULL, CMDH_init},
        {"PING", "", "", 255, NULL, CMDH_ping},
        {"REBOOT_BOOTLOADER", "", "", 0, NULL, CMDH_reboot_bootloader},
        {"GET_OBSERVABILITY", "", "s", 0, NULL, CMDH_get_observability},
        {"GET_VERSION", "", "s", 0, NULL, CMDH_get_version},
    }}};

void CMDH_stepper_move_steps(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_move_at_speed(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_set_speed_limits(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_set_acceleration(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_is_stopped(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_get_position(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_set_position(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_home(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_jitter(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_is_jittering(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_drv_set_enabled(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_drv_set_microsteps(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_drv_set_current(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_drv_read_register(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_drv_write_register(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_enable_stall_detection(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_get_stall_status(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_clear_stall(const BusMessage *msg, BusMessage *resp);
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
        {"JITTER", "iiii", "?", 16, VAL_stepper_channel, CMDH_stepper_jitter},
        {"IS_JITTERING", "", "B", 0, VAL_stepper_channel, CMDH_stepper_is_jittering},
        // StallGuard. GET_STALL_STATUS ignores the channel and returns a bitmask
        // of every channel on this board (bit i = stepper i latched-stalled), so
        // the backend learns all stalls in one bus round-trip.
        {"ENABLE_STALL_DETECTION", "?", "", 1, VAL_stepper_channel, CMDH_stepper_enable_stall_detection},
        {"GET_STALL_STATUS", "", "B", 0, VAL_stepper_channel, CMDH_stepper_get_stall_status},
        {"CLEAR_STALL", "", "", 0, VAL_stepper_channel, CMDH_stepper_clear_stall},
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
void CMDH_servo_move_to_and_release(const BusMessage *msg, BusMessage *resp);
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
        {"MOVE_TO", "H", "?", 2, VAL_servo_channel, CMDH_servo_move_to},
        {"SET_SPEED_LIMITS", "HH", "", 4, VAL_servo_channel, CMDH_servo_set_speed_limits},
        {"SET_ACCELERATION", "H", "", 2, VAL_servo_channel, CMDH_servo_set_acceleration},
        {"GET_POSITION", "", "H", 0, VAL_servo_channel, CMDH_servo_get_position},
        {"IS_STOPPED", "", "?", 0, VAL_servo_channel, CMDH_servo_is_stopped},
        {"STOP", "", "", 0, VAL_servo_channel, CMDH_servo_stop},
        {"SET_ENABLED", "?", "", 1, VAL_servo_channel, CMDH_servo_set_enabled},
        {"SET_DUTY_LIMITS", "HH", "", 4, VAL_servo_channel, CMDH_servo_set_duty_limits},
        // Payload: position (uint16) + optional max_duration_ms (uint16).
        // We use payload_length=255 (variable) so the dispatcher does not reject
        // legacy 2-byte sends. The handler itself accepts 2 or 4 bytes.
        {"MOVE_TO_AND_RELEASE", "HH", "?", 255, VAL_servo_channel, CMDH_servo_move_to_and_release},
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

#ifndef FIRMWARE_GIT_VERSION
#define FIRMWARE_GIT_VERSION "unknown"
#endif

#ifndef FIRMWARE_GIT_COMMIT
#define FIRMWARE_GIT_COMMIT "unknown"
#endif

#ifndef FIRMWARE_BUILD_TIME_UTC
#define FIRMWARE_BUILD_TIME_UTC "unknown"
#endif

#ifndef FIRMWARE_VARIANT
#define FIRMWARE_VARIANT "unknown"
#endif

char DEVICE_NAME[16] = INIT_DEVICE_NAME;
uint8_t DEVICE_ADDRESS = INIT_DEVICE_ADDRESS;

#if defined(HARDWARE_SKR_PICO)
#include "hwcfg_skr_pico.h"
#elif defined(HW_BASICALLY_V1_1)
#include "hwcfg_basically_v1_1.h"
#elif defined(HW_BASICALLY_V1_2)
#include "hwcfg_basically_v1_2.h"
#elif defined(HW_PICO2W_BREADBOARD)
#include "hwcfg_pico2w_breadboard.h"
#else
#error "No hardware config selected. Define HARDWARE_SKR_PICO, HW_BASICALLY_V1_1, HW_BASICALLY_V1_2, or HW_PICO2W_BREADBOARD."
#endif

// End board configuration

TMC_UART_Bus tmc_bus_0(TMC_UART_BUSES[0]);
#if TMC_UART_BUS_COUNT > 1
TMC_UART_Bus tmc_bus_1(TMC_UART_BUSES[1]);
#endif

static TMC_UART_Bus* tmc_bus_for(uint8_t i) {
#if TMC_UART_BUS_COUNT > 1
    return TMC_UART_BUS_INDEX[i] == 0 ? &tmc_bus_0 : &tmc_bus_1;
#else
    (void)i;
    return &tmc_bus_0;
#endif
}

template <size_t... I>
static std::array<TMC2209, STEPPER_COUNT> make_tmc_array(std::index_sequence<I...>) {
    return {TMC2209(tmc_bus_for(I), TMC_UART_ADDRESSES[I])...};
}

static auto tmc_drivers = make_tmc_array(std::make_index_sequence<STEPPER_COUNT>{});

template <size_t... I>
static std::array<Stepper, STEPPER_COUNT> make_stepper_array(std::index_sequence<I...>) {
    return {Stepper(STEPPER_STEP_PINS[I], STEPPER_DIR_PINS[I])...};
}

static auto steppers = make_stepper_array(std::make_index_sequence<STEPPER_COUNT>{});

// Tracks whether each stepper's hardware nEN pin has been pulled low.
// Starts false; set on first move or explicit enable so motors don't hold at boot.
static bool stepper_hw_enabled[STEPPER_COUNT] = {};

static void ensure_stepper_hw_enabled(int i) {
    if (!stepper_hw_enabled[i]) {
        gpio_put(STEPPER_nEN_PINS[i], 0);
        stepper_hw_enabled[i] = true;
    }
}

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
static int append_stepper_names_json(char *buf, size_t buf_size) {
    if (buf_size == 0) return -1;
    int written = snprintf(buf, buf_size, "[");
    if (written < 0 || (size_t)written >= buf_size) return -1;
    for (int i = 0; i < STEPPER_COUNT; i++) {
        int n = snprintf(buf + written, buf_size - written, "%s\"%s\"", i == 0 ? "" : ",", STEPPER_NAMES[i]);
        if (n < 0 || (size_t)(written + n) >= buf_size) return -1;
        written += n;
    }
    int n = snprintf(buf + written, buf_size - written, "]");
    if (n < 0 || (size_t)(written + n) >= buf_size) return -1;
    return written + n;
}

static int append_stepper_diag_pins_json(char *buf, size_t buf_size) {
    if (buf_size == 0) return -1;
    int written = snprintf(buf, buf_size, "[");
    if (written < 0 || (size_t)written >= buf_size) return -1;
    for (int i = 0; i < STEPPER_COUNT; i++) {
        int n = snprintf(buf + written, buf_size - written, "%s%d", i == 0 ? "" : ",", STEPPER_DIAG_PINS[i]);
        if (n < 0 || (size_t)(written + n) >= buf_size) return -1;
        written += n;
    }
    int n = snprintf(buf + written, buf_size - written, "]");
    if (n < 0 || (size_t)(written + n) >= buf_size) return -1;
    return written + n;
}

int dump_observability(char *buf, size_t buf_size) {
    if (buf_size == 0) {
        return 0;
    }

    char diag_pins_buf[128];
    int diag_pins_len = append_stepper_diag_pins_json(diag_pins_buf, sizeof(diag_pins_buf));

    int n_bytes = snprintf(
        buf,
        buf_size,
        "{\"hw\":\"%s\",\"diag_pins\":%s}",
        HW_ID,
        diag_pins_len > 0 ? diag_pins_buf : "[]");

    if (n_bytes >= 0 && (size_t)n_bytes < buf_size) {
        return n_bytes;
    }

    if (buf_size >= 3) {
        buf[0] = '{';
        buf[1] = '}';
        buf[2] = '\0';
        return 2;
    }

    buf[0] = '\0';
    return 0;
}

int dump_configuration(char *buf, size_t buf_size) {
    if (buf_size == 0) {
        return 0;
    }

    char names_buf[256];
    int names_len = append_stepper_names_json(names_buf, sizeof(names_buf));

    // Keep detect response compact to stay within bus frame limits.
    // Try richest payload first (with names), then progressively smaller valid JSON fallbacks.

    if (names_len > 0) {
        int n_bytes = snprintf(
            buf,
            buf_size,
            "{\"device_name\":\"%s\",\"stepper_count\":%d,"
            "\"stepper_names\":%s,"
            "\"digital_input_count\":%d,\"digital_output_count\":%d,\"servo_count\":%d}",
            DEVICE_NAME,
            STEPPER_COUNT,
            names_buf,
            DIGITAL_INPUT_COUNT,
            DIGITAL_OUTPUT_COUNT,
            SERVO_COUNT.load());

        if (n_bytes >= 0 && (size_t)n_bytes < buf_size) {
            return n_bytes;
        }

        n_bytes = snprintf(
            buf,
            buf_size,
            "{\"device_name\":\"%s\",\"hw\":\"%s\",\"stepper_count\":%d,"
            "\"stepper_names\":%s,"
            "\"digital_input_count\":%d,\"digital_output_count\":%d,\"servo_count\":%d}",
            DEVICE_NAME,
            HW_ID,
            STEPPER_COUNT,
            names_buf,
            DIGITAL_INPUT_COUNT,
            DIGITAL_OUTPUT_COUNT,
            SERVO_COUNT.load());

        if (n_bytes >= 0 && (size_t)n_bytes < buf_size) {
            return n_bytes;
        }
    }

    int n_bytes = snprintf(
        buf,
        buf_size,
        "{\"device_name\":\"%s\",\"hw\":\"%s\",\"stepper_count\":%d,\"digital_input_count\":%d,\"digital_output_count\":%d,\"servo_count\":%d}",
        DEVICE_NAME,
        HW_ID,
        STEPPER_COUNT,
        DIGITAL_INPUT_COUNT,
        DIGITAL_OUTPUT_COUNT,
        SERVO_COUNT.load());

    if (n_bytes >= 0 && (size_t)n_bytes < buf_size) {
        return n_bytes;
    }

    // Absolute last resort: always return valid JSON instead of truncated content.
    if (buf_size >= 3) {
        buf[0] = '{';
        buf[1] = '}';
        buf[2] = '\0';
        return 2;
    }

    buf[0] = '\0';
    return 0;
}

int dump_version(char *buf, size_t buf_size) {
    if (buf_size == 0) {
        return 0;
    }

    int n_bytes = snprintf(
        buf,
        buf_size,
        "{\"firmware_version\":\"%s\",\"variant\":\"%s\",\"commit\":\"%s\",\"build_time_utc\":\"%s\"}",
        FIRMWARE_GIT_VERSION,
        FIRMWARE_VARIANT,
        FIRMWARE_GIT_COMMIT,
        FIRMWARE_BUILD_TIME_UTC);

    if (n_bytes >= 0 && (size_t)n_bytes < buf_size) {
        return n_bytes;
    }

    if (buf_size >= 3) {
        buf[0] = '{';
        buf[1] = '}';
        buf[2] = '\0';
        return 2;
    }

    buf[0] = '\0';
    return 0;
}

/** \brief Initialize all hardware components, including GPIOs, UART, stepper drivers, etc.
 *
 * This function is called once at startup to set up the hardware for operation. It configures the TMC2209 drivers,
 * initializes the stepper objects, and sets up the GPIO pins for digital inputs and outputs.
 *
 * If called again, it will return the hardware to a known state.
 */
void initialize_hardware() {
    tmc_bus_0.setupComm(TMC_UART_BAUDRATE, TMC_UART_BUS_TX_PINS[0], TMC_UART_BUS_RX_PINS[0]);
#if TMC_UART_BUS_COUNT > 1
    tmc_bus_1.setupComm(TMC_UART_BAUDRATE, TMC_UART_BUS_TX_PINS[1], TMC_UART_BUS_RX_PINS[1]);
#endif
    // Initialize TMC2209 drivers and steppers
    for (int i = 0; i < STEPPER_COUNT; i++) {
        steppers[i].initialize();
        steppers[i].setAcceleration(20000);
        steppers[i].setSpeedLimits(16, 4000);
        tmc_drivers[i].initialize();
        tmc_drivers[i].enableDriver(true);
        tmc_drivers[i].setCurrent(0, 0, 0);
        tmc_drivers[i].setMicrosteps(MICROSTEP_8);
        tmc_drivers[i].enableStealthChop(true);
    }
    // Initialize nEN pins but leave HIGH (disabled) until first move or explicit enable
    for (int i = 0; i < STEPPER_COUNT; i++) {
        gpio_init(STEPPER_nEN_PINS[i]);
        gpio_set_dir(STEPPER_nEN_PINS[i], GPIO_OUT);
        gpio_put(STEPPER_nEN_PINS[i], 1);
        stepper_hw_enabled[i] = false;
    }
    // Initialize StallGuard DIAG inputs. TMC2209 drives DIAG high on stall, so
    // pull down for a defined idle level. Channels with no DIAG wire (pin < 0)
    // get _stall_pin = -1 and are simply never checked.
    for (int i = 0; i < STEPPER_COUNT; i++) {
        if (STEPPER_DIAG_PINS[i] >= 0) {
            gpio_init(STEPPER_DIAG_PINS[i]);
            gpio_set_dir(STEPPER_DIAG_PINS[i], GPIO_IN);
            gpio_pull_down(STEPPER_DIAG_PINS[i]);
        }
        steppers[i].setStallPin(STEPPER_DIAG_PINS[i]);
        steppers[i].enableStallDetection(false);
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
    // Turn on FAN0 permanently for cooling on boards that expose it.
    if (FAN0_OUTPUT_CHANNEL >= 0 && FAN0_OUTPUT_CHANNEL < DIGITAL_OUTPUT_COUNT) {
        gpio_put(digital_output_pins[FAN0_OUTPUT_CHANNEL], 1);
    }
    // Initialize i2c
    i2c_init(I2C_PORT, 400000);
    gpio_set_function(I2C_SDA_PIN, GPIO_FUNC_I2C);
    gpio_set_function(I2C_SCL_PIN, GPIO_FUNC_I2C);
    gpio_pull_up(I2C_SDA_PIN);
    gpio_pull_up(I2C_SCL_PIN);
    // Perform software reset on all servo controllers on the i2c bus
    uint8_t reset_command[] = {0x06}; // Software reset command for PCA9685
    int res, count = 5;
    do {
        res = i2c_write_timeout_us(I2C_PORT, 0x00, reset_command, 1, false, 1000); // Broadcast address 0x00 to reset all controllers
    } while (res < 0 && --count > 0); // Retry a few times in case some controllers are still resetting and not responding to i2c commands
    // Initialize servo controller and servos
    bool sc_present = servo_controller.initialize();
    if (sc_present) {
        servo_controller.setPWMFreq(50); // Set frequency to 50 Hz for standard hobby servos
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

void CMDH_reboot_bootloader(const BusMessage *msg, BusMessage *resp) {
    resp->payload_length = 0;
    reset_usb_boot(0, 0);
}

void CMDH_get_observability(const BusMessage *msg, BusMessage *resp) {
    (void)msg;
    resp->payload_length = dump_observability((char *)resp->payload, MAX_PAYLOAD_SIZE);
}

void CMDH_get_version(const BusMessage *msg, BusMessage *resp) {
    (void)msg;
    resp->payload_length = dump_version((char *)resp->payload, MAX_PAYLOAD_SIZE);
}

bool VAL_stepper_channel(uint8_t channel) { return channel < STEPPER_COUNT; }

void CMDH_stepper_move_steps(const BusMessage *msg, BusMessage *resp) {
    int32_t distance;
    memcpy(&distance, msg->payload, sizeof(distance));
    ensure_stepper_hw_enabled(msg->channel);
    bool result = steppers[msg->channel].moveSteps(distance);
    resp->payload[0] = result ? 1 : 0;
    resp->payload_length = 1;
}

void CMDH_stepper_move_at_speed(const BusMessage *msg, BusMessage *resp) {
    int32_t speed;
    memcpy(&speed, msg->payload, sizeof(speed));
    ensure_stepper_hw_enabled(msg->channel);
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
    uint8_t home_pin_channel = msg->payload[4];
    bool home_pin_polarity = msg->payload[5] != 0;
    if (home_pin_channel >= DIGITAL_INPUT_COUNT) {
        resp->command = msg->command | 0x80;
        resp->payload_length = snprintf((char *)resp->payload, MAX_PAYLOAD_SIZE, "Invalid home pin channel %u", home_pin_channel);
        return;
    }
    int home_pin = digital_input_pins[home_pin_channel];
    ensure_stepper_hw_enabled(msg->channel);
    steppers[msg->channel].home(home_speed, home_pin, home_pin_polarity);
    resp->payload_length = 0;
}

void CMDH_stepper_jitter(const BusMessage *msg, BusMessage *resp) {
    int32_t amplitude, cycles, speed, accel;
    memcpy(&amplitude, msg->payload, sizeof(amplitude));
    memcpy(&cycles, msg->payload + 4, sizeof(cycles));
    memcpy(&speed, msg->payload + 8, sizeof(speed));
    memcpy(&accel, msg->payload + 12, sizeof(accel));
    ensure_stepper_hw_enabled(msg->channel);
    bool result = steppers[msg->channel].jitter(amplitude, cycles, speed, accel);
    resp->payload[0] = result ? 1 : 0;
    resp->payload_length = 1;
}

void CMDH_stepper_is_jittering(const BusMessage *msg, BusMessage *resp) {
    bool is_jittering = steppers[msg->channel].isJittering();
    resp->payload[0] = is_jittering ? 1 : 0;
    resp->payload_length = 1;
}

void CMDH_stepper_drv_set_enabled(const BusMessage *msg, BusMessage *resp) {
    bool enabled = msg->payload[0] != 0;
    if (enabled) ensure_stepper_hw_enabled(msg->channel);
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

void CMDH_stepper_enable_stall_detection(const BusMessage *msg, BusMessage *resp) {
    bool enable = msg->payload[0] != 0;
    if (enable && STEPPER_DIAG_PINS[msg->channel] < 0) {
        resp->command = msg->command | 0x80; // Set error bit
        resp->payload_length =
            snprintf((char *)resp->payload, MAX_PAYLOAD_SIZE, "No DIAG pin for channel %u", msg->channel);
        return;
    }
    steppers[msg->channel].enableStallDetection(enable);
    resp->payload_length = 0;
}

void CMDH_stepper_get_stall_status(const BusMessage *msg, BusMessage *resp) {
    (void)msg; // Channel is ignored: we report every channel on this board at once.
    uint8_t mask = 0;
    for (int i = 0; i < STEPPER_COUNT; i++) {
        if (steppers[i].wasStalled()) mask |= (uint8_t)(1u << i);
    }
    resp->payload[0] = mask;
    resp->payload_length = 1;
}

void CMDH_stepper_clear_stall(const BusMessage *msg, BusMessage *resp) {
    steppers[msg->channel].clearStall();
    resp->payload_length = 0;
}

void CMDH_servo_move_to(const BusMessage *msg, BusMessage *resp) {
    uint16_t position;
    memcpy(&position, msg->payload, sizeof(position));
    bool result = servos[msg->channel].moveTo(position);
    resp->payload[0] = result ? 1 : 0;
    resp->payload_length = 1;
}

void CMDH_servo_move_to_and_release(const BusMessage *msg, BusMessage *resp) {
    uint16_t position;
    uint16_t max_duration_ms;
    memcpy(&position, msg->payload, sizeof(position));
    // New wire format: 4 bytes total (position + max duration in ms).
    // If the caller only sent 2 bytes (old style), we treat duration as 0 (use default).
    if (msg->payload_length >= 4) {
        memcpy(&max_duration_ms, msg->payload + sizeof(position), sizeof(max_duration_ms));
    } else {
        max_duration_ms = 0;
    }
    bool result = servos[msg->channel].moveToAndRelease(position, max_duration_ms);
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
    uint16_t acceleration;
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
