/*
 * Sorter Interface Firmware - when a motor's next step is due
 *
 * A motor turning at a steady speed sounds and runs smooth only if its steps
 * are evenly spaced. A step generator that can place a step only on a fixed
 * tick cannot do that: at 3000 steps a second on a 10 kHz tick the steps come
 * 300 and 400 microseconds apart in turn, and the motor rattles. This clock
 * keeps the motor's place within its current step from the real time and the
 * speed, and says in how many microseconds the next step is due, so the caller
 * can step then and not on a grid.
 *
 * It needs nothing from the Pico SDK, so it is tested on any computer
 * (test/step_clock_test.cpp).
 */

#ifndef STEP_CLOCK_H
#define STEP_CLOCK_H

#include <stdint.h>

class StepClock {
  public:
    // How far through a step the motor is, in steps a second times microseconds:
    // one whole step is a million.
    static const uint32_t ONE_STEP = 1000000;
    // A caller that was away longer than this is treated as away this long: the
    // motor falls behind instead of making up the steps in a burst.
    static const uint32_t LONGEST_GAP_US = 2000;
    static const uint32_t NEVER = 0xFFFFFFFF;

    // The motor has stopped: the next move starts a fresh step.
    void stop() {
        _running = false;
        _phase = 0;
    }

    // Bring the clock to `now_us`, the motor having turned at `speed` steps a
    // second since the last call. Then `due()` says whether a step has come due.
    void advance(uint32_t now_us, uint32_t speed) {
        if (!_running) {
            _running = true;
            _last_us = now_us;
            _phase = 0;
            return;
        }
        uint32_t gap_us = now_us - _last_us; // Right across the 32-bit wrap too
        _last_us = now_us;
        if (gap_us > LONGEST_GAP_US) {
            gap_us = LONGEST_GAP_US;
        }
        _phase += speed * gap_us; // At most 60000 x 2000, far inside 32 bits
    }

    bool due() const { return _phase >= ONE_STEP; }

    // One step was made.
    void stepped() { _phase -= ONE_STEP; }

    // The caller will make no more steps this time: what is still owed is dropped
    // down to one step, due at once.
    void dropBacklog() {
        if (_phase >= ONE_STEP) {
            _phase = ONE_STEP - 1;
        }
    }

    // Microseconds from the last `advance` to the next step at `speed`, never
    // less than 1; NEVER at a standstill.
    uint32_t waitUs(uint32_t speed) const {
        if (speed == 0) {
            return NEVER;
        }
        if (_phase >= ONE_STEP) {
            return 1;
        }
        return (ONE_STEP - _phase + speed - 1) / speed;
    }

  private:
    bool _running = false;
    uint32_t _last_us = 0;
    uint32_t _phase = 0;
};

#endif // STEP_CLOCK_H
