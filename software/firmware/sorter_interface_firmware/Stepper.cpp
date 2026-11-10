/*
 * Sorter Interface Firmware - Stepper Motion Controller Implementation
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

#include "Stepper.h"
#include "hardware/gpio.h"
#include "pico/time.h"

Stepper::Stepper(int step_pin, int dir_pin)
    : _step_pin(step_pin), _dir_pin(dir_pin),
      _accel(10000), _max_speed(2000), _min_speed(16),
    _state(STEPPER_STOPPED), _mc_distance(-1), _mc_speed(-1),
      _mc_dir(1), _mc_home_pin(-1),
    _steps_moved(0), _steps_frac(0), _brake_distance(0),
    _current_speed(0), _current_speed_frac(0), _current_dir(1),
    _jitter_active(false), _jitter_amplitude(0), _jitter_strokes_remaining(0), _jitter_dir(1) {
}

void Stepper::initialize() {
    gpio_init(_step_pin);
    gpio_set_dir(_step_pin, GPIO_OUT);
    gpio_init(_dir_pin);
    gpio_set_dir(_dir_pin, GPIO_OUT);
}

void Stepper::setSpeedLimits(uint32_t min_speed, uint32_t max_speed) {
    if (max_speed > STEPPER_MAX_SPEED) max_speed = STEPPER_MAX_SPEED;
    if (min_speed > STEPPER_MAX_SPEED) min_speed = STEPPER_MAX_SPEED;
    if (min_speed > max_speed) return; // Invalid
    
    
    _min_speed = min_speed;
    _max_speed = max_speed;
}

void Stepper::setAcceleration(uint32_t acceleration) {
    _accel = acceleration;
}

void Stepper::cancel() {
    // If we tear down an in-flight jitter, restore the motion params it saved so
    // the override doesn't outlive the jitter.
    if (_jitter_active.load()) {
        _accel = _saved_accel;
        _max_speed = _saved_max_speed;
        _min_speed = _saved_min_speed;
    }
    _state = STEPPER_STOPPED;
    _jitter_active.store(false);
    _jitter_strokes_remaining.store(0);
    _jitter_amplitude.store(0);
    _mc_distance.store(0);
    _mc_speed.store(0);
    _mc_home_pin.store(-1);
    _steps_moved.store(0);
    _steps_frac.store(0);
    _brake_distance.store(0);
    _current_speed.store(0);
    _current_speed_frac.store(0);
}

bool Stepper::moveSteps(int32_t distance) {
    if (_jitter_active.load()) return false; // Don't interrupt an in-flight jitter
    if (_state != STEPPER_STOPPED) return false; // Only allow new move when stopped
    // From this point we assume we start from a standstill
    if (distance == 0) return true; // No move
    _mc_distance = (distance > 0) ? distance : -distance;
    _mc_dir.store((distance > 0) ? 1 : -1);
    _mc_speed = -1; // Not a speed move
    _mc_home_pin.store(-1); // Not homing
    // Initialize motion state
    _current_speed = _min_speed; // Start from minimum speed
    _current_speed_frac = 0;
    _current_dir.store(_mc_dir.load());
    _steps_moved = 0;
    _steps_frac = 0;
    _brake_distance = _mc_distance / 2; // Initially set braking point to half way (true if we never reach max speed)
    _state = STEPPER_ACCELERATING;
    return true;
}

bool Stepper::moveAtSpeed(int32_t speed) {
    // A jitter is owned by core1 and always runs to completion; reject any speed
    // command (including a stop) while one is active so core0 never mutates the
    // jitter's motion state underneath the relaunching strokes. The UI "stop"
    // instead cuts driver current (DRV_SET_ENABLED false) — the jitter then
    // finishes its remaining strokes silently against a de-energized driver.
    if (_jitter_active.load()) return false;
    if (speed == 0) {
        _mc_speed = 0;
        _mc_distance = -1;
        _mc_home_pin.store(-1);
        _mc_dir.store(_current_dir.load());
        _steps_moved = 0;
        _steps_frac = 0;
        if (_state == STEPPER_STOPPED) {
            _current_speed = 0;
            _current_speed_frac = 0;
            return true;
        }
        _state = STEPPER_BRAKING;
        return true;
    }

    _mc_dir.store((speed > 0) ? 1 : -1);
    _mc_speed = (speed > 0) ? speed : -speed;
    _mc_distance = 0;
    // Limit maximum speed
    if (_mc_speed > STEPPER_MAX_SPEED) {
        _mc_speed = STEPPER_MAX_SPEED;
    }
    _mc_distance = -1; // Not a distance move
    _mc_home_pin.store(-1); // Abort homing if we were homing
    // Determine if the stepper needs to reverse direction, go faster or slower
    if (_state == STEPPER_STOPPED) {
        _current_dir.store(_mc_dir.load());
        _current_speed = _min_speed; // Start from minimum speed
        _current_speed_frac = 0;
        _state = STEPPER_ACCELERATING;
    } else if (_current_speed == _mc_speed && _current_dir == _mc_dir.load()) {
        // Already at target speed and direction, force cruise
        _state = STEPPER_CRUISING;
    } else if (_current_dir != _mc_dir.load()) {
        // Need to reverse direction, enter braking state to slow down to zero first
        _state = STEPPER_BRAKING;
    } else if (_current_speed > _mc_speed) {
        // Need to brake to lower speed
        _state = STEPPER_BRAKING;
    } else {
        // Can accelerate to target speed
        _state = STEPPER_ACCELERATING;
    }
    // Reset Step couter for this new move
    _steps_moved = 0;
    _steps_frac = 0;
    return true;
}

bool Stepper::jitter(int32_t amplitude, int32_t cycles, int32_t speed, int32_t accel) {
    if (_jitter_active.load()) return false; // Reject overlapping jitter; let the current one finish
    if (_state != STEPPER_STOPPED) return false; // Only start from standstill
    if (amplitude <= 0 || cycles <= 0 || speed <= 0 || accel <= 0) return false;
    // Snapshot the normal motion params so we can put them back when the jitter
    // finishes — the jitter's fast accel/speed must not leak into later moves.
    _saved_accel = _accel;
    _saved_max_speed = _max_speed;
    _saved_min_speed = _min_speed;
    setAcceleration((uint32_t)accel);
    setSpeedLimits(_min_speed, (uint32_t)speed);
    _jitter_amplitude.store(amplitude);
    _jitter_strokes_remaining.store(cycles * 2); // each cycle = forward + back
    _jitter_dir.store(1);
    _jitter_active.store(true);
    beginJitterStroke();
    return true;
}

// Launch a single jitter stroke as a distance move, reusing the accel/brake
// machinery. Unlike moveSteps() this does not touch the jitter bookkeeping, so
// the STOPPED handler in motion_update_tick() can chain the next stroke.
void Stepper::beginJitterStroke() {
    int32_t amp = _jitter_amplitude.load();
    // Defensive: never start a zero-length distance move (it would never satisfy
    // _steps_moved >= _mc_distance and would cruise forever).
    if (amp <= 0) {
        _state = STEPPER_STOPPED;
        _jitter_strokes_remaining.store(0);
        _jitter_amplitude.store(0);
        _jitter_active.store(false);
        return;
    }
    int32_t dir = _jitter_dir.load();
    _mc_distance = amp;
    _mc_dir.store(dir);
    _mc_speed = -1; // Not a speed move
    _mc_home_pin.store(-1);
    _current_speed = _min_speed;
    _current_speed_frac = 0;
    _current_dir.store(dir);
    _steps_moved = 0;
    _steps_frac = 0;
    _brake_distance = amp / 2;
    _state = STEPPER_ACCELERATING;
}

void Stepper::home(int32_t home_speed, int home_pin, bool home_pin_polarity) {
    moveAtSpeed(home_speed);
    _mc_home_pin.store(home_pin);
    _mc_home_pin_polarity.store(home_pin_polarity);
}

/*! \brief Step generator tick
 *
 *  This function should be called at a fixed rate defined by STEP_TICK_RATE_HZ.
 *  It generates step pulses based on the current speed of the stepper. 
 *  Will stop the motor if the target position is reached.
 * 
 *  Due to the high calling frequency, this function should return as quickly as possible.
 */
