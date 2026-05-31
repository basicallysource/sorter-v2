// Bare-bones dual-UART probe for the basically V1-2 board.
//
// Standalone diagnostic firmware: NO IRL, NO COBS, NO command tables — just the
// two hardware UARTs and plain-text reports over USB serial. Built to answer one
// question: can we talk over BOTH TMC UART buses at all, in the most constrained
// context possible?
//
// Per bus it runs three escalating tests:
//   1. internal LBE loopback  — sets the UART's internal loopback bit and checks
//      the peripheral echoes bytes back. Proves the UART block is alive & clocked,
//      independent of any external wiring.
//   2. external tie loopback  — LBE off, transmits on TX and reads it back on RX.
//      Because the TMC single-wire bus ties TX->(~1k)->RX, a correct board echoes
//      every byte. Proves the tie resistor + pin mux + half-duplex path.
//   3. TMC2209 IOIN read       — real driver probe at addresses 0..3. IOIN bits
//      31:24 are the chip VERSION (0x21 for a genuine TMC2209). On failure the raw
//      echo + reply bytes are dumped so we can tell "silent" from "garbled".
//
// Bus 0 (4-motor): TX=GP16 RX=GP17.  Bus 1 (chute): TX=GP4 RX=GP5.  Baud 400000.
//
// Output prints every ~2 s. Send 'b' over the USB serial to reboot into BOOTSEL
// for re-flashing (this firmware doesn't speak the COBS protocol, so flash.py
// can't auto-reboot it).

#include <stdio.h>
#include <stdint.h>
#include <string.h>

#include "pico/stdlib.h"
#include "pico/bootrom.h"
#include "hardware/uart.h"
#include "hardware/gpio.h"

struct BusCfg {
    uart_inst_t* uart;
    const char* name;
    int tx_pin;
    int rx_pin;
};

static const BusCfg BUSES[] = {
    {uart0, "UART0 4-bus", 16, 17},
    {uart1, "UART1 chute", 4, 5},
};
static const size_t BUS_COUNT = sizeof(BUSES) / sizeof(BUSES[0]);

// 400000 is the production baud; the slower rates are tried in case the second
// bus only works when bit periods are long enough to punch through any RC smear.
static const long BAUDS[] = {400000, 115200, 19200, 9600};
static const size_t BAUD_COUNT = sizeof(BAUDS) / sizeof(BAUDS[0]);

static const uint UART_LBE_BIT = 1u << 7; // UARTCR loopback enable

// Per-byte read timeout, baud-aware: must comfortably exceed one byte time plus
// the driver's reply turnaround. At 9600 a single byte is already ~1ms, so a
// fixed 1ms would be too short — scale it.
static uint32_t byte_timeout_us(long baud) {
    return (uint32_t)(40 * 1000000L / baud) + 2000;
}

static uint8_t tmc_crc(const uint8_t* data, size_t len) {
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        uint8_t cur = data[i];
        for (uint8_t j = 0; j < 8; j++) {
            if ((crc >> 7) ^ (cur & 0x01)) {
                crc = (crc << 1) ^ 0x07;
            } else {
                crc <<= 1;
            }
            cur >>= 1;
        }
    }
    return crc;
}

static void uart_basic_init(const BusCfg& b, long baud) {
    gpio_set_function(b.tx_pin, GPIO_FUNC_UART);
    gpio_set_function(b.rx_pin, GPIO_FUNC_UART);
    uart_init(b.uart, baud);
    uart_set_format(b.uart, 8, 1, UART_PARITY_NONE);
    uart_set_hw_flow(b.uart, false, false);
}

static void drain_rx(uart_inst_t* u) {
    while (uart_is_readable(u)) {
        (void)uart_get_hw(u)->dr;
    }
}

static bool read_byte_timeout(uart_inst_t* u, uint8_t* out, uint32_t timeout_us) {
    absolute_time_t deadline = make_timeout_time_us(timeout_us);
    while (!uart_is_readable(u)) {
        if (time_reached(deadline)) {
            return false;
        }
    }
    *out = (uint8_t)uart_get_hw(u)->dr;
    return true;
}

// Returns count of bytes that echoed back correctly out of 4.
static int test_internal_lbe(const BusCfg& b, long baud) {
    uint32_t to = byte_timeout_us(baud);
    uart_basic_init(b, baud);
    hw_set_bits(&uart_get_hw(b.uart)->cr, UART_LBE_BIT);
    drain_rx(b.uart);

    const uint8_t pattern[4] = {0xDE, 0xAD, 0xBE, 0xEF};
    int ok = 0;
    for (int i = 0; i < 4; i++) {
        uart_putc_raw(b.uart, pattern[i]);
        uint8_t got = 0;
        if (read_byte_timeout(b.uart, &got, to) && got == pattern[i]) {
            ok++;
        }
    }

    hw_clear_bits(&uart_get_hw(b.uart)->cr, UART_LBE_BIT);
    return ok;
}

