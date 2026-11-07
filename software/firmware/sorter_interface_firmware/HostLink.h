/*
 * Sorter Interface Firmware - Host Link Header
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

#ifndef HOST_LINK_H
#define HOST_LINK_H

#include "hardware/pio.h"
#include <stdint.h>

/** \brief 8N1 UART to the host on any two GPIOs, through PIO.
 *
 * The host speaks the same framed commands here as over USB. Received bytes go
 * from the PIO FIFO to a ring buffer in an interrupt, so a slow command handler
 * on the main loop does not lose them. Sending blocks until the bytes are in the
 * PIO FIFO.
 */
class HostLink {
  public:
    HostLink(PIO pio, uint tx_pin, uint rx_pin);

    void setup(uint32_t baudrate);
    int getc(); // The next received byte, or -1 if none
    void write(const char *data, int length);

  private:
    static void rxIrq();
    void drainRxFifo();

    PIO _pio;
    uint _tx_pin;
    uint _rx_pin;
    uint _tx_sm = 0;
    uint _rx_sm = 0;
    bool _ready = false;

    static const uint32_t RX_BUFFER_SIZE = 1024; // A power of two
    volatile uint8_t _rx_buffer[RX_BUFFER_SIZE];
    volatile uint32_t _rx_head = 0; // Written by the interrupt
    volatile uint32_t _rx_tail = 0; // Written by the main loop
};

#endif
