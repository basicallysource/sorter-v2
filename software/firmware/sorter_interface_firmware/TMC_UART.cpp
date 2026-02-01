/*
 * Sorter Interface Firmware - TMC UART Bus Implementation
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

#include "TMC_UART.h"
#include "hardware/gpio.h"

//#define TMC_UART_TRACE_ENABLED

#ifdef TMC_UART_TRACE_ENABLED
#define TRACE_PIN 8
#define TRACE_INIT() gpio_init(TRACE_PIN); gpio_set_dir(TRACE_PIN, GPIO_OUT);
#define TRACE_HIGH() gpio_put(TRACE_PIN, 1)
#define TRACE_LOW() gpio_put(TRACE_PIN, 0)
#else
#define TRACE_INIT()
#define TRACE_HIGH()
#define TRACE_LOW()
#endif

// Polyfill functions for RP2040 UART to work with the TMC

#include "pico/time.h"
#include "pico/sync.h"

/*! \brief Read data from UART with timeout
 *
 *  This function reads up to 'len' bytes from the specified UART instance into the provided buffer.
 *  It blocks until either 'len' bytes have been read or the specified timeout in microseconds has elapsed.
 *
 *  \param uart Pointer to the UART instance to read from.
 *  \param buf Pointer to the buffer where read data will be stored.
 *  \param len Number of bytes to read.
 *  \param timeout_us Timeout in microseconds.
 *  \return Number of bytes actually read.
 */
static inline size_t uart_read_blocking_timeout(uart_inst_t *uart, uint8_t *buf, size_t len, uint32_t timeout_us) {
    size_t bytes_read = 0;
    uint32_t start_time = time_us_32();
    while (bytes_read < len) {
        if (uart_is_readable(uart)) {
            *buf++ = (uint8_t)uart_get_hw(uart)->dr;
            bytes_read++;
        }
        if ((time_us_32() - start_time) > timeout_us) {
            break; // Timeout
        }
    }
    return bytes_read;
}

/*! \brief Clear UART RX buffer
 *
 *  This function quickly discards all data currently available in the UART RX fifo. 
 *  
 *  It attempts to be atomic by disabling interrupts. This may fail to work correctly if the uart character 
 *  time is less than (up to) 32 memory accesses to the fifo.
 *
 *  \param uart Pointer to the UART instance to clear.
 */
static inline void uart_clear_rx_fifo(uart_inst_t *uart) {
    uint32_t interrupt_status = save_and_disable_interrupts();
    while (uart_is_readable(uart)) {
        volatile uint8_t dummy = (uint8_t)uart_get_hw(uart)->dr;
        (void)dummy; // Prevent unused variable warning
    }
    restore_interrupts(interrupt_status);
}


// End Polyfill functions for RP2040 UART to work with the TMC


struct TMC_WRITE_COMMAND {
    uint8_t sync;
    uint8_t address;
    uint8_t reg;
    uint8_t data[4];
    uint8_t crc;
} __attribute__((packed));


struct TMC_READ_COMMAND {
    uint8_t sync;
    uint8_t address;
    uint8_t reg;
    uint8_t crc;
} __attribute__((packed));

struct TMC_READ_RESPONSE {
    uint8_t sync;
    uint8_t address;
    uint8_t reg;
    uint8_t data[4];
    uint8_t crc;
} __attribute__((packed));

TMC_UART_Bus::TMC_UART_Bus(uart_inst_t* uart)
    : _uart(uart) {
}

bool TMC_UART_Bus::setupComm(long baudrate, uint tx_pin, uint rx_pin) {
    _timeout_us = 120000000 / baudrate; // Timeout for 120 bits
    // Set data format: 8 data bits, 1 stop bit, no parity
    uart_set_format(_uart, 8, 1, UART_PARITY_NONE);
    // Disable hardware flow control
    uart_set_hw_flow(_uart, false, false);
    // Set TX and RX pins
    gpio_set_function(tx_pin, GPIO_FUNC_UART);
    gpio_set_function(rx_pin, GPIO_FUNC_UART);
    uart_init(_uart, baudrate);

    TRACE_INIT();

    return true;
}


