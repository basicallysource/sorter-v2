/*
 * Sorter Interface Firmware - Servo Motion Controller
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

#include "Servo.h"

Servo::Servo()
        : _state(SERVO_DISABLED), _move_start_pos(0), _current_pos(0), _current_pos_frac(0), _target_pos(0), _brake_pos(0),
            _current_speed(0), _current_speed_frac(0), _max_speed(3750), _min_speed(50), _acceleration(100), _min_duty(102),
            _max_duty(512), _current_duty(0) {
}

/** \brief Move the servo to a specified position
 *
 * The servo will accelerate from its current position to the target position at the configured acceleration rate, up to
 * the configured maximum speed, and then decelerate to a stop at the target position. If the servo is currently moving,
 * this function will return false and the move command will be ignored. If the servo is disabled, it will update the
 * current position to the target position and return true, allowing you to set the current position for when you enable
 * the servo again.
 *
 * \param position Target position in units of 0.1 degree (0-1800 for 0-180 degrees)
 * \return true if the move was successfully started, false if the servo is currently moving and cannot accept a new
 * move command
 */
bool Servo::moveTo(uint16_t position) {
    if (_state == SERVO_DISABLED) {
        _current_pos = position; // Update current position to target when disabled so we start from the correct
                                 // position when enabled again
        return true;             // Allow move command when disabled to set the current position for when we enable
    }
    if (_state != SERVO_IDLE)
        return false; // Only allow new move when idle
    // Limit position to valid range
    if (position > 1800)
        position = 1800;
    if (position == _current_pos)
        return true; // No move needed
    _target_pos = position;
    int16_t distance = (int16_t)_target_pos - (int16_t)_current_pos;
    int16_t direction = (distance > 0) ? 1 : -1;
    _current_speed = _min_speed;
    _current_speed_frac = 0;
    _current_dir = direction;
    _move_start_pos.store(_current_pos.load());
    // Start braking at the half way point between current and target position
    _brake_pos = _current_pos + distance / 2;
    _state = SERVO_ACCELERATING;
    return true;
}

/** \brief Update the servo's position and state
 *
 * This function should be called at a fixed rate defined by SERVO_UPDATE_RATE_HZ. It updates the servo's position based
 * on the current speed and direction, checks for state transitions (acceleration, cruising, braking), and updates the
 * PWM signal accordingly.
 */
void Servo::update() {
    _current_pos_frac += _current_speed;
    if (_current_pos_frac >= SERVO_UPDATE_RATE_HZ) {
        _current_pos += (_current_pos_frac / SERVO_UPDATE_RATE_HZ) * _current_dir;
        _current_pos_frac = _current_pos_frac % SERVO_UPDATE_RATE_HZ;
    }
    // Check if we've reached or passed the target position and need to stop
    if (_current_dir > 0 && _current_pos >= _target_pos) {
        _current_pos.store(_target_pos.load());
        _state = SERVO_IDLE;
    } else if (_current_dir < 0 && _current_pos <= _target_pos) {
        _current_pos.store(_target_pos.load());
        _state = SERVO_IDLE;
    }
    // Update the PWM signal based on the current state and position
    if (_state == SERVO_DISABLED) {
        _current_duty = 0; // No signal when disabled
    } else {
        // Map the current position to a duty cycle between _min_duty and _max_duty
        int new_duty = _min_duty + (_max_duty - _min_duty) * _current_pos / 1800;
        if (new_duty < _min_duty)
            new_duty = _min_duty;
        if (new_duty > _max_duty)
            new_duty = _max_duty;
        _current_duty = new_duty;
    }
    // Update motion state based on current speed and position
    switch (_state) {
    case SERVO_DISABLED:
        return; // No update when disabled
    case SERVO_IDLE:
        return; // No update needed when idle
    case SERVO_ACCELERATING:
        // Accelerate towards max speed
        _current_speed_frac += _acceleration;
        if (_current_speed_frac >= SERVO_UPDATE_RATE_HZ) {
            _current_speed += _current_speed_frac / SERVO_UPDATE_RATE_HZ;
            _current_speed_frac = _current_speed_frac % SERVO_UPDATE_RATE_HZ;
            if (_current_speed > _max_speed) {
                _current_speed = _max_speed;
                _state = SERVO_CRUISING;
                auto distance_traveled = _current_pos - _move_start_pos;
                // Should take the same distance to decelerate from max speed to stop as it took to accelerate from stop
                // to max speed, so we start braking at the point where we've traveled the distance required to brake
                // from max speed
                _brake_pos = _target_pos - distance_traveled;
            }
        }
        // Fall through to check for brake point
    case SERVO_CRUISING:
        // Check if we need to start braking
        if ((_current_dir > 0 && _current_pos >= _brake_pos) || (_current_dir < 0 && _current_pos <= _brake_pos)) {
            _state = SERVO_BRAKING;
        }
        break;
    case SERVO_BRAKING:
        // Decelerate towards stop
        _current_speed_frac += _acceleration;
        if (_current_speed_frac >= SERVO_UPDATE_RATE_HZ) {
            _current_speed -= _current_speed_frac / SERVO_UPDATE_RATE_HZ;
            _current_speed_frac = _current_speed_frac % SERVO_UPDATE_RATE_HZ;
            if (_current_speed < _min_speed) {
                _current_speed = _min_speed;
            }
        }
        break;
    }
}

/** \brief Stop the servo's motion immediately
 *
 * This will transition the servo to the idle state and set speed to zero. The servo will hold its current position
 * since the PWM signal will still be updated based on the current position, but any ongoing move command will be
 * aborted.
 */
void Servo::stopMotion() {
    _state = SERVO_IDLE;
    _current_speed = 0;
    _current_speed_frac = 0;
    _current_dir = 0;
}

/** \brief Enable or disable the servo
 *
 * When disabled, the servo will not respond to move commands and the PWM signal will be turned off. When enabled, the
 * servo will transition to the idle state and can accept move commands.
 *
 * If the servo was previously moving when set to disabled, it will stop immediately and lose its current position. When
 * re-enabled, it will start from its current position.
 *
 * \param enabled true to enable the servo, false to disable it
 */
void Servo::setEnabled(bool enabled) {
    if (enabled) {
        // Only do something if we were previously disabled.
        if (_state == SERVO_DISABLED) {
            _state = SERVO_IDLE; // Transition to idle when enabled
        }
    } else {
        stopMotion();
        _state = SERVO_DISABLED;
        _current_duty = 0;
    }
}