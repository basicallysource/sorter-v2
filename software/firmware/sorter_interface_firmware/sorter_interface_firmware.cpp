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

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/timer.h"

#include "Stepper.h"
#include "TMC_UART.h"
#include "TMC2209.h"

// Break this off into a separate module later (communications)

#include "cobs.h"


/** \brief Calculate CRC-32 of a given data buffer
 * 
 * \param data Pointer to the data buffer
 * \param length Length of the data buffer in bytes
 * \return Calculated CRC-32 value
 */
uint32_t crc32(const void *data, size_t length) {
    uint32_t crc = 0xFFFFFFFF; // Initialize with -1

    for (size_t i = 0; i < length; i++) {
        crc ^= ((const uint8_t *)data)[i];
        for (int j = 0; j < 8; j++) {
            // If the LSB is set, shift and XOR with polynomial
            if (crc & 1) {
                crc = (crc >> 1) ^ 0xEDB88320;
            } else {
                crc >>= 1;
            }
        }
    }
    // Invert the final CRC value
    return ~crc;
}

struct Message {
    uint8_t dev_address; // Device address, ignored on USB connections
    uint8_t command; // Command code (from 0 to 127, high bit is used to signal exceptions)
    uint8_t channel; // Channel or motor number
    uint8_t payload_length; // Length of payload in bytes
    uint8_t payload[]; // Payload data
};

enum CommandCodes {
    // Common Commands
    CMD_INIT = 0x01,
    CMD_PING = 0x02,
    // Stepper Commands
    CMD_STEPPER_MOVE_STEPS = 0x10,
    CMD_STEPPER_MOVE_AT_SPEED = 0x11,
    CMD_STEPPER_SET_SPEED_LIMITS = 0x12,
    CMD_STEPPER_SET_ACCELERATION = 0x13,
    CMD_STEPPER_IS_STOPPED = 0x14,
    CMD_STEPPER_GET_POSITION = 0x15,
    CMD_STEPPER_SET_POSITION = 0x16,
    CMD_STEPPER_HOME = 0x17,
    // Stepper driver commands
    CMD_STEPPER_DRV_SET_ENABLED = 0x20,
    CMD_STEPPER_DRV_SET_MICROSTEPS = 0x21,
    CMD_STEPPER_DRV_SET_CURRENT = 0x22,
    CMD_STEPPER_DRV_READ_REGISTER = 0x2e,
    CMD_STEPPER_DRV_WRITE_REGISTER = 0x2f,
    // Digital I/O Commands
    CMD_DIGITAL_READ = 0x30,
    CMD_DIGITAL_WRITE = 0x31,
    // Servo Commands
    CMD_SERVO_SET_ENABLED = 0x40,
    CMD_SERVO_MOVE_TO = 0x41,
    CMD_SERVO_SET_SPEED_LIMITS = 0x42,
    CMD_SERVO_SET_ACCELERATION = 0x43,

    CMD_BAD_COMMAND = 0xFF
};


// End break

//#define MAIN_TRACE_ENABLED

#ifdef MAIN_TRACE_ENABLED
#define TRACE_PIN 8
#define TRACE_INIT() gpio_init(TRACE_PIN); gpio_set_dir(TRACE_PIN, GPIO_OUT);
#define TRACE_HIGH() gpio_put(TRACE_PIN, 1)
#define TRACE_LOW() gpio_put(TRACE_PIN, 0)
#else
#define TRACE_INIT()
#define TRACE_HIGH()
#define TRACE_LOW()
#endif

// Board configuration
// This needs to be unique for each board and should be loaded from a config file or something in the future, but hardcoded for now.

char DEVICE_NAME[16] = "FEEDER MB";
uint8_t DEVICE_ADDRESS = 0x00;

const uint8_t STEPPER_COUNT = 4;

TMC_UART_Bus tmc_bus(uart0);
TMC2209 tmc_drivers[] = {
    TMC2209(&tmc_bus, 0),
    TMC2209(&tmc_bus, 1),
    TMC2209(&tmc_bus, 2),
    TMC2209(&tmc_bus, 3)
};
Stepper steppers[] = {
    Stepper(28, 27),
    Stepper(26, 25),
    Stepper(21, 20),
    Stepper(19, 18)
};

const int TMC_UART_TX_PIN = 16;
const int TMC_UART_RX_PIN = 17;
const int TMC_UART_BAUDRATE = 400000;

const int STEPPER_nEN_PIN = 0;

const uint8_t DIGITAL_INPUT_COUNT = 4;
const int digital_input_pins[] = {9, 8, 13, 12};

const uint8_t DIGITAL_OUTPUT_COUNT = 2;
const int digital_output_pins[] = {14, 15};

const int I2C_SDA_PIN = 10;
const int I2C_SCL_PIN = 11;