/*! \brief Write a 32-bit value to a register on the TMC device
 *
 *  This function writes a 32-bit value to the specified register of the TMC device over UART.
 *
 *  \param address The TMC device address.
 *  \param reg The register address to write to.
 *  \param value The 32-bit value to write to the register.
 */
void TMC_UART_Bus::writeRegister(uint8_t address, uint8_t reg, uint32_t value) {
    struct TMC_WRITE_COMMAND cmd;
    cmd.sync = 0x55; // Sync byte for write
    cmd.address = address;
    cmd.reg = reg | 0x80; // Set MSB for write
    cmd.data[0] = (value >> 24) & 0xFF;
    cmd.data[1] = (value >> 16) & 0xFF;
    cmd.data[2] = (value >> 8) & 0xFF;
    cmd.data[3] = value & 0xFF;
    cmd.crc = calcCRC((uint8_t*)&cmd, sizeof(cmd) - 1);
    uart_write_blocking(_uart, (const uint8_t*)&cmd, sizeof(cmd));
    uart_tx_wait_blocking(_uart); // Ensure all data is sent
}


/*! \brief Read a register from the TMC device
 *
 *  This function reads a 32-bit register value from the specified TMC device over UART.
 *
 *  \param address The TMC device address.
 *  \param reg The register address to read from.
 *  \param value Pointer to store the read register value.
 *  \return 0 on success, negative error code on failure.
 */
int TMC_UART_Bus::readRegister(uint8_t address, uint8_t reg, uint32_t* value) {
    struct TMC_READ_COMMAND cmd;
    cmd.sync = 0x55; // Sync byte for read
    cmd.address = address;
    cmd.reg = reg & 0x7F; // Clear MSB for read
    cmd.crc = calcCRC((uint8_t*)&cmd, sizeof(cmd) - 1);
    uart_write_blocking(_uart, (const uint8_t*)&cmd, sizeof(cmd));
    uart_tx_wait_blocking(_uart); // Ensure all data is sent
    TRACE_HIGH();
    uart_clear_rx_fifo(_uart); // Clear any stale data (like what we just transmitted)
    TRACE_LOW();
    // Read response with timeout
    struct TMC_READ_RESPONSE resp;
    size_t bytes_read = uart_read_blocking_timeout(_uart, (uint8_t*)&resp, sizeof(resp), _timeout_us);
    if (bytes_read < sizeof(resp)) {
        return -1; // Timeout or incomplete response
    }
    // Verify CRC
    uint8_t crc = calcCRC((uint8_t*)&resp, sizeof(resp) - 1);
    if (crc != resp.crc) {
        return -2; // CRC error
    }
    // Extract data
    *value = (resp.data[0] << 24) | (resp.data[1] << 16) | (resp.data[2] << 8) | resp.data[3];
    // Success
    return 0;
}

/*! \brief Calculate CRC for TMC UART communication
 *
 *  This function calculates the CRC byte for a given data buffer using the polynomial
 *  x^8 + x^2 + x^1 + x^0.
 *
 *  \param data Pointer to the data buffer.
 *  \param length Length of the data buffer in bytes.
 *  \return Calculated CRC byte.
 */
uint8_t TMC_UART_Bus::calcCRC(uint8_t *data, size_t length) {
    uint8_t crc = 0;
    for (size_t i = 0; i < length; i++) {
        uint8_t cur_byte = data[i];
        for (uint8_t j = 0; j < 8; j++) {
            if ((crc >> 7) ^ (cur_byte & 0x01)) {
                crc = (crc << 1) ^ 0x07;
            } else {
                crc <<= 1;
            }
            cur_byte >>= 1;
        }
    }
    return crc;
}