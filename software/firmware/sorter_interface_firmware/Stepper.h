#include <atomic>
/*
 * Sorter Interface Firmware - Stepper Motion Controller Header
 * Copyright (C) 2017-2026 Jose I Romero
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

#ifndef STEPPER_H
#define STEPPER_H

#include <stdint.h>

#define STEP_TICK_RATE_HZ 10000 // Stepper tick rate in Hz
#define STEP_MOTION_UPDATE_RATE_HZ 1000 // How often to update motion parameters
#define STEPPER_MAX_SPEED 60000 // Max stepper speed in steps per second


enum StepperState {
    STEPPER_STOPPED, // Stepper is at a standstill
    STEPPER_ACCELERATING, // Speeding up to target speed
    STEPPER_CRUISING, // At target speed
    STEPPER_BRAKING, // Decelerating to stop or lower target speed
};

class Stepper {
public:
    Stepper(int step_pin, int dir_pin);
    void initialize();
    void stepgen_tick(); // Must be called at STEP_TICK_RATE_HZ
    void motion_update_tick(); // Must be called at STEP_MOTION_UPDATE_RATE_HZ
    void setSpeedLimits(uint32_t min_speed, uint32_t max_speed);
    void setAcceleration(uint32_t acceleration);
    bool moveSteps(int32_t distance);
    bool moveAtSpeed(int32_t speed);
    // Oscillate +-amplitude microsteps for `cycles` full back-and-forths to
    // break static friction. Sets accel/max-speed, then runs autonomously on
    // core1; net displacement is zero (ends where it started).
    bool jitter(int32_t amplitude, int32_t cycles, int32_t speed, int32_t accel);
    void cancel();
    bool isStopped() { return _state == STEPPER_STOPPED; }
    // True for the whole duration of a jitter run. Unlike isStopped() this does
    // NOT flicker between strokes (a jitter passes through STEPPER_STOPPED for
    // ~1ms between every stroke), so it is the reliable signal for "is a jitter
    // still in progress" and the gate that refuses overlapping jitter requests.
    bool isJittering() { return _jitter_active.load(); }
    int32_t getPosition() { return _absolute_position; }
    void setPosition(int32_t position) { _absolute_position = position; }
    void home(int32_t home_speed, int home_pin, bool home_pin_polarity);

    // StallGuard / DIAG. The TMC2209 drives its DIAG output high when SG_RESULT
    // falls to/below 2*SGTHRS while running above the TCOOLTHRS velocity floor —
    // i.e. the motor is stalling. setStallPin() records the wired GPIO (-1 if
    // none); enableStallDetection() arms the motion-tick check; wasStalled()
    // reports the latched event; clearStall() resets it. SGTHRS/TCOOLTHRS are
    // configured by the backend over UART (write_driver_register), not here.
    void setStallPin(int pin) { _stall_pin = pin; }
    void enableStallDetection(bool enable) {
        _stall_enabled.store(enable);
        if (enable) _stalled.store(false);
    }
    bool wasStalled() { return _stalled.load(); }
    void clearStall() { _stalled.store(false); }

private:
    void beginJitterStroke();

    // Pins for the step generator
    int _step_pin, _dir_pin;
    // Motion parameters
    uint32_t _accel;
    uint32_t _max_speed, _min_speed;
    // Snapshot of the above taken when a jitter starts, restored when it ends.
    // A jitter overrides accel/max_speed for its fast oscillation; without this
    // the override would persist and make every subsequent normal move jolt.
    uint32_t _saved_accel = 0, _saved_max_speed = 0, _saved_min_speed = 0;
    
    // Last commanded state
    std::atomic<StepperState> _state;
    std::atomic<int32_t> _mc_distance; // Always positive, direction in _move_dir
    std::atomic<int32_t> _mc_speed; // Always positive, direction in _move_dir
    std::atomic<int32_t> _mc_dir; // 1 = forward, -1 = reverse
    std::atomic<int32_t> _mc_home_pin; // Home switch pin, -1 if not homing
    std::atomic<bool> _mc_home_pin_polarity; // Home switch polarity, true if active high, false if active low

    // Internal state
    std::atomic<int32_t> _steps_moved, _steps_frac; // How many steps have we moved in the current move, counted towards the _move_direction (if moving backwards we go negative)
    std::atomic<int32_t> _brake_distance; // Distance required to brake to a stop from current speed, decision point for braking
    std::atomic<int32_t> _current_speed;
    std::atomic<int32_t> _current_speed_frac;
    std::atomic<int32_t> _current_dir; // 1 = forward, -1 = reverse
    std::atomic<int32_t> _absolute_position;

    // Jitter state. A jitter run is owned entirely by core1 once started: only
    // jitter() (core0, gated so it can't fire while one is active) and the core1
    // motion tick ever mutate these. core0 stop/move commands are REJECTED while
    // jittering rather than tearing the run down, so there is no cross-core race.
    std::atomic<bool> _jitter_active; // true from start until the last stroke completes
    std::atomic<int32_t> _jitter_amplitude; // microsteps per stroke
    std::atomic<int32_t> _jitter_strokes_remaining; // strokes still to perform (2 per cycle)
    std::atomic<int32_t> _jitter_dir; // direction of the next stroke (1 / -1)

    // StallGuard state. _stall_pin is set once at init (core0) and only read by
    // the core1 motion tick, so it needs no atomicity. _stall_enabled/_stalled
    // are written from both cores (core0 commands, core1 detection) so they are
    // atomic. _stalled latches until clearStall() so a transient stall is not
    // lost between backend polls.
    int _stall_pin = -1; // TMC2209 DIAG GPIO for this channel, -1 if not wired
    std::atomic<bool> _stall_enabled{false}; // whether the motion tick checks DIAG
    std::atomic<bool> _stalled{false}; // latched: DIAG fired while moving
};

#endif // STEPPER_H