void Stepper::stepgen_tick() {
    if (_state == STEPPER_STOPPED) return; // Return fast if stopped
    // Check home switch at 10kHz - catches narrow optical endstops
    int home_pin = _mc_home_pin.load();
    if (home_pin >= 0) {
        if (gpio_get(home_pin) == _mc_home_pin_polarity.load()) {
            _state = STEPPER_STOPPED;
            _current_speed = 0;
            _absolute_position = 0;
            _mc_home_pin.store(-1);
            return;
        }
    }
    // Set direction pin
    gpio_put(_dir_pin, (_current_dir > 0) ? 1 : 0);
    // Advance step counter by fractional steps
    _steps_frac += _current_speed;
    // If one or more steps ready, issue them
    while (_steps_frac >= STEP_TICK_RATE_HZ || _steps_frac <= -STEP_TICK_RATE_HZ) {
        // Step
        gpio_put(_step_pin, 1);
        busy_wait_at_least_cycles(25); // Minimum pulse width is 100ns, 1 cycle is 8ns at 125MHz, 25 cycles is 200ns
        gpio_put(_step_pin, 0);
        busy_wait_at_least_cycles(25); // Minimum pulse spacing is 100ns, use 200ns for safety
        // Update fractional step counter and total steps moved
        if (_steps_frac >= STEP_TICK_RATE_HZ) {
            _steps_frac -= STEP_TICK_RATE_HZ;
        } else if (_steps_frac <= -STEP_TICK_RATE_HZ) {
            _steps_frac += STEP_TICK_RATE_HZ;
        }
        // And the move counter
        _steps_moved += _current_dir * _mc_dir.load();
        // Update absolute position
        _absolute_position += _current_dir;
        if (_mc_distance > 0) {
            // Distance move, check if done
            if (_steps_moved >= _mc_distance) {
                // Move complete
                _state = STEPPER_STOPPED;
                _current_speed = 0;
                break;
            }
        }
    }
}


/*! \brief Motion update tick
 *
 *  This function should be called at a fixed rate defined by STEP_MOTION_UPDATE_RATE_HZ.
 *  It updates the motion parameters (speed, acceleration, state transitions) of the stepper.
 */
void Stepper::motion_update_tick() {
    // StallGuard: the TMC2209 holds DIAG high while it reads a stall (SG_RESULT
    // <= 2*SGTHRS above the TCOOLTHRS velocity floor). When armed, latch it and
    // stop immediately — the backend poll then raises an operator incident.
    // Skip while jittering: the unstick wiggle is *meant* to fight load, and a
    // stall during it is expected, not a fault.
    if (_stall_enabled.load() && _stall_pin >= 0 && _state.load() != STEPPER_STOPPED &&
        !_jitter_active.load() && gpio_get(_stall_pin)) {
        _stalled.store(true);
        _state.store(STEPPER_STOPPED);
        _current_speed.store(0);
        _current_speed_frac.store(0);
        return;
    }
    switch (_state) {
        case STEPPER_STOPPED:
            // Chain the next jitter stroke if one is pending. A completed stroke
            // lands here (stepgen sets STOPPED); we flip direction and relaunch
            // until all strokes are done, leaving net displacement at zero. The
            // last stroke clears _jitter_active, which re-opens jitter()/moves.
            if (_jitter_strokes_remaining.load() > 0) {
                int32_t rem = _jitter_strokes_remaining.load() - 1;
                _jitter_strokes_remaining.store(rem);
                if (rem > 0) {
                    _jitter_dir.store(-_jitter_dir.load());
                    beginJitterStroke();
                } else {
                    _jitter_amplitude.store(0);
                    _jitter_active.store(false);
                    // Jitter done: put the normal motion params back so the next
                    // ordinary move uses them, not the jitter's fast accel/speed.
                    _accel = _saved_accel;
                    _max_speed = _saved_max_speed;
                    _min_speed = _saved_min_speed;
                }
            }
            break;
        case STEPPER_ACCELERATING: {
            // Increase speed
            _current_speed_frac += _accel;
            _current_speed += _current_speed_frac / STEP_MOTION_UPDATE_RATE_HZ;
            _current_speed_frac = _current_speed_frac % STEP_MOTION_UPDATE_RATE_HZ;
            
            if ((_mc_speed > 0) && (_current_speed >= _mc_speed)) {
                // Is speed move and reached target speed
                _current_speed.store(_mc_speed.load());
                _current_speed_frac = 0;
                _state = STEPPER_CRUISING;
            } else if ((_mc_speed < 0) && (_current_speed.load() >= (int32_t)_max_speed)) {
                // Is distance move and reached max speed
                _current_speed = _max_speed;
                _current_speed_frac = 0;
                // It should take the same amount of steps to brake as to accelerate, so calculate braking point
                _brake_distance = _mc_distance - _steps_moved;
                _state = STEPPER_CRUISING;
            }
            // Fall through to cruising to check for braking point
        case STEPPER_CRUISING:
            // Check home switch if homing
            if (_mc_home_pin.load() >= 0) {
                if (gpio_get(_mc_home_pin.load()) == _mc_home_pin_polarity.load()) {
                    // Home switch triggered, stop now and set position to zero
                    _state = STEPPER_STOPPED;
                    _current_speed = 0;
                    _absolute_position = 0;
                    _mc_home_pin.store(-1); // Homing done
                    break;
                }
            }
            // Check if we need to brake
            if ((_steps_moved >= _brake_distance) && (_mc_distance > 0)) {
                // Need to brake to stop at target
                _state = STEPPER_BRAKING;
            }
            break;
        case STEPPER_BRAKING: {
            // Decrease speed
            _current_speed_frac += _accel;
            _current_speed -= _current_speed_frac / STEP_MOTION_UPDATE_RATE_HZ;
            _current_speed_frac = _current_speed_frac % STEP_MOTION_UPDATE_RATE_HZ;
            // Dont allow the speed to go below the minimum. _min_speed MUST be
            // cast to signed here: _current_speed can step below zero when one
            // brake tick (_accel / update rate) is larger than the remaining
            // speed, and a signed/unsigned comparison would promote the
            // negative speed to a huge unsigned value — the catch never fires,
            // BRAKING keeps subtracting forever, and the motor accelerates
            // unbounded (runaway) until power-cut.
            if (_current_speed.load() <= (int32_t)_min_speed) {
                _current_speed = _min_speed;
                _current_speed_frac = 0;
                // Check if we are reversing a speed move, in that case, flip the direction and accelerate!
                if ((_mc_speed > 0) && (_current_dir != _mc_dir.load())) {
                    // Reached zero speed, now reverse direction
                    _current_dir.store(_mc_dir.load());
                    _steps_frac = -_steps_frac; // Invert fractional step counter to match new direction
                    _state = STEPPER_ACCELERATING;
                } else if (_mc_speed == 0) {
                    // Zero speed move and reached minimum speed, stop now
                    _state = STEPPER_STOPPED;
                } else {
                    // Speed move and reached minimum speed, cruise
                    _state = STEPPER_CRUISING;
                }
            }
            // Reached target speed on a speed move? Cruise
            if ((_mc_speed > 0) && (_mc_dir.load() == _current_dir) && (_current_speed >= _mc_speed)) {
                _current_speed.store(_mc_speed.load());
                _current_speed_frac = 0;
                _state = STEPPER_CRUISING;
            }
        }
            break;
        }
    }
}