const uint8_t SERVO_COUNT = 0;

// End board configuration

/**
 * \brief Dump the board configuration as a JSON string for use by the driver software.
 * This is used for auto-detecting the board and its capabilities.
 * 
 * \param buf Buffer to write the json string to
 * \param buf_size Size of the buffer in bytes
 * \return Number of bytes written to the buffer, excluding the null terminator
 */
int dump_configuration(char * buf, size_t buf_size) {
    int n_bytes;
    n_bytes = snprintf(
        buf,
        buf_size,
        "{\"firmware_version\":\"1.0\",\"device_name\":\"%s\",\"device_address\":%d,"
        "\"stepper_count\":%d,\"digital_input_count\":%d,\"digital_output_count\":%d,"
        "\"servo_count\":%d}",
        DEVICE_NAME,
        DEVICE_ADDRESS,
        STEPPER_COUNT,
        DIGITAL_INPUT_COUNT,
        DIGITAL_OUTPUT_COUNT,
        SERVO_COUNT);
    return n_bytes;
}


const uint32_t STEP_TICK_PERIOD_US = 1000000 / STEP_TICK_RATE_HZ;
const uint32_t MOTION_UPDATE_PERIOD_US = 1000000 / STEP_MOTION_UPDATE_RATE_HZ;

void core1_stepgen_isr(uint alarm_num ) {
    TRACE_HIGH();
    // Core 1 step generator interrupt service routine, called at STEP_TICK_RATE_HZ
    hardware_alarm_set_target(alarm_num, time_us_64() + STEP_TICK_PERIOD_US);
    
    for (int i = 0; i < STEPPER_COUNT; i++) {
        steppers[i].stepgen_tick();
    }
    TRACE_LOW();
}

void core1_motion_update_isr(uint alarm_num ) {
    TRACE_HIGH();
    // Core 1 motion update interrupt service routine, called at STEP_MOTION_UPDATE_RATE_HZ
    hardware_alarm_set_target(alarm_num, time_us_64() + MOTION_UPDATE_PERIOD_US);
    
    for (int i = 0; i < STEPPER_COUNT; i++) {
        steppers[i].motion_update_tick();
    }
    TRACE_LOW();
}

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

    while (true) {
        // Core 1 main loop does nothing, all work is done in interrupts
        tight_loop_contents();
    }
}


void initialize_hardware() {
    // Initialize TMC UART bus
    tmc_bus.setupComm(TMC_UART_BAUDRATE, TMC_UART_TX_PIN, TMC_UART_RX_PIN);
    // Initialize TMC2209 drivers and steppers
    for (int i = 0; i < STEPPER_COUNT; i++) {
        //tmc_drivers[i].enableDriver(true);
        steppers[i].initialize();
        steppers[i].setAcceleration(20000);
        steppers[i].setSpeedLimits(16, 4000);
        tmc_drivers[i].initialize();
        tmc_drivers[i].enableDriver(true);
        tmc_drivers[i].setCurrent(31, 16, 10);
        tmc_drivers[i].setMicrosteps(MICROSTEP_8);
        tmc_drivers[i].enableStealthChop(true); 
    }
    // Global enable for stepper drivers
    gpio_init(STEPPER_nEN_PIN);
    gpio_set_dir(STEPPER_nEN_PIN, GPIO_OUT);
    gpio_put(STEPPER_nEN_PIN, 0); // Enable stepper drivers
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
}


