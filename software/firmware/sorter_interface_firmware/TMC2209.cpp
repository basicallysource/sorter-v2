/*
 * Sorter Interface Firmware - TMC2209 Driver Implementation
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

#include "TMC2209.h"

TMC2209::TMC2209(class TMC_UART_Bus* bus, uint8_t address, uint32_t rsense_mohm)
    : _bus(bus), _address(address), _rsense_mohm(rsense_mohm) {
}

void TMC2209::initialize() {
    uint32_t gconf = 0;
    // Use external reference for current scaling
    gconf |= TMC2209_GCONF_BITS::GCONF_I_SCALE_ANALOG;
    // Disable PDN function (required for UART operation)
    gconf |= TMC2209_GCONF_BITS::GCONF_PD_DISABLE;
    // Use internal mres instead of MS pins for microstep resolution
    gconf |= TMC2209_GCONF_BITS::GCONF_MSTEP_REG_SELECT;
    // Enable filtering
    gconf |= TMC2209_GCONF_BITS::GCONF_MULTISTEP_FILT;
    _bus->writeRegister(_address, TMC2209_Register::GCONF, gconf);
    setMicrosteps(MICROSTEP_16); // Default to 1/16 microstepping
}


/*! \brief Set the motor current settings
 *
 *  This function sets the run current, hold current, and hold delay for the TMC2209 stepper motor driver.
 *
 *  \param runCurrent The run current setting (0-31).
 *  \param holdCurrent The hold current setting (0-31).
 *  \param holdDelay The hold delay setting (0-15).
*/
void TMC2209::setCurrent(uint8_t runCurrent, uint8_t holdCurrent, uint8_t holdDelay) {
    uint32_t ihold_irun = ((holdDelay & 0x0F) << 16) | ((runCurrent & 0x1F) << 8) | (holdCurrent & 0x1F);
    _bus->writeRegister(_address, TMC2209_Register::IHOLD_IRUN, ihold_irun);
}


/*! \brief Set the microstepping resolution
 *
 *  This function sets the microstepping resolution for the TMC2209 stepper motor driver.
 *
 *  \param microsteps The desired microstepping resolution (enum TMC2209_MICROSTEPS).
*/
void TMC2209::setMicrosteps(enum TMC2209_Microstep microsteps) {
    TMC2209ChopperConfig chopconf;
    int res = _bus->readRegister(_address, TMC2209_Register::CHOPCONF, &chopconf.value);
    if (res < 0) {
        //XXX: Probably should handle read errors here, retry?
        return;
    }
    chopconf.mres = microsteps;
    _bus->writeRegister(_address, TMC2209_Register::CHOPCONF, chopconf.value);
}


/*! \brief Enable or disable StealthChop mode
 *
 *  This function enables or disables StealthChop mode on the TMC2209 stepper motor driver.
 *
 *  \param enable True to enable StealthChop, false to disable.
*/
void TMC2209::enableStealthChop(bool enable) {
    uint32_t gconf;
    int res = _bus->readRegister(_address, TMC2209_Register::GCONF, &gconf);
    if (res < 0) {
        //XXX: Probably should handle read errors here, retry?
        return;
    }
    if (!enable) {
        gconf |= TMC2209_GCONF_BITS::GCONF_EN_SPREADCYCLE; // Enable SpreadCycle
    } else {
        gconf &= ~TMC2209_GCONF_BITS::GCONF_EN_SPREADCYCLE; // Disable SpreadCycle (enable StealthChop)
    }
    _bus->writeRegister(_address, TMC2209_Register::GCONF, gconf);
}

void TMC2209::enableDriver(bool enable) {
    TMC2209ChopperConfig chopconf;
    int res = _bus->readRegister(_address, TMC2209_Register::CHOPCONF, &chopconf.value);
    if (res < 0) {
        //XXX: Probably should handle read errors here, retry?
        return;
    }
    if (enable) {
        chopconf.toff = 3; // Enable driver with toff=3
    } else {
        chopconf.toff = 0; // Disable driver with toff=0
    }
    _bus->writeRegister(_address, TMC2209_Register::CHOPCONF, chopconf.value);
}