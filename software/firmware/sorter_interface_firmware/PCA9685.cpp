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

#include "PCA9685.h"

#define PCA9685_OSC_FREQ 25000000
#define PCA9685_MAX_PWM 4095
#define PCA9685_I2C_TIMEOUT_US 1000 // 1ms timeout for I2C operations

PCA9685::PCA9685(uint8_t i2c_addr, i2c_inst_t *i2c_port) : _i2c_addr(i2c_addr), _i2c_port(i2c_port) {
    _channel_duty.fill(0);
}

/** \brief Detect if the PCA9685 is present on the I2C bus and initialize it
 *
 * This function attempts to write to the MODE1 and MODE2 registers of the PCA9685 to configure it for normal operation.
 * If the device is present and responds to the I2C commands, it will be configured to respond to ALL CALL addresses and
 * use a totem pole structure for the outputs. If any of the I2C operations fail (e.g. due to no response from the
 * device), the function will return false, indicating that the device was not detected.
 *
 * \return true if the device is detected and initialized successfully, false otherwise
 */
bool PCA9685::initialize() {
    uint8_t mode1 = PCA_MODE1_ALLCALL; // Respond to I2C ALL CALL
    mode1 |= PCA_MODE1_AI;             // Enable auto-increment
    int res;
    res =
        i2c_write_timeout_us(_i2c_port, _i2c_addr, (uint8_t[]){PCA_REG_MODE1, mode1}, 2, false, PCA9685_I2C_TIMEOUT_US);
    if (res < 0)
        return false;
    uint8_t mode2 = PCA_MODE2_OUTDRV; // Totem pole structure
    res =
        i2c_write_timeout_us(_i2c_port, _i2c_addr, (uint8_t[]){PCA_REG_MODE2, mode2}, 2, false, PCA9685_I2C_TIMEOUT_US);
    if (res < 0)
        return false;
    // initialize all channels to 0 duty cycle (off)
    uint8_t all_led_off_data[5] = {PCA_REG_ALL_LED_OFF_L, 0, 0, 0, 0}; // off_l=0, off_h=0 means fully off
    res = i2c_write_timeout_us(_i2c_port, _i2c_addr, all_led_off_data, 5, false, PCA9685_I2C_TIMEOUT_US);
    if (res < 0)
        return false;
    _channel_duty.fill(0); // Update internal state to match hardware
    return true; // If we got a response, the device is present
}

/** \brief Set the PWM frequency for all channels
 *
 * The PCA9685 has a fixed internal oscillator frequency (25MHz) and a 12-bit resolution for the PWM duty cycle (4096
 * steps). The PWM frequency is determined by the prescaler value, which is calculated using the formula:
 *
 * \f$ prescale = round(\frac{25 \text{MHz}}{4096 \cdot freq}) - 1 \f$
 *
 * \param freq Desired PWM frequency in Hz. Minimum value is approximately 24Hz (prescale=255), maximum value is
 * approximately 1526Hz (prescale=3). Values outside this range will be clamped.
 */
void PCA9685::setPWMFreq(uint16_t freq) {
    // Calculate prescale value using the datasheet formula and fixed point math
    int prescaleval = 10 * PCA9685_OSC_FREQ / ((PCA9685_MAX_PWM + 1) * freq);
    prescaleval = ((prescaleval + 5) / 10); // Round to nearest integer
    prescaleval -= 1;                       // Subtract 1 from the result

    if (prescaleval < 3)
        prescaleval = 3; // Minimum prescale value is 3
    if (prescaleval > 255)
        prescaleval = 255; // Maximum prescale value is 255
    uint8_t prescale = (uint8_t)prescaleval;

    // Put the device to sleep to set the prescaler
    uint8_t oldmode;

    int res = i2c_write_timeout_us(_i2c_port, _i2c_addr, (uint8_t[]){PCA_REG_MODE1}, 1, true,
                                   PCA9685_I2C_TIMEOUT_US); // Write register address
    if (res < 0)
        return;
    res = i2c_read_timeout_us(_i2c_port, _i2c_addr, &oldmode, 1, false, PCA9685_I2C_TIMEOUT_US);
    if (res < 0)
        return;
    uint8_t newmode = (oldmode & 0x7F) | PCA_MODE1_SLEEP; // Sleep
    res = i2c_write_timeout_us(_i2c_port, _i2c_addr, (uint8_t[]){PCA_REG_MODE1, newmode}, 2, false,
                               PCA9685_I2C_TIMEOUT_US);
    if (res < 0)
        return;

    // Set the prescaler
    res = i2c_write_timeout_us(_i2c_port, _i2c_addr, (uint8_t[]){PCA_REG_PRE_SCALE, prescale}, 2, false,
                               PCA9685_I2C_TIMEOUT_US);
    if (res < 0)
        return;

    // Wake up the device
    res = i2c_write_timeout_us(_i2c_port, _i2c_addr, (uint8_t[]){PCA_REG_MODE1, oldmode}, 2, false,
                               PCA9685_I2C_TIMEOUT_US);
    if (res < 0)
        return;
}

/** \brief Set the PWM duty cycle for a specific channel
 *
 * The PCA9685 uses a 12-bit value to represent the duty cycle, where 0 means always off and 4095 means always on. The
 * duty cycle is set by specifying the count at which the signal turns on and off within the 4096-count PWM period. In
 * this implementation, we always start the signal at count 0 (on_l=0, on_h=0) and set the off count based on the
 * desired duty cycle.
 *
 * \param channel PWM channel number (0-15)
 * \param duty Desired duty cycle (0-4095). Values outside this range will be clamped.
 */
void PCA9685::setPWM(uint8_t channel, uint16_t duty) {
    if (channel > 15)
        return; // Invalid channel
    if (duty > PCA9685_MAX_PWM)
        duty = PCA9685_MAX_PWM; // Clamp duty cycle to max

    // Check if the duty cycle has changed to minimize I2C writes
    if (_channel_duty[channel] == duty)
        return; // No change, skip I2C write

    _channel_duty[channel] = duty;

    uint8_t on_l = 0; // Always start at count 0
    uint8_t on_h = 0;
    uint8_t off_l = duty & 0xFF;
    uint8_t off_h = (duty >> 8) & 0x0F;

    uint8_t reg_base = PCA_REG_LED0_ON_L + 4 * channel;
    int res = i2c_write_timeout_us(_i2c_port, _i2c_addr, (uint8_t[]){reg_base, on_l, on_h, off_l, off_h}, 5, false,
                                   PCA9685_I2C_TIMEOUT_US);
    (void)res; // Optionally handle error
}