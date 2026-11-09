/*
 * Sorter Interface Firmware - Serial Servo Wire Interface
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

#ifndef SERVO_WIRE_H
#define SERVO_WIRE_H

#include <stddef.h>
#include <stdint.h>

const uint8_t SERVO_BUS_BROADCAST_ID = 254;
const uint8_t SERVO_BUS_INST_PING = 0x01;
const uint8_t SERVO_BUS_INST_READ = 0x02;
const uint8_t SERVO_BUS_INST_WRITE = 0x03;
const size_t SERVO_BUS_MAX_DATA = 64; // Most data bytes in one read or write

// What transact returns when no good answer came. Silence is a servo that is not
// there. A garbled answer is bytes that are no packet: two servos with one ID
// answering over each other, or noise. A stuck line is one that does not carry what
// the board sends: held low, or shorted.
const int SERVO_BUS_NO_REPLY = -1;
const int SERVO_BUS_GARBLED = -2;
const int SERVO_BUS_STUCK = -3;

/** \brief One instruction to a serial bus servo and its answer.
 *
 * ServoBus is the real one. ServoGuard talks through this, so its logic builds
 * and runs on a desk against a pretend servo.
 */
class ServoWire {
  public:
    /*! \return The servo's status byte, or SERVO_BUS_NO_REPLY, SERVO_BUS_GARBLED
     *          or SERVO_BUS_STUCK. */
    virtual int transact(uint8_t id, uint8_t instruction, const uint8_t *params, size_t params_len, uint8_t *data,
                         size_t data_len) = 0;

  protected:
    ~ServoWire() = default;
};

#endif // SERVO_WIRE_H