// Returns count of bytes that came back through the external TX->1k->RX tie.
static int test_external_tie(const BusCfg& b, long baud) {
    uint32_t to = byte_timeout_us(baud);
    uart_basic_init(b, baud); // LBE off
    drain_rx(b.uart);

    const uint8_t pattern[4] = {0xDE, 0xAD, 0xBE, 0xEF};
    int ok = 0;
    for (int i = 0; i < 4; i++) {
        uart_putc_raw(b.uart, pattern[i]);
        uint8_t got = 0;
        if (read_byte_timeout(b.uart, &got, to) && got == pattern[i]) {
            ok++;
        }
    }
    return ok;
}

struct IoinResult {
    int echo_n;
    uint8_t echo[4];
    int reply_n;
    uint8_t reply[8];
    bool full;    // got all 8 reply bytes
    bool crc_ok;
    uint32_t ioin;
    uint8_t version;
};

// Single-wire TMC2209 read of IOIN at one address. Captures the raw echo (our own
// request looped back through the tie) and the device reply separately, so a
// caller can tell "silent" from "garbled".
static IoinResult tmc_read_ioin(const BusCfg& b, uint8_t addr, long baud) {
    IoinResult r = {};
    uint32_t to = byte_timeout_us(baud);
    uart_basic_init(b, baud); // LBE off
    drain_rx(b.uart);

    uint8_t req[4];
    req[0] = 0x55;        // sync (matches working production firmware)
    req[1] = addr;        // slave node address
    req[2] = 0x06 & 0x7F; // IOIN register, read (MSB clear)
    req[3] = tmc_crc(req, 3);

    uart_write_blocking(b.uart, req, sizeof(req));
    uart_tx_wait_blocking(b.uart);

    // Pull back everything: first 4 bytes are our echo, then up to 8 reply bytes.
    for (int i = 0; i < 4; i++) {
        uint8_t v;
        if (!read_byte_timeout(b.uart, &v, to)) break;
        r.echo[r.echo_n++] = v;
    }
    for (int i = 0; i < 8; i++) {
        uint8_t v;
        if (!read_byte_timeout(b.uart, &v, to)) break;
        r.reply[r.reply_n++] = v;
    }

    if (r.reply_n == 8) {
        r.full = true;
        uint8_t crc = tmc_crc(r.reply, 7);
        r.ioin = ((uint32_t)r.reply[3] << 24) | ((uint32_t)r.reply[4] << 16) |
                 ((uint32_t)r.reply[5] << 8) | (uint32_t)r.reply[6];
        r.version = (r.ioin >> 24) & 0xFF;
        r.crc_ok = (crc == r.reply[7]);
    }
    return r;
}

static void print_ioin_detail(uint8_t addr, const IoinResult& r) {
    if (r.full && r.crc_ok) {
        printf("    addr %3u IOIN : 0x%08lX ver=0x%02X %s\n", addr, (unsigned long)r.ioin,
               r.version, r.version == 0x21 ? "OK (genuine TMC2209)" : "(unexpected version)");
        return;
    }
    if (r.full) {
        printf("    addr %3u IOIN : CRC ERROR ioin=0x%08lX\n", addr, (unsigned long)r.ioin);
        return;
    }
    char echo_hex[16] = {0};
    char reply_hex[24] = {0};
    for (int i = 0; i < r.echo_n; i++) sprintf(echo_hex + i * 2, "%02X", r.echo[i]);
    for (int i = 0; i < r.reply_n; i++) sprintf(reply_hex + i * 2, "%02X", r.reply[i]);
    printf("    addr %3u IOIN : no response  echo=%d[%s]  reply=%d[%s]\n", addr, r.echo_n,
           echo_hex, r.reply_n, reply_hex);
}

// --- Pin/peripheral mux verification (RP2040 IO MUX table from the Gemini doc) ---
// UART0 TX: GP0/12/16/28  RX: GP1/13/17/29
// UART1 TX: GP4/8/20/24   RX: GP5/9/21/25
// The doc's central failure mode is wiring two buses onto pins that route to the
// same internal UART block. We verify statically (no pin driving) that each bus's
// pins belong to its own peripheral and the two buses don't collide.
static int uart_for_tx(int pin) {
    if (pin == 0 || pin == 12 || pin == 16 || pin == 28) return 0;
    if (pin == 4 || pin == 8 || pin == 20 || pin == 24) return 1;
    return -1;
}
static int uart_for_rx(int pin) {
    if (pin == 1 || pin == 13 || pin == 17 || pin == 29) return 0;
    if (pin == 5 || pin == 9 || pin == 21 || pin == 25) return 1;
    return -1;
}

