/*
 * Sorter Interface Firmware - Serial Servo Guard Header
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

#ifndef SERVO_GUARD_H
#define SERVO_GUARD_H

#include "ServoWire.h"

const uint8_t SERVO_GUARD_SLOTS = 8; // Servos watched at once

const int SERVO_GUARD_FULL = -10; // Every slot holds a servo that is still moving

// The SC series: big-endian words, a goal with a time. Without it, the STS series:
// little-endian words, a goal with a speed and an acceleration.
const uint8_t SERVO_GUARD_FLAG_SC = 1 << 0;
// Let the servo go once it has arrived.
const uint8_t SERVO_GUARD_FLAG_RELEASE_ON_ARRIVAL = 1 << 1;
// Let the servo go once it has backed off or been stopped short.
const uint8_t SERVO_GUARD_FLAG_RELEASE_AFTER_BACKOFF = 1 << 2;

enum ServoGuardState : uint8_t {
    SERVO_GUARD_IDLE = 0,       // Not watched: never moved through the guard, or handed back
    SERVO_GUARD_MOVING = 1,     // On its way to the goal
    SERVO_GUARD_ARRIVED = 2,    // At the goal
    SERVO_GUARD_STALLED = 3,    // Met resistance on the way, and backed off
    SERVO_GUARD_TIMED_OUT = 4,  // Neither arrived nor stalled in time, and stopped where it was
    SERVO_GUARD_LOST = 5,       // Stopped answering
    SERVO_GUARD_PROBING = 6,    // Creeping toward a limit, feeling for resistance
    SERVO_GUARD_CONTACT = 7,    // A probe met resistance, and backed off
    SERVO_GUARD_NO_CONTACT = 8, // A probe reached its limit and met nothing
};

/** \brief A move the guard watches until it ends. */
struct ServoGuardMove {
    uint8_t flags;
    uint16_t goal;       // Position, in the servo's own counts
    uint16_t time_ms;    // SC: the move's time, 0 for as fast as it goes
    uint16_t speed;      // STS: counts a second, 0 for as fast as it goes
    uint8_t accel;       // STS: the acceleration register, 0 for none
    uint16_t stall_load; // Load, 0 to 1000, that with no motion is a stall
    uint16_t stall_ms;   // How long that must last
    uint8_t flat;        // Counts of motion below which it is not moving
    uint8_t arrived;     // Counts from the goal that are the goal
    uint16_t backoff;    // Counts to come back from where it stalled
    uint16_t timeout_ms; // Longest the move may take, 0 for no limit

    static const size_t BYTES = 18;
    static ServoGuardMove parse(const uint8_t *payload);
};

/** \brief A slow search for whatever stops the servo in one direction. */
struct ServoGuardProbe {
    uint8_t flags;
    int8_t direction;  // +1 toward higher counts, -1 toward lower
    uint8_t step;      // Counts the goal advances each period
    uint8_t period_ms; // How long each step lasts
    uint16_t limit;    // The position never to pass
    uint16_t lag;      // Counts behind its goal that mean it is held
    uint16_t load;     // Load, 0 to 1000, that means it is held
    uint16_t backoff;  // Counts to come back from where it was held

    static const size_t BYTES = 12;
    static ServoGuardProbe parse(const uint8_t *payload);
};

/** \brief What the guard knows of one servo. */
struct ServoGuardReport {
    uint8_t state;
    uint16_t position;   // As last read
    int16_t load;        // As last read, signed by direction
    uint16_t mark;       // Where it stalled or met resistance
    uint16_t peak_load;  // The most load seen since it began
    uint16_t elapsed_ms; // Since it began, until it ended

    static const size_t BYTES = 11;
    void pack(uint8_t *payload) const;
};

/** \brief Watches serial bus servos while they move, and stops one that meets resistance.
 *
 * A servo pushing against something it cannot move draws its stall current until
 * something lets go: it can break what it pushes, overheat, or pull the servo
 * supply down for everything else on it. The host may be busy for longer than
 * that takes, so the board watches. Each servo sent through move() is read every
 * 10 ms; one that is loaded and no longer moving, short of its goal, is sent back
 * the way it came and reported stalled.
 *
 * probe() finds an end of travel without ever pushing hard: the goal creeps a few
 * counts at a time, and the servo is taken to be held as soon as it falls behind
 * its goal or its load rises.
 *
 * Nothing here uses the Pico SDK: time comes in as microseconds, the bus as a
 * ServoWire.
 */
class ServoGuard {
  public:
    explicit ServoGuard(ServoWire &wire);

    /*! \return 0, or SERVO_GUARD_FULL, or the wire's error if the servo did not take it. */
    int move(uint8_t id, const ServoGuardMove &move, uint32_t now_us);
    int probe(uint8_t id, const ServoGuardProbe &probe, uint32_t now_us);
    /*! Stop watching and stop the servo: let it go, or hold it where it is.
     *  SERVO_BUS_BROADCAST_ID is every servo, and only lets go. */
    int stop(uint8_t id, bool release, uint32_t now_us);
    /*! The host wrote to this servo itself: it is no longer the guard's to judge. */
    void forget(uint8_t id);
    ServoGuardReport report(uint8_t id, uint32_t now_us) const;
    /*! Call often. Reads at most one servo a call. */
    void tick(uint32_t now_us);

  private:
    struct Slot {
        bool used = false;
        uint8_t id = 0;
        uint8_t state = SERVO_GUARD_IDLE;
        uint8_t flags = 0;
        uint16_t goal = 0;
        uint16_t start = 0;
        uint16_t position = 0;
        int16_t load = 0;
        uint16_t mark = 0;
        uint16_t peak_load = 0;
        uint16_t stall_load = 0;
        uint16_t backoff = 0;
        uint8_t flat = 0;
        uint8_t arrived = 0;
        uint8_t misses = 0;
        uint32_t stall_us = 0;
        uint32_t timeout_us = 0;
        uint16_t stall_ref = 0;
        bool stall_timing = false;
        uint32_t stall_since_us = 0;
        uint32_t began_us = 0;
        uint32_t ended_us = 0;
        uint32_t next_sample_us = 0;
        bool release_pending = false;
        uint32_t release_at_us = 0;
        // A probe
        int8_t direction = 0;
        uint8_t step = 0;
        uint32_t period_us = 0;
        uint16_t limit = 0;
        uint16_t lag = 0;
        uint8_t held_samples = 0;
        uint8_t at_limit_samples = 0;
    };

    ServoWire &_wire;
    Slot _slots[SERVO_GUARD_SLOTS];
    uint8_t _next_slot = 0;

    Slot *find(uint8_t id);
    const Slot *find(uint8_t id) const;
    Slot *claim(uint8_t id);
    static bool active(const Slot &slot);
    static uint16_t maxRaw(const Slot &slot);

    int readPresent(Slot &slot, uint8_t *status);
    int writeGoal(const Slot &slot, uint16_t position, uint16_t time_ms, uint16_t speed, uint8_t accel);
    int writeTorque(uint8_t id, bool on);

    void sampleMove(Slot &slot, uint32_t now_us);
    void sampleProbe(Slot &slot, uint32_t now_us);
    void backOff(Slot &slot, int toward, uint8_t state, uint32_t now_us);
    void holdHere(Slot &slot, uint8_t state, uint32_t now_us);
    void end(Slot &slot, uint8_t state, uint32_t now_us);
};

#endif // SERVO_GUARD_H
