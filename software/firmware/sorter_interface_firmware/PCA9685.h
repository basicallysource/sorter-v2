/*
 * Sorter Interface Firmware - PCA9685 PWM Driver
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

#include "hardware/i2c.h"
#include <array>
#include <cstdint>

#ifndef PCA9685_H
#define PCA9685_H

enum PCA9685Register {
    PCA_REG_MODE1 = 0x00,
    PCA_REG_MODE2 = 0x01,
    PCA_REG_SUBADR1 = 0x02,
    PCA_REG_SUBADR2 = 0x03,
    PCA_REG_SUBADR3 = 0x04,
    PCA_REG_ALLCALLADR = 0x05,
    PCA_REG_LED0_ON_L = 0x06,
    PCA_REG_LED0_ON_H = 0x07,
    PCA_REG_LED0_OFF_L = 0x08,
    PCA_REG_LED0_OFF_H = 0x09,
    PCA_REG_ALL_LED_ON_L = 0xFA,
    PCA_REG_ALL_LED_ON_H = 0xFB,
    PCA_REG_ALL_LED_OFF_L = 0xFC,
    PCA_REG_ALL_LED_OFF_H = 0xFD,
    PCA_REG_PRE_SCALE = 0xFE,
};

enum PCA9685Mode1Bits {
    PCA_MODE1_RESTART = 0x80,
    PCA_MODE1_EXTCLK = 0x40,
    PCA_MODE1_AI = 0x20,
    PCA_MODE1_SLEEP = 0x10,
    PCA_MODE1_SUB1 = 0x08,
    PCA_MODE1_SUB2 = 0x04,
    PCA_MODE1_SUB3 = 0x02,
    PCA_MODE1_ALLCALL = 0x01,
};

enum PCA9685Mode2Bits {
    PCA_MODE2_INVRT = 0x10,
    PCA_MODE2_OCH = 0x08,
    PCA_MODE2_OUTDRV = 0x04,
    PCA_MODE2_OUTNE1 = 0x02,
    PCA_MODE2_OUTNE0 = 0x01,
};

class PCA9685 {
  public:
    PCA9685(uint8_t i2c_addr, i2c_inst_t *i2c_port);
    bool initialize();
    void setPWMFreq(uint16_t freq);
    void setPWM(uint8_t channel, uint16_t duty);

  private:
    uint8_t _i2c_addr;
    i2c_inst_t *_i2c_port;
    std::array<uint16_t, 16> _channel_duty; // Store duty cycle for each channel to minimize I2C writes
};

#endif // PCA9685_H