int main()
{
    stdio_init_all();
    initialize_hardware();
    // Initialize Core 1
    multicore_launch_core1(core1_entry);

    // Communication buffers
    char rx_buffer[255], tx_buffer[255];
    // Buffers for received and transmitted messages, aligned to 32 bits for easy casting
    alignas(uint32_t) char rx_message[254];
    alignas(uint32_t) char tx_message[254];
    int rx_buffer_pos = 0, msg_len = 0;

    // Main loop, this deals with communications and high level command processing
    while (true) {
        // Check if there is any data coming from USB, append it to the rx_buffer until exhausted or we find a \0. 
        // If we do find a \0, we set msg_len to the length of the message (excluding \0) and process it.
        // If we don't find a \0 and the buffer is full, we mark this as a framing error (msg_len = -1) so we don't process it.
        while (true) {
            int c = stdio_getchar_timeout_us(0);
            if (c == PICO_ERROR_TIMEOUT) {
                // No more data
                break;
            }
            if (c == 0) {
                // End of message
                if (rx_buffer_pos < 8) {
                    // Empty message, ignore (doesn't even fit the CRC and header)
                    msg_len = 0;
                    break;
                }
                int res = COBS_decode((uint8_t*)rx_buffer, rx_buffer_pos, (uint8_t*)rx_message, sizeof(rx_message));
                if (res < 0) { 
                    msg_len = -1; // Framing error
                    rx_buffer_pos = 0;
                    break;
                }
                if (rx_message[0] != DEVICE_ADDRESS) {
                    msg_len = -1; // Not for us, ignore
                    rx_buffer_pos = 0;
                    break;
                }
                msg_len = res;
                uint32_t incoming_crc;
                memcpy(&incoming_crc, rx_message + msg_len - 4, sizeof(incoming_crc));
                uint32_t calc_crc = crc32(rx_message, msg_len-4);
                if (calc_crc != incoming_crc) { 
                    msg_len = -1; // CRC error
                    rx_buffer_pos = 0;
                    break;
                }
                msg_len = msg_len - 4; // Exclude CRC
                rx_buffer_pos = 0; // Prepare to receive again
                break;
            }
            if (rx_buffer_pos < sizeof(rx_buffer)) {
                rx_buffer[rx_buffer_pos++] = (char)c;
            } else {
                // Buffer full, framing error
                msg_len = -1;
                rx_buffer_pos = 0;
                break;
            }
        }
        // If we have a complete message, process it
        if (msg_len > 0) {
            // Process message
            struct Message* msg = (struct Message*)rx_message;
            // Here we would escape if the device address doesnt match, but we ignore it in USB
            // Prepare response message
            struct Message* resp = (struct Message*)tx_message;
            resp->dev_address = msg->dev_address; // We respond to the address
            resp->channel = msg->channel; // We respond on the same channel
            switch (msg->command) {
                case CMD_INIT:
                    resp->command = CMD_INIT;
                    // Stop all steppers
                    for (int i = 0; i < STEPPER_COUNT; i++) {
                        steppers[i].moveAtSpeed(0);
                    }
                    // Turn off all digital outputs
                    for (int i = 0; i < DIGITAL_OUTPUT_COUNT; i++) {
                        gpio_put(digital_output_pins[i], 0);
                    }
                    resp->payload_length = dump_configuration((char*)resp->payload, 246);
                    break;
                case CMD_PING:
                    resp->command = CMD_PING;
                    // Copy payload back
                    resp->payload_length = msg->payload_length;
                    memcpy(resp->payload, msg->payload, msg->payload_length);
                    break;
                case CMD_STEPPER_MOVE_STEPS:
                    if (msg->payload_length == 4 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        int32_t distance = *((int32_t*)msg->payload);
                        resp->command = msg->command;
                        resp->payload_length = 4;
                        bool res = steppers[stepper_id].moveSteps(distance);
                        *((uint32_t*)resp->payload) = res ? 1 : 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_MOVE_AT_SPEED:
                    if (msg->payload_length == 4 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        int32_t speed = *((int32_t*)msg->payload);
                        resp->command = msg->command;
                        resp->payload_length = 4;
                        bool res = steppers[stepper_id].moveAtSpeed(speed);
                        *((uint32_t*)resp->payload) = res ? 1 : 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_SET_SPEED_LIMITS:
                    if (msg->payload_length == 8 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        uint32_t min_speed = *((uint32_t*)msg->payload);
                        uint32_t max_speed = *((uint32_t*)(msg->payload + 4));
                        steppers[stepper_id].setSpeedLimits(min_speed, max_speed);
                        resp->command = msg->command;
                        resp->payload_length = 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_SET_ACCELERATION:
                    if (msg->payload_length == 4 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        uint32_t acceleration = *((uint32_t*)msg->payload);
                        steppers[stepper_id].setAcceleration(acceleration);
                        resp->command = msg->command;
                        resp->payload_length = 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_IS_STOPPED:
                    if (msg->payload_length == 0 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        resp->command = msg->command;
                        resp->payload_length = 4;
                        bool res = steppers[stepper_id].isStopped();
                        *((uint32_t*)resp->payload) = res ? 1 : 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_GET_POSITION:
                    if (msg->payload_length == 0 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        resp->command = msg->command;
                        resp->payload_length = 4;
                        int32_t position = steppers[stepper_id].getPosition();
                        *((int32_t*)resp->payload) = position;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_SET_POSITION:
                    if (msg->payload_length == 4 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        int32_t position = *((int32_t*)msg->payload);
                        steppers[stepper_id].setPosition(position);
                        resp->command = msg->command;
                        resp->payload_length = 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_HOME:
                    if (msg->payload_length == 12 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        int32_t home_speed = *((int32_t*)msg->payload);
                        int home_pin = *((int32_t*)(msg->payload + 4));
                        bool home_pin_polarity = msg->payload[8] != 0;
                        // Convert homing pin from channel number to actual GPIO pin
                        if (home_pin >= DIGITAL_INPUT_COUNT) {
                            resp->command = msg->command | 0x80; // Exception, bad arguments
                            resp->payload_length = 0;
                            break;
                        }
                        home_pin = digital_input_pins[home_pin];
                        steppers[stepper_id].home(home_speed, home_pin, home_pin_polarity);
                        resp->command = msg->command;
                        resp->payload_length = 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_DRV_SET_ENABLED:
                   if (msg->payload_length == 4 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        bool enabled = *((uint32_t*)msg->payload) != 0;
                        tmc_drivers[stepper_id].enableDriver(enabled);
                        resp->command = msg->command;
                        resp->payload_length = 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_DRV_SET_MICROSTEPS:
                    if (msg->payload_length == 4 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        uint32_t microsteps = *((uint32_t*)msg->payload);
                        switch (microsteps) {
                            case 1: tmc_drivers[stepper_id].setMicrosteps(MICROSTEP_FULL); break;
                            case 2: tmc_drivers[stepper_id].setMicrosteps(MICROSTEP_2); break;
                            case 4: tmc_drivers[stepper_id].setMicrosteps(MICROSTEP_4); break;
                            case 8: tmc_drivers[stepper_id].setMicrosteps(MICROSTEP_8); break;
                            case 16: tmc_drivers[stepper_id].setMicrosteps(MICROSTEP_16); break;
                            case 32: tmc_drivers[stepper_id].setMicrosteps(MICROSTEP_32); break;
                            default:
                                resp->command = msg->command | 0x80; // Exception, bad arguments
                                resp->payload_length = 0;
                                continue;
                        }
                        resp->command = msg->command;
                        resp->payload_length = 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_DRV_SET_CURRENT:
                    if (msg->payload_length == 12 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        uint32_t run_current = *((uint32_t*)msg->payload);
                        uint32_t hold_current = *((uint32_t*)(msg->payload + 4));
                        uint32_t hold_delay = *((uint32_t*)(msg->payload + 8));
                        tmc_drivers[stepper_id].setCurrent(run_current, hold_current, hold_delay);
                        resp->command = msg->command;
                        resp->payload_length = 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_DRV_READ_REGISTER:
                    if (msg->payload_length == 4 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        uint32_t reg_addr = *((uint32_t*)msg->payload);
                        uint32_t reg_value;
                        int res = tmc_drivers[stepper_id].readRegister(reg_addr, &reg_value);
                        resp->command = msg->command;
                        if (res < 0) {
                            resp->command |= 0x80; // Exception, read error
                            resp->payload_length = 0;
                        } else {
                            resp->payload_length = 4;
                            *((uint32_t*)resp->payload) = reg_value;
                        }
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_STEPPER_DRV_WRITE_REGISTER:
                    if (msg->payload_length == 8 && msg->channel < STEPPER_COUNT) {
                        uint8_t stepper_id = msg->channel;
                        uint32_t reg_addr = *((uint32_t*)msg->payload);
                        uint32_t reg_value = *((uint32_t*)(msg->payload + 4));
                        tmc_drivers[stepper_id].writeRegister(reg_addr, reg_value);
                        resp->command = msg->command;
                        resp->payload_length = 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_DIGITAL_READ:
                    if (msg->payload_length == 0 && msg->channel < DIGITAL_INPUT_COUNT) {
                        uint8_t input_id = msg->channel;
                        int pin = digital_input_pins[input_id];
                        bool value = gpio_get(pin) != 0;
                        resp->command = msg->command;
                        resp->payload_length = 4;
                        *((uint32_t*)resp->payload) = value ? 1 : 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                case CMD_DIGITAL_WRITE:
                    if (msg->payload_length == 4 && msg->channel < DIGITAL_OUTPUT_COUNT) {
                        uint8_t output_id = msg->channel;
                        bool value = *((uint32_t*)msg->payload) != 0;
                        int pin = digital_output_pins[output_id];
                        gpio_put(pin, value ? 1 : 0);
                        resp->command = msg->command;
                        resp->payload_length = 0;
                    } else {
                        resp->command = msg->command | 0x80; // Exception, bad arguments
                        resp->payload_length = 0;
                    }
                    break;
                default:
                    resp->command = CMD_BAD_COMMAND; // Exception, bad command
                    resp->payload_length = 0;
                    break;
            }
            // Calculate total response length
            int resp_len = 4 + resp->payload_length; // Header + payload
            // Append CRC
            uint32_t crc = crc32(tx_message, resp_len);
            memcpy(tx_message + resp_len, &crc, sizeof(crc));
            resp_len += sizeof(crc);
            // COBS encode response in place
            int enc_len = COBS_encode((uint8_t*)tx_message, resp_len, (uint8_t*)tx_buffer, sizeof(tx_buffer));
            if (enc_len < 0) {
                // Encoding error, should not happen
                continue;
            }
            stdio_put_string(tx_buffer, enc_len, false, false);
            msg_len = 0; // Message, processed, drop it
        }
    }
}