static void verify_pin_mux() {
    printf("\n-- pin/peripheral mux check (per RP2040 IO MUX) --\n");
    bool ok = true;
    int claimed[2] = {-1, -1}; // which bus index claimed uart0 / uart1
    for (size_t i = 0; i < BUS_COUNT; i++) {
        const BusCfg& b = BUSES[i];
        int want = (b.uart == uart0) ? 0 : 1;
        int tx_u = uart_for_tx(b.tx_pin);
        int rx_u = uart_for_rx(b.rx_pin);
        bool good = (tx_u == want) && (rx_u == want);
        printf("  %s: TX=GP%-2d->UART%d  RX=GP%-2d->UART%d  -> %s\n", b.name, b.tx_pin,
               tx_u, b.rx_pin, rx_u, good ? "OK" : "BAD MAPPING");
        if (!good) ok = false;
        if (claimed[want] != -1) {
            printf("  !! COLLISION: UART%d claimed by two buses\n", want);
            ok = false;
        }
        claimed[want] = (int)i;
    }
    printf("  mux verdict: %s\n", ok ? "no collision, pins valid" : "PROBLEM — see above");
}

// Full register-level sweep of one bus at one baud across the entire 8-bit address
// space the datagram can carry. TMC2209 only decodes 0..3 (MS1/MS2), so anything
// answering above 3 would be a surprise; sweeping all 256 leaves zero doubt that
// the bus is truly silent rather than merely mis-addressed.
static void sweep_bus_baud(const BusCfg& b, long baud) {
    printf("  [baud %6ld]\n", baud);

    int lbe = test_internal_lbe(b, baud);
    printf("    internal LBE : %d/4  %s\n", lbe, lbe == 4 ? "OK (peripheral alive)" : "FAIL");

    int tie = test_external_tie(b, baud);
    printf("    external tie : %d/4  %s\n", tie, tie == 4 ? "OK (TX->1k->RX wired)" : "FAIL");

    // Detailed view (with raw echo/reply) for the only addresses a TMC2209 can use.
    for (uint8_t addr = 0; addr < 4; addr++) {
        IoinResult r = tmc_read_ioin(b, addr, baud);
        print_ioin_detail(addr, r);
    }

    // Exhaustive sweep 4..255: print only anything that answers at all.
    int responders = 0;
    for (int addr = 4; addr < 256; addr++) {
        IoinResult r = tmc_read_ioin(b, (uint8_t)addr, baud);
        if (r.reply_n > 0) {
            responders++;
            print_ioin_detail((uint8_t)addr, r);
        }
    }
    printf("    swept addr 4..255: %d extra responder(s)\n", responders);
}

static void run_full_battery() {
    printf("\n================ UART FULL BATTERY ================\n");
    printf("platform: RP2040 / genuine Pico, single-board single-wire half-duplex.\n");
    printf("(RP2350-E9 idle-pulldown errata and board-to-board common-ground notes\n");
    printf(" from the doc are N/A here: not RP2350, not a two-board link.)\n");

    verify_pin_mux();

    for (size_t i = 0; i < BUS_COUNT; i++) {
        const BusCfg& b = BUSES[i];
        printf("\n%s (TX=GP%d RX=GP%d):\n", b.name, b.tx_pin, b.rx_pin);
        for (size_t j = 0; j < BAUD_COUNT; j++) {
            sweep_bus_baud(b, BAUDS[j]);
        }
    }
    printf("\n================ END BATTERY ================\n");
    printf("Send 'r' to re-run, 'b' to reboot to BOOTSEL.\n");
}

int main() {
    stdio_init_all();

    // Give the host time to mount the USB serial port. Drain any startup-settling
    // noise (the doc notes GP0 etc. can emit a stray 0xFF at boot).
    sleep_ms(3000);
    printf("\nUART probe firmware up.\n");

    run_full_battery();

    while (true) {
        int c = getchar_timeout_us(100000);
        if (c == 'r' || c == 'R') {
            run_full_battery();
        } else if (c == 'b' || c == 'B') {
            printf("Rebooting to BOOTSEL...\n");
            sleep_ms(50);
            reset_usb_boot(0, 0);
        }
    }
}
