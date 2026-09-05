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

#include "hardware/pwm.h"
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
void CMDH_stepper_encoder_config(const BusMessage *msg, BusMessage *resp);
void CMDH_stepper_encoder_status(const BusMessage *msg, BusMessage *resp);
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
        // Position encoder (AS5600 on the motor shaft, I2C). ENCODER_CONFIG:
        // sign (+1/-1), encoder counts per 1000 microsteps, tolerance in counts,
        // enable. ENCODER_STATUS: raw angle, deviation (counts), AS5600 status,
        // AGC, latch count.
        {"ENCODER_CONFIG", "bIH?", "", 8, VAL_stepper_channel, CMDH_stepper_encoder_config},
        {"ENCODER_STATUS", "", "HiBBH", 0, VAL_stepper_channel, CMDH_stepper_encoder_status},
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
void CMDH_digital_write_pwm(const BusMessage *msg, BusMessage *resp);
bool VAL_digital_out_channel(uint8_t channel);
bool VAL_digital_in_channel(uint8_t channel);

const struct CommandTable digitalIoCmdTable = { //
    .prefix = "DIGITAL_IO",
    .commands = {{
        {"READ", "", "?", 0, VAL_digital_in_channel, CMDH_digital_read},
        {"WRITE", "?", "", 1, VAL_digital_out_channel, CMDH_digital_write},
        {"WRITE_PWM", "H", "", 2, VAL_digital_out_channel, CMDH_digital_write_pwm},
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
#else
#error "No hardware config selected. Define HARDWARE_SKR_PICO, HW_BASICALLY_V1_1, or HW_BASICALLY_V1_2."
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

// Software StallGuard (boards whose TMC DIAG lines are not wired to the MCU,
// e.g. the SKR Pico config). The backend configures SGTHRS/TCOOLTHRS over UART
// exactly as for the DIAG path; we remember the last written values and, while
// an armed stepper cruises, poll TSTEP and SG_RESULT on core0 and latch a stall
// under the same rule the driver applies to DIAG: SG_RESULT <= 2*SGTHRS while
// TSTEP <= TCOOLTHRS (i.e. above the velocity floor). Two consecutive hits are
// required so a single noisy read cannot stop a motor.
//
// Each poll tick issues exactly one UART read per channel: TSTEP on one tick,
// SG_RESULT on the next. Two reads back to back fail: the TMC2209 needs the
// bus idle after its reply before it accepts the next sync byte, and the
// second read then times out (measured on the B1 chute: TSTEP fine, SG_RESULT
// failing on ~40 of 44 polls).
#define TMC_REG_TSTEP 0x12
#define TMC_REG_TCOOLTHRS 0x14
#define TMC_REG_SGTHRS 0x40
#define TMC_REG_SG_RESULT 0x41
#define SOFT_SG_POLL_INTERVAL_US 2500
#define SOFT_SG_HITS_TO_LATCH 2
static uint32_t soft_sg_sgthrs[STEPPER_COUNT] = {0};
static uint32_t soft_sg_tcoolthrs[STEPPER_COUNT] = {0};
static uint8_t soft_sg_hits[STEPPER_COUNT] = {0};
static bool soft_sg_read_sg_next[STEPPER_COUNT] = {false}; // false = TSTEP next, true = SG_RESULT next
// Debug view of the software poll, exported in GET_OBSERVABILITY.
static uint16_t soft_sg_latches[STEPPER_COUNT] = {0};
static uint32_t soft_sg_last_tstep[STEPPER_COUNT] = {0};
static uint32_t soft_sg_last_sg[STEPPER_COUNT] = {0};
static uint8_t soft_sg_gate[STEPPER_COUNT] = {0};       // why the last poll returned early

// ---------------------------------------------------------------------------
// Shaft encoder position check. One AS5600 per board (fixed I2C address) on
// the motor's rear shaft; the backend tells us which channel it belongs to.
// Every ENC_POLL_INTERVAL_US the poll reads the angle, unwraps it into a
// running count and compares it with the stepper's commanded position
// (counts = offset + sign * position * counts_per_1000_usteps / 1000). A
// deviation beyond the tolerance on ENC_HITS_TO_LATCH consecutive polls
// latches the same stall flag StallGuard uses, so the backend's incident
// path (pause, re-home) is shared. Unlike StallGuard this works on ramps and
// at the target. A position jump larger than any real move between two polls
// (SET_POSITION / homing zeroed the counter) re-captures the offset.
#include "AS5600.h"
#define ENC_POLL_INTERVAL_US 5000
#define ENC_HITS_TO_LATCH 3
#define ENC_STATUS_EVERY_N_POLLS 20
#define ENC_RESET_JUMP_USTEPS 2000
static AS5600 shaft_encoder(I2C_PORT);
struct EncoderCheck {
    bool enabled = false;
    int8_t sign = 1;
    uint32_t counts_per_kusteps = 2560; // 4096 counts / 1600 microsteps * 1000
    uint16_t tolerance_counts = 82;     // 4 full steps at 8 microsteps
    bool synced = false;                // offset captured
    uint16_t last_raw = 0;
    int32_t unwrapped = 0;
    int32_t offset = 0;
    int32_t last_position = 0;
    int32_t deviation = 0;
    uint8_t hits = 0;
    uint8_t status = 0;                 // AS5600 STATUS register (MD/ML/MH)
    uint8_t agc = 0;
    uint16_t latches = 0;
    uint8_t i2c_errors = 0;             // saturating
};
static EncoderCheck enc[STEPPER_COUNT];
static int8_t enc_channel = -1;         // the one channel with the encoder, -1 = none

static int32_t enc_expected_counts(const EncoderCheck &e, int32_t position) {
    return e.offset + (int32_t)(((int64_t)e.sign * position * (int64_t)e.counts_per_kusteps) / 1000);
}


template <size_t... I>
static std::array<Stepper, STEPPER_COUNT> make_stepper_array(std::index_sequence<I...>) {
    return {Stepper(STEPPER_STEP_PINS[I], STEPPER_DIR_PINS[I])...};
}

static auto steppers = make_stepper_array(std::make_index_sequence<STEPPER_COUNT>{});

// Tracks whether each stepper's hardware nEN pin has been pulled low.
// Starts false; set on first move or explicit enable so motors don't hold at boot.
static bool stepper_hw_enabled[STEPPER_COUNT] = {};

// Tracks whether each stepper's TMC chopper (CHOPCONF.TOFF) is on. This is a
// SEPARATE enable gate from the nEN pin above: DRV_SET_ENABLED false cuts current
// via the register (TOFF=0) but leaves nEN low, so without this tracking the next
// move/home would step a current-less motor forever (state runs, shaft doesn't
// turn, endstop never fires). Starts true to match enableDriver(true) in setup().
static bool stepper_drv_current_on[STEPPER_COUNT];

// Tracks which digital outputs currently have their pad routed to the PWM block
// rather than SIO. Declared up here because initialize_hardware() has to clear
// it: it puts every output pad back on SIO, and a stale "already PWM" flag would
// make later duty writes land on a pad the PWM block no longer drives.
static bool digital_output_pwm_active[DIGITAL_OUTPUT_COUNT];

static void ensure_stepper_hw_enabled(int i) {
    if (!stepper_hw_enabled[i]) {
        gpio_put(STEPPER_nEN_PINS[i], 0);
        stepper_hw_enabled[i] = true;
    }
    // Re-energize the chopper if a prior DRV_SET_ENABLED false turned it off, so a
    // move/home after a force-halt actually produces torque instead of silently
    // running the motion state machine against a de-energized driver.
    if (!stepper_drv_current_on[i]) {
        tmc_drivers[i].enableDriver(true);
        stepper_drv_current_on[i] = true;
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

    char led_gpios_buf[64];
    int led_len = snprintf(led_gpios_buf, sizeof(led_gpios_buf), "[");
    for (int i = 0; i < LED_OUTPUT_COUNT && led_len > 0; i++) {
        led_len += snprintf(led_gpios_buf + led_len, sizeof(led_gpios_buf) - led_len,
                            "%s%d", i == 0 ? "" : ",", digital_output_pins[i]);
    }
    snprintf(led_gpios_buf + led_len, sizeof(led_gpios_buf) - led_len, "]");

    // Armed channels only (the payload is capped at MAX_PAYLOAD_SIZE): c=channel,
    // l=latches, t/s=last TSTEP/SG_RESULT, g=last early-return reason
    char soft_sg_buf[200];
    int sg_len = snprintf(soft_sg_buf, sizeof(soft_sg_buf), "[");
    bool first = true;
    for (int i = 0; i < STEPPER_COUNT && sg_len > 0 && (size_t)sg_len < sizeof(soft_sg_buf); i++) {
        if (!steppers[i].stallDetectionEnabled()) continue;
        sg_len += snprintf(soft_sg_buf + sg_len, sizeof(soft_sg_buf) - sg_len,
                           "%s{\"c\":%d,\"l\":%u,\"t\":%lu,\"s\":%lu,\"g\":%u}",
                           first ? "" : ",", i,
                           (unsigned)soft_sg_latches[i], (unsigned long)soft_sg_last_tstep[i],
                           (unsigned long)soft_sg_last_sg[i], (unsigned)soft_sg_gate[i]);
        first = false;
    }
    if (sg_len > 0 && (size_t)sg_len < sizeof(soft_sg_buf) - 1) {
        snprintf(soft_sg_buf + sg_len, sizeof(soft_sg_buf) - sg_len, "]");
    } else {
        snprintf(soft_sg_buf, sizeof(soft_sg_buf), "[]");
    }

    // enc: c=channel, st=AS5600 STATUS (0x20 magnet ok, 0x10 weak, 0x08 strong;
    // 0 = never read, i.e. no sensor answering), agc, dev=last deviation in
    // counts, l=latches. Worst case with two armed soft_sg channels stays
    // under MAX_PAYLOAD_SIZE (measured 237 of 246 bytes).
    char enc_buf[64] = "null";
    if (enc_channel >= 0) {
        const EncoderCheck &e = enc[enc_channel];
        snprintf(enc_buf, sizeof(enc_buf), "{\"c\":%d,\"st\":%u,\"agc\":%u,\"dev\":%ld,\"l\":%u}",
                 (int)enc_channel, (unsigned)e.status, (unsigned)e.agc, (long)e.deviation,
                 (unsigned)e.latches);
    }

    int n_bytes = snprintf(
        buf,
        buf_size,
        "{\"hw\":\"%s\",\"diag_pins\":%s,\"led_gpios\":%s,\"soft_sg\":%s,\"enc\":%s}",
        HW_ID,
        diag_pins_len > 0 ? diag_pins_buf : "[]",
        led_gpios_buf,
        soft_sg_buf,
        enc_buf);

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
        stepper_drv_current_on[i] = true;
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
    // Initialize digital outputs. gpio_init routes the pad back to SIO, so any
    // channel that was driving PWM is no longer in PWM mode — clear the flag to
    // match, or the next duty write skips re-arming the pad and silently does
    // nothing. INIT arrives on every host start, so a host restart without a
    // board reset used to leave the LEDs dark and unlightable.
    for (int i = 0; i < DIGITAL_OUTPUT_COUNT; i++) {
        gpio_init(digital_output_pins[i]);
        gpio_set_dir(digital_output_pins[i], GPIO_OUT);
        gpio_put(digital_output_pins[i], 0);
        digital_output_pwm_active[i] = false;
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

// Counter wraps at 65534, so it takes 65535 values (0..65534) and a duty of
// 65535 is genuinely always-high rather than 65535/65536 of the time. Duty 0 is
// likewise always-low, so the full u16 range maps to real 0%..100%.
static const uint16_t PWM_OUTPUT_WRAP = 65534;

static bool pwm_slice_configured[NUM_PWM_SLICES];

static void digital_output_set_plain(int pin, uint8_t channel, bool value) {
    if (digital_output_pwm_active[channel]) {
        // Hand the pad back to SIO. Never disable the slice: on some boards two
        // outputs share one slice, and disabling it would freeze the other pin.
        gpio_set_function(pin, GPIO_FUNC_SIO);
        gpio_set_dir(pin, GPIO_OUT);
        digital_output_pwm_active[channel] = false;
    }
    gpio_put(pin, value ? 1 : 0);
}

void CMDH_digital_write(const BusMessage *msg, BusMessage *resp) {
    int pin = digital_output_pins[msg->channel];
    bool value = msg->payload[0] != 0;
    digital_output_set_plain(pin, msg->channel, value);
    resp->payload_length = 0;
}

void CMDH_digital_write_pwm(const BusMessage *msg, BusMessage *resp) {
    uint16_t duty;
    memcpy(&duty, msg->payload, sizeof(duty));
    int pin = digital_output_pins[msg->channel];

    uint slice = pwm_gpio_to_slice_num(pin);
    if (!pwm_slice_configured[slice]) {
        pwm_config config = pwm_get_default_config();
        pwm_config_set_wrap(&config, PWM_OUTPUT_WRAP);
        pwm_init(slice, &config, false);
        pwm_slice_configured[slice] = true;
    }
    pwm_set_chan_level(slice, pwm_gpio_to_channel(pin), duty);
    pwm_set_enabled(slice, true);
    if (!digital_output_pwm_active[msg->channel]) {
        gpio_set_function(pin, GPIO_FUNC_PWM);
        digital_output_pwm_active[msg->channel] = true;
    }
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
    if (enabled) {
        // ensure_stepper_hw_enabled re-asserts the chopper (and tracks it), so
        // don't write enableDriver(true) twice.
        ensure_stepper_hw_enabled(msg->channel);
    } else {
        tmc_drivers[msg->channel].enableDriver(false);
        stepper_drv_current_on[msg->channel] = false;
    }
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
    if (reg == TMC_REG_SGTHRS) soft_sg_sgthrs[msg->channel] = value;
    if (reg == TMC_REG_TCOOLTHRS) soft_sg_tcoolthrs[msg->channel] = value;
}

void CMDH_stepper_enable_stall_detection(const BusMessage *msg, BusMessage *resp) {
    bool enable = msg->payload[0] != 0;
    // Without a DIAG pin the software poll (core0, UART) takes over; it needs
    // SGTHRS/TCOOLTHRS to have been written first, which the backend does.
    soft_sg_hits[msg->channel] = 0;
    steppers[msg->channel].enableStallDetection(enable);
    resp->payload_length = 0;
}

void CMDH_stepper_encoder_config(const BusMessage *msg, BusMessage *resp) {
    EncoderCheck &e = enc[msg->channel];
    int8_t sign = (int8_t)msg->payload[0];
    uint32_t counts_per_kusteps;
    uint16_t tolerance;
    memcpy(&counts_per_kusteps, msg->payload + 1, sizeof(counts_per_kusteps));
    memcpy(&tolerance, msg->payload + 5, sizeof(tolerance));
    bool enable = msg->payload[7] != 0;
    if (enable && (counts_per_kusteps == 0 || tolerance == 0 || (sign != 1 && sign != -1))) {
        resp->command = msg->command | 0x80;
        resp->payload_length = snprintf((char *)resp->payload, MAX_PAYLOAD_SIZE, "Invalid encoder config");
        return;
    }
    for (int i = 0; i < STEPPER_COUNT; i++) enc[i].enabled = false; // one encoder per board
    e.sign = sign;
    e.counts_per_kusteps = counts_per_kusteps;
    e.tolerance_counts = tolerance;
    e.synced = false;
    e.hits = 0;
    e.enabled = enable;
    enc_channel = enable ? (int8_t)msg->channel : -1;
    resp->payload_length = 0;
}

void CMDH_stepper_encoder_status(const BusMessage *msg, BusMessage *resp) {
    const EncoderCheck &e = enc[msg->channel];
    uint16_t raw = e.last_raw;
    int32_t deviation = e.deviation;
    memcpy(resp->payload, &raw, 2);
    memcpy(resp->payload + 2, &deviation, 4);
    resp->payload[6] = e.status;
    resp->payload[7] = e.agc;
    memcpy(resp->payload + 8, &e.latches, 2);
    resp->payload_length = 10;
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

static void software_stallguard_poll() {
    static uint64_t next_poll_us = 0;
    static uint8_t next_channel = 0;
    uint64_t now = time_us_64();
    if (now < next_poll_us) return;
    next_poll_us = now + SOFT_SG_POLL_INTERVAL_US;
    uint8_t i = next_channel;
    next_channel = (uint8_t)((next_channel + 1) % STEPPER_COUNT);
    Stepper &stepper = steppers[i];
    if (stepper.hasStallPin()) { soft_sg_gate[i] = 1; soft_sg_hits[i] = 0; return; }
    if (!stepper.stallDetectionEnabled()) { soft_sg_gate[i] = 2; soft_sg_hits[i] = 0; return; }
    if (soft_sg_sgthrs[i] == 0) { soft_sg_gate[i] = 3; soft_sg_hits[i] = 0; return; }
    if (!stepper.isCruisingForStallCheck()) {
        soft_sg_gate[i] = 4;
        soft_sg_hits[i] = 0;
        soft_sg_read_sg_next[i] = false;
        return;
    }
    // Gate codes 5x/7x carry the UART result: x1 = timeout, x2 = CRC error.
    if (!soft_sg_read_sg_next[i]) {
        uint32_t tstep = 0;
        int rc = tmc_drivers[i].readRegister(TMC_REG_TSTEP, &tstep);
        if (rc != 0) { soft_sg_gate[i] = (uint8_t)(50 - rc); return; }
        soft_sg_last_tstep[i] = tstep & 0xFFFFF;
        if ((tstep & 0xFFFFF) > soft_sg_tcoolthrs[i]) {
            soft_sg_gate[i] = 6; // below the velocity floor DIAG would be inactive too
            soft_sg_hits[i] = 0;
            return;
        }
        soft_sg_read_sg_next[i] = true;
        return;
    }
    soft_sg_read_sg_next[i] = false;
    uint32_t sg_result = 0;
    int rc = tmc_drivers[i].readRegister(TMC_REG_SG_RESULT, &sg_result);
    if (rc != 0) { soft_sg_gate[i] = (uint8_t)(70 - rc); return; }
    soft_sg_last_sg[i] = sg_result & 0x3FF;
    soft_sg_gate[i] = 0;
    if ((sg_result & 0x3FF) <= 2 * soft_sg_sgthrs[i]) {
        if (++soft_sg_hits[i] >= SOFT_SG_HITS_TO_LATCH) {
            soft_sg_hits[i] = 0;
            soft_sg_latches[i]++;
            stepper.latchStall();
        }
    } else {
        soft_sg_hits[i] = 0;
    }
}

static void encoder_position_poll() {
    static uint64_t next_poll_us = 0;
    static uint32_t polls = 0;
    if (enc_channel < 0) return;
    uint64_t now = time_us_64();
    if (now < next_poll_us) return;
    next_poll_us = now + ENC_POLL_INTERVAL_US;
    EncoderCheck &e = enc[enc_channel];
    Stepper &stepper = steppers[enc_channel];
    polls++;
    uint16_t raw = 0;
    if (!shaft_encoder.readRawAngle(&raw)) {
        if (e.i2c_errors < 255) e.i2c_errors++;
        return;
    }
    if ((polls % ENC_STATUS_EVERY_N_POLLS) == 0) {
        shaft_encoder.readStatus(&e.status);
        shaft_encoder.readAgc(&e.agc);
    }
    int32_t position = stepper.getPosition();
    if (!e.synced) {
        e.last_raw = raw;
        e.unwrapped = raw;
        e.last_position = position;
        e.offset = e.unwrapped - (int32_t)(((int64_t)e.sign * position * (int64_t)e.counts_per_kusteps) / 1000);
        e.deviation = 0;
        e.hits = 0;
        e.synced = true;
        return;
    }
    int32_t delta = (int32_t)raw - (int32_t)e.last_raw;
    if (delta > (int32_t)AS5600::COUNTS_PER_REV / 2) delta -= AS5600::COUNTS_PER_REV;
    if (delta < -(int32_t)AS5600::COUNTS_PER_REV / 2) delta += AS5600::COUNTS_PER_REV;
    e.unwrapped += delta;
    e.last_raw = raw;
    int32_t moved = position - e.last_position;
    e.last_position = position;
    if (moved > ENC_RESET_JUMP_USTEPS || moved < -ENC_RESET_JUMP_USTEPS) {
        // The counter was set from outside (homing, SET_POSITION): re-sync.
        e.synced = false;
        return;
    }
    if (stepper.isJittering()) { e.hits = 0; return; }
    e.deviation = e.unwrapped - enc_expected_counts(e, position);
    int32_t magnitude = e.deviation < 0 ? -e.deviation : e.deviation;
    if (magnitude > (int32_t)e.tolerance_counts) {
        if (++e.hits >= ENC_HITS_TO_LATCH) {
            e.hits = 0;
            e.latches++;
            stepper.latchStall();
            e.synced = false; // measure the next move from wherever the shaft really is
        }
    } else {
        e.hits = 0;
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
        software_stallguard_poll();
        encoder_position_poll();
    }
}
