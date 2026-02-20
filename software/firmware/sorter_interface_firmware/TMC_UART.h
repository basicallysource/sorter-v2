/*
 * Sorter Interface Firmware - TMC UART Bus Header
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

#ifndef TMC_UART_H
#define TMC_UART_H

#include <stdint.h>
#include "hardware/uart.h"

class TMC_UART_Bus {
public:
    TMC_UART_Bus(uart_inst_t* uart);

    bool setupComm(long baudrate = 115200, uint tx_pin = 0, uint rx_pin = 1);

    void writeRegister(uint8_t address, uint8_t reg, uint32_t data);
    int readRegister(uint8_t address, uint8_t  reg, uint32_t* data);

private:
    uart_inst_t* _uart;
    uint8_t _address;
    uint32_t _timeout_us;
    uint8_t calcCRC(uint8_t* data, size_t length);
};

#endif // TMC_UART_H