/*
 * Sorter Interface Firmware - Host Link Implementation
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

#include "HostLink.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/irq.h"
#include "host_link.pio.h"

// The interrupt handler is a plain function, so it reaches the one link through this.
static HostLink *active_link = nullptr;

HostLink::HostLink(PIO pio, uint tx_pin, uint rx_pin) : _pio(pio), _tx_pin(tx_pin), _rx_pin(rx_pin) {}

/** \brief Claim two state machines, load both programs and start the link.
 *
 * Called once at boot, not from INIT: the host may be talking over this link
 * when it sends INIT.
 */
void HostLink::setup(uint32_t baudrate) {
    if (_ready)
        return;
    _tx_sm = (uint)pio_claim_unused_sm(_pio, true);
    _rx_sm = (uint)pio_claim_unused_sm(_pio, true);
    uint tx_offset = (uint)pio_add_program(_pio, &host_link_tx_program);
    uint rx_offset = (uint)pio_add_program(_pio, &host_link_rx_program);
    float clkdiv = (float)clock_get_hz(clk_sys) / (8.0f * (float)baudrate);

    // TX idles high before the state machine owns the pin, so the host sees no
    // start bit while the link comes up.
    pio_sm_set_pins_with_mask(_pio, _tx_sm, 1u << _tx_pin, 1u << _tx_pin);
    pio_sm_set_pindirs_with_mask(_pio, _tx_sm, 1u << _tx_pin, 1u << _tx_pin);
    pio_gpio_init(_pio, _tx_pin);
    pio_sm_config tx = host_link_tx_program_get_default_config(tx_offset);
    sm_config_set_out_pins(&tx, _tx_pin, 1);
    sm_config_set_sideset_pins(&tx, _tx_pin);
    sm_config_set_out_shift(&tx, true, false, 32);
    sm_config_set_fifo_join(&tx, PIO_FIFO_JOIN_TX);
    sm_config_set_clkdiv(&tx, clkdiv);
    pio_sm_init(_pio, _tx_sm, tx_offset, &tx);

    pio_sm_set_consecutive_pindirs(_pio, _rx_sm, _rx_pin, 1, false);
    pio_gpio_init(_pio, _rx_pin);
    gpio_pull_up(_rx_pin);
    pio_sm_config rx = host_link_rx_program_get_default_config(rx_offset);
    sm_config_set_in_pins(&rx, _rx_pin);
    sm_config_set_jmp_pin(&rx, _rx_pin);
    sm_config_set_in_shift(&rx, true, false, 32);
    sm_config_set_fifo_join(&rx, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv(&rx, clkdiv);
    pio_sm_init(_pio, _rx_sm, rx_offset, &rx);

    active_link = this;
    uint irq_num = (_pio == pio0) ? PIO0_IRQ_0 : PIO1_IRQ_0;
    irq_set_exclusive_handler(irq_num, rxIrq);
    pio_set_irq0_source_enabled(_pio, (enum pio_interrupt_source)(pis_sm0_rx_fifo_not_empty + _rx_sm), true);
    irq_set_enabled(irq_num, true);

    pio_sm_set_enabled(_pio, _rx_sm, true);
    pio_sm_set_enabled(_pio, _tx_sm, true);
    _ready = true;
}

void HostLink::rxIrq() {
    if (active_link != nullptr)
        active_link->drainRxFifo();
}

void HostLink::drainRxFifo() {
    while (!pio_sm_is_rx_fifo_empty(_pio, _rx_sm)) {
        // The byte arrives in the top 8 bits of the shift register.
        uint8_t c = (uint8_t)(pio_sm_get(_pio, _rx_sm) >> 24);
        uint32_t next = (_rx_head + 1) & (RX_BUFFER_SIZE - 1);
        if (next == _rx_tail)
            continue; // Full: drop the byte, and the frame's CRC will fail
        _rx_buffer[_rx_head] = c;
        _rx_head = next;
    }
}

int HostLink::getc() {
    if (!_ready || _rx_tail == _rx_head)
        return -1;
    uint8_t c = _rx_buffer[_rx_tail];
    _rx_tail = (_rx_tail + 1) & (RX_BUFFER_SIZE - 1);
    return c;
}

void HostLink::write(const char *data, int length) {
    if (!_ready)
        return;
    for (int i = 0; i < length; i++)
        pio_sm_put_blocking(_pio, _tx_sm, (uint8_t)data[i]);
}
