/*
 * Sorter Interface Firmware - Serial Servo Bus Implementation
 * Copyright (C) 2026 sorter-v2 contributors
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

#include "ServoBus.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "pico/time.h"
#include "servo_bus.pio.h"
#include <string.h>

// A missing servo costs this wait and no more. It is longer than the slowest
// return delay a servo can be set to (254 x 2 us).
static const uint32_t REPLY_TIMEOUT_US = 2000;
static const uint32_t SLACK_US = 200;

static const size_t PACKET_OVERHEAD = 6; // FF FF ID LEN INSTR/STATUS CHECKSUM
static const size_t MAX_PARAMS = 1 + SERVO_BUS_MAX_DATA; // A write's address and data

static inline bool time_reached(uint32_t deadline_us) { return (int32_t)(time_us_32() - deadline_us) >= 0; }

ServoBus::ServoBus(PIO pio, uint pin) : _pio(pio), _pin(pin) {}

/*! \brief Set up the bus, or return it to a known state if it is already running
 *
 *  \param baudrate Bus speed in bits per second.
 */
void ServoBus::setupComm(long baudrate) {
    if (!_claimed) {
        _tx_sm = (uint)pio_claim_unused_sm(_pio, true);
        _rx_sm = (uint)pio_claim_unused_sm(_pio, true);
        _tx_offset = (uint)pio_add_program(_pio, &servo_bus_tx_program);
        _rx_offset = (uint)pio_add_program(_pio, &servo_bus_rx_program);
        _claimed = true;
    }
    _clkdiv = (float)clock_get_hz(clk_sys) / (float)(8 * baudrate);
    _byte_time_us = 10000000 / baudrate;
    // Direction and value are set before the pad goes to PIO, so it never drives high.
    stop();
    pio_gpio_init(_pio, _pin);
    gpio_pull_up(_pin);
    gpio_set_drive_strength(_pin, GPIO_DRIVE_STRENGTH_12MA);
    start();
}

/*! \brief Stop both state machines and let go of the line
 *
 *  A PIO pin keeps its direction when its state machine stops, so this releases
 *  it explicitly. The output value is written here and never again: from now on
 *  only the direction changes, which is all that makes the pin open drain.
 */
void ServoBus::stop() {
    const uint32_t pin_mask = 1u << _pin;
    pio_sm_set_enabled(_pio, _tx_sm, false);
    pio_sm_set_enabled(_pio, _rx_sm, false);
    pio_sm_set_pindirs_with_mask(_pio, _tx_sm, 0, pin_mask);
    pio_sm_set_pins_with_mask(_pio, _tx_sm, 0, pin_mask);
}

void ServoBus::start() {
    pio_sm_config tx = servo_bus_tx_program_get_default_config(_tx_offset);
    sm_config_set_out_pins(&tx, _pin, 1);
    sm_config_set_sideset_pins(&tx, _pin);
    sm_config_set_out_shift(&tx, true, false, 32);
    sm_config_set_clkdiv(&tx, _clkdiv);
    pio_sm_init(_pio, _tx_sm, _tx_offset, &tx);

    pio_sm_config rx = servo_bus_rx_program_get_default_config(_rx_offset);
    sm_config_set_in_pins(&rx, _pin);
    sm_config_set_jmp_pin(&rx, _pin);
    sm_config_set_in_shift(&rx, true, false, 32);
    sm_config_set_fifo_join(&rx, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv(&rx, _clkdiv);
    pio_sm_init(_pio, _rx_sm, _rx_offset, &rx);

    pio_sm_set_enabled(_pio, _rx_sm, true);
    pio_sm_set_enabled(_pio, _tx_sm, true);
}

/*! \brief Send a packet and consume its echo
 *
 *  The receiver hears everything sent, so each byte must come back as sent. One
 *  that does not, or does not arrive in time, means the bus is stuck or someone
 *  else is talking: the packet is abandoned and the line released, and nothing
 *  of it reaches the reply parser.
 *
 *  \return true if the whole packet went out.
 */
bool ServoBus::send(const uint8_t *packet, size_t length) {
    // Anything waiting now is stale: a late reply or noise.
    while (!pio_sm_is_rx_fifo_empty(_pio, _rx_sm)) {
        (void)pio_sm_get(_pio, _rx_sm);
    }
    const uint32_t deadline_us = time_us_32() + (uint32_t)length * 2 * _byte_time_us + SLACK_US;
    size_t sent = 0;
    size_t echoed = 0;
    while (echoed < length) {
        if (sent < length && !pio_sm_is_tx_fifo_full(_pio, _tx_sm)) {
            pio_sm_put(_pio, _tx_sm, (uint8_t)~packet[sent++]);
        }
        const bool got_echo = !pio_sm_is_rx_fifo_empty(_pio, _rx_sm);
        if (got_echo ? (uint8_t)(pio_sm_get(_pio, _rx_sm) >> 24) != packet[echoed] : time_reached(deadline_us)) {
            stop();
            start();
            return false;
        }
        if (got_echo) {
            echoed++;
        }
    }
    return true;
}

bool ServoBus::readByte(uint8_t *byte, uint32_t deadline_us) {
    while (pio_sm_is_rx_fifo_empty(_pio, _rx_sm)) {
        if (time_reached(deadline_us)) {
            return false;
        }
    }
    *byte = (uint8_t)(pio_sm_get(_pio, _rx_sm) >> 24);
    return true;
}

/*! \brief Read one status packet
 *
 *  \param id The ID asked. A broadcast ping is answered with the servo's own ID.
 *  \param data Where to store the data bytes.
 *  \param data_len Number of data bytes this reply must carry.
 *  \return The servo's status byte, or -1 on no reply or a bad packet.
 */
int ServoBus::receive(uint8_t id, uint8_t *data, size_t data_len) {
    uint8_t byte;
    if (!readByte(&byte, time_us_32() + REPLY_TIMEOUT_US)) {
        return -1;
    }
    // The servo has started: the rest comes at once.
    const uint32_t deadline_us = time_us_32() + (uint32_t)(data_len + PACKET_OVERHEAD) * 2 * _byte_time_us + SLACK_US;

    int header_bytes = byte == 0xFF ? 1 : 0;
    while (header_bytes < 2) {
        if (!readByte(&byte, deadline_us)) {
            return -1;
        }
        header_bytes = byte == 0xFF ? header_bytes + 1 : 0;
    }
    uint8_t reply_id = 0xFF;
    while (reply_id == 0xFF) {
        if (!readByte(&reply_id, deadline_us)) {
            return -1;
        }
    }
    uint8_t reply_len;
    uint8_t status;
    if (!readByte(&reply_len, deadline_us) || reply_len != data_len + 2 || !readByte(&status, deadline_us)) {
        return -1;
    }
    uint8_t sum = reply_id + reply_len + status;
    for (size_t i = 0; i < data_len; i++) {
        if (!readByte(&data[i], deadline_us)) {
            return -1;
        }
        sum += data[i];
    }
    uint8_t checksum;
    if (!readByte(&checksum, deadline_us) || checksum != (uint8_t)~sum) {
        return -1;
    }
    if (reply_id != id && id != SERVO_BUS_BROADCAST_ID) {
        return -1;
    }
    return status;
}

/*! \brief Send one instruction and wait for its answer
 *
 *  A broadcast write gets no answer, so none is awaited and its status is 0.
 *
 *  \param id Servo ID, or SERVO_BUS_BROADCAST_ID.
 *  \param instruction SERVO_BUS_INST_PING, _READ or _WRITE.
 *  \param params Instruction parameters.
 *  \param params_len Number of parameters.
 *  \param data Where to store the data bytes of the answer.
 *  \param data_len Number of data bytes the answer must carry.
 *  \return The servo's status byte, or -1 on no reply or a bad packet.
 */
int ServoBus::transact(uint8_t id, uint8_t instruction, const uint8_t *params, size_t params_len, uint8_t *data,
                       size_t data_len) {
    if (params_len > MAX_PARAMS) {
        return -1;
    }
    uint8_t packet[PACKET_OVERHEAD + MAX_PARAMS];
    size_t length = 0;
    packet[length++] = 0xFF;
    packet[length++] = 0xFF;
    packet[length++] = id;
    packet[length++] = (uint8_t)(params_len + 2);
    packet[length++] = instruction;
    memcpy(packet + length, params, params_len);
    length += params_len;
    uint8_t sum = 0;
    for (size_t i = 2; i < length; i++) {
        sum += packet[i];
    }
    packet[length++] = (uint8_t)~sum;

    if (!send(packet, length)) {
        return -1;
    }
    if (id == SERVO_BUS_BROADCAST_ID && instruction == SERVO_BUS_INST_WRITE) {
        return 0;
    }
    return receive(id, data, data_len);
}
