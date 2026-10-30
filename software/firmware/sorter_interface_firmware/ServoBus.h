/*
 * Sorter Interface Firmware - Serial Servo Bus Header
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

#ifndef SERVO_BUS_H
#define SERVO_BUS_H

#include "hardware/pio.h"
#include <stddef.h>
#include <stdint.h>

const uint8_t SERVO_BUS_BROADCAST_ID = 254;
const uint8_t SERVO_BUS_INST_PING = 0x01;
const uint8_t SERVO_BUS_INST_READ = 0x02;
const uint8_t SERVO_BUS_INST_WRITE = 0x03;
const size_t SERVO_BUS_MAX_DATA = 64; // Most data bytes in one read or write

/** \brief Feetech SC protocol over a half-duplex PIO UART on one open-drain pin.
 *
 * Packets are `FF FF ID LEN INSTR PARAMS CHECKSUM`, the checksum being the
 * inverted sum from ID on. A servo answers `FF FF ID LEN STATUS DATA CHECKSUM`.
 */
class ServoBus {
  public:
    ServoBus(PIO pio, uint pin);

    void setupComm(long baudrate = 1000000);

    int transact(uint8_t id, uint8_t instruction, const uint8_t *params, size_t params_len, uint8_t *data,
                 size_t data_len);

  private:
    PIO _pio;
    uint _pin;
    bool _claimed = false;
    uint _tx_sm = 0;
    uint _rx_sm = 0;
    uint _tx_offset = 0;
    uint _rx_offset = 0;
    float _clkdiv = 1.0f;
    uint32_t _byte_time_us = 10;

    void stop();
    void start();
    bool send(const uint8_t *packet, size_t length);
    int receive(uint8_t id, uint8_t *data, size_t data_len);
    bool readByte(uint8_t *byte, uint32_t deadline_us);
};

#endif // SERVO_BUS_H
