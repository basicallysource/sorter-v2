/*
 * Sorter Interface Firmware - TMC2209 Driver Header
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

#ifndef TMC2209_H
#define TMC2209_H

#include <stdint.h>
#include "TMC_UART.h"

enum TMC2209_Register {
    // General Registers
    GCONF       = 0x00,
    GSTAT       = 0x01,
    IFCNT       = 0x02,
    SLAVECONF   = 0x03,
    OTP_PROG    = 0x04,
    OTP_READ    = 0x05,
    IOIN        = 0x06,
    FACTORY_CONF= 0x07,
    // Velocity Dependent Control
    IHOLD_IRUN  = 0x10,
    TPOWERDOWN  = 0x11,
    TSTEP       = 0x12,
    TPWMTHRS    = 0x13,
    VACTUAL     = 0x22,
    // Stallguard Control
    TCOOLTHRS   = 0x14,
    SGTHRS      = 0x40,
    SG_RESULT   = 0x41,
    COOLCONF    = 0x42,
    // Sequencer registers
    MSCNT       = 0x6A,
    MSCURACT    = 0x6B,
    // Chopper Control
    CHOPCONF    = 0x6C,
    DRV_STATUS  = 0x6F,
    PWM_CONF    = 0x70,
    PWM_SCALE   = 0x71,
    PWM_AUTO    = 0x72,
};

enum TMC2209_Microstep {
    MICROSTEP_256 = 0b0000,
    MICROSTEP_128 = 0b0001,
    MICROSTEP_64  = 0b0010,
    MICROSTEP_32  = 0b0011,
    MICROSTEP_16  = 0b0100,
    MICROSTEP_8   = 0b0101,
    MICROSTEP_4   = 0b0110,
    MICROSTEP_2   = 0b0111,
    MICROSTEP_FULL   = 0b1000,
};

enum TMC2209_GCONF_BITS {
    GCONF_I_SCALE_ANALOG = 1 << 0, // 0: Use internal current scaler, 1: external
    GCONF_INTERNAL_RSENSE = 1 << 1, // 1: Use internal Rsense (Vref becomes current reference), 0: external
    GCONF_EN_SPREADCYCLE = 1 << 2, // 1: Enable SpreadCycle, 0: StealthChop
    GCONF_SHAFT = 1 << 3, // 1: Motor direction is reversed
    GCONF_INDEX_OTPW = 1 << 4, // 1: Index output shows Over Temperature Pre-Warn 0: Shows first microstep position
    GCONF_INDEX_STEP = 1 << 5, // 1: Index output shows steps from internal pulse gen
    GCONF_PD_DISABLE = 1 << 6, // 1: Disable PDN function MUST BE SET WHEN USING UART
    GCONF_MSTEP_REG_SELECT = 1 << 7, // 0: Microstep resolution from MS1, MS2, 1: from MRES in CHOPCONF
    GCONF_MULTISTEP_FILT = 1 << 8, // 1: Software pulse generator optimization when fullstep frequency > 750Hz
    GCONF_TEST_MODE = 1 << 9, // Not for user, set to 0
};

union TMC2209ChopperConfig {
    struct __attribute__((packed)) {
        uint32_t toff : 4;
        uint32_t hstrt : 3;
        uint32_t hend : 4;
        uint32_t reserved1: 4;
        uint32_t tbl : 2;
        uint32_t vsense : 1;
        uint32_t reserved2 : 6;
        uint32_t mres : 4;
        uint32_t intpol : 1;
        uint32_t dedge : 1;
        uint32_t diss2g : 1;
        uint32_t diss2vs : 1;
    };
    uint32_t value;
};

class TMC2209 {
public:
    TMC2209(class TMC_UART_Bus* bus, uint8_t address, uint32_t rsense_mohm = 100);
    void initialize();
    void enableDriver(bool enable);
    void setCurrent(uint8_t runCurrent, uint8_t holdCurrent, uint8_t holdDelay);
    void setMicrosteps(enum TMC2209_Microstep microsteps);
    void enableStealthChop(bool enable);
    void setStealthChopThreshold(int32_t threshold);
    void enableStallGuard(int32_t threshold);
    void disableStallGuard();
    int32_t readStallGuardResult();
    bool isStalled();
    void enableCoolStep(uint8_t semin, uint8_t semax, uint8_t seup, uint8_t sedn);
    void disableCoolStep();
    void writeRegister(uint8_t reg, uint32_t value) { _bus->writeRegister(_address, reg, value); };
    int readRegister(uint8_t reg, uint32_t* value) { return _bus->readRegister(_address, reg, value); };
private:
    TMC_UART_Bus* _bus;
    uint8_t _address;
    uint32_t _rsense_mohm;
    // Shadow registers — tracks last written value so we can avoid fragile read-modify-write
    uint32_t _gconf;
    TMC2209ChopperConfig _chopconf;
};

#endif // TMC2209_H