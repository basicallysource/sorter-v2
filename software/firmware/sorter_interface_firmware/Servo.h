#include <atomic>
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

#ifndef SERVO_H
#define SERVO_H
#include <stdint.h>

#define SERVO_UPDATE_RATE_HZ 100 // How often to update servo motion state

// Default maximum time (in milliseconds) we will ever leave PWM enabled for a
// MOVE_TO_AND_RELEASE command before forcing the servo to release. This is the
// hard safety net that guarantees we stop driving the servo even if the motion
// profile never "arrives" at the target in simulation (stalled, blocked, slow
// mechanical response, etc.).
//
// The redesign of MOVE_TO_AND_RELEASE guarantees two things:
//   1. Best-effort nice release at the end of the normal trapezoidal profile.
//   2. Unconditional release after this wall-clock deadline, no matter what.
//
// This replaces the previous behavior where a MOVE_TO_AND_RELEASE could fail to
// release (command rejected while not idle, or simulation never reached target).
#define SERVO_DEFAULT_MAX_RELEASE_DURATION_MS 3500

enum ServoState {
    SERVO_IDLE,
    SERVO_ACCELERATING,
    SERVO_CRUISING,
    SERVO_BRAKING,
    SERVO_DISABLED
};

class Servo {
public:
    Servo();
    bool moveTo(uint16_t position);
    bool moveToAndRelease(uint16_t position, uint16_t max_duration_ms = 0);
    void setSpeedLimits(uint16_t min_speed, uint16_t max_speed) { _min_speed = min_speed; _max_speed = max_speed; }
    void setDutyCycleLimits(uint16_t min_duty, uint16_t max_duty) { _min_duty = min_duty; _max_duty = max_duty; }
    void setAcceleration(uint16_t acceleration) { _acceleration = acceleration; }
    bool isStopped() const { return _state == SERVO_IDLE || _state == SERVO_DISABLED; }
    void stopMotion();
    void setEnabled(bool enabled);
    void update();
    uint16_t getCurrentPosition() const { return _current_pos; }
    uint16_t getCurrentDuty() const { return _current_duty; }
private:
    std::atomic<ServoState> _state;
    std::atomic<int16_t> _move_start_pos; // Position at the start of the current move, used for acceleration calculations
    std::atomic<int16_t> _current_pos, _current_pos_frac; // Current position, fractional part for acceleration calculations
    std::atomic<int16_t> _target_pos, _brake_pos; // Target position and point at which to start braking
    std::atomic<int16_t> _current_speed, _current_speed_frac; // Speed in units of position per second, fractional part for acceleration calculations
    int16_t _current_dir; // 1 = forward, -1 = reverse
    int16_t _max_speed, _min_speed;
    uint16_t _acceleration;
    bool _release_on_idle; // If true, auto-disable the servo when it reaches its target position (profile-based path)
    uint16_t _min_duty, _max_duty; // Minimum and maximum duty cycle corresponding to 0 and 180 degree positions
    uint16_t _current_duty; // Current duty cycle being output to the servo

    // Hard wall-clock deadline (in microseconds, from time_us_64) after which we
    // *always* force the servo to DISABLED + duty=0, regardless of simulated position.
    // 0 means "no pending forced release". This guarantees that MOVE_TO_AND_RELEASE
    // will never leave the servo driving indefinitely.
    uint64_t _release_deadline_us;
};

#endif // SERVO_H