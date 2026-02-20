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
    bool isStopped() { return _state == STEPPER_STOPPED; }
    int32_t getPosition() { return _absolute_position; }
    void setPosition(int32_t position) { _absolute_position = position; }
    void home(int32_t home_speed, int home_pin, bool home_pin_polarity);

private:
    // Pins for the step generator
    int _step_pin, _dir_pin;
    // Motion parameters
    uint32_t _accel;
    uint32_t _max_speed, _min_speed;
    
    // Last commanded state
    StepperState _state;
    int32_t _mc_distance; // Always positive, direction in _move_dir
    int32_t _mc_speed; // Always positive, direction in _move_dir
    int32_t _mc_dir; // 1 = forward, -1 = reverse
    int32_t _mc_home_pin; // Home switch pin, -1 if not homing
    bool _mc_home_pin_polarity; // Home switch polarity, true if active high, false if active low

    // Internal state
    int32_t _steps_moved, _steps_frac; // How many steps have we moved in the current move, counted towards the _move_direction (if moving backwards we go negative)
    int32_t _brake_distance; // Distance required to brake to a stop from current speed, decision point for braking
    int32_t _current_speed, _current_speed_frac; // Always positive, direction in _current_dir
    int32_t _current_dir; // 1 = forward, -1 = reverse
    int32_t _absolute_position;
};

#endif // STEPPER_H