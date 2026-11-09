/*
 * Sorter Interface Firmware - Serial Servo Guard Implementation
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

#include "ServoGuard.h"

// Registers both Feetech series share. They differ in byte order, in the range of
// a position, and in how a goal is written.
static const uint8_t REG_TORQUE = 40;
static const uint8_t REG_STS_GOAL = 41; // Acceleration, then position, time and speed
static const uint8_t REG_SC_GOAL = 42;  // Position, time and speed
static const uint8_t REG_PRESENT = 56;  // Position, speed and load, two bytes each
static const uint8_t PRESENT_BYTES = 6;
static const uint8_t STATUS_OVERLOAD = 1 << 5;

static const uint16_t SC_MAX_RAW = 1023;
static const uint16_t STS_MAX_RAW = 4095;

static const uint32_t SAMPLE_PERIOD_US = 10000;
static const uint8_t LOST_AFTER_MISSES = 3;
// A back-off's time to finish before the servo is let go.
static const uint32_t RELEASE_DELAY_US = 250000;
// Samples in a row that must say a probing servo is held: one alone can be its
// own start-up friction.
static const uint8_t PROBE_HELD_SAMPLES = 2;
// Periods a probe waits at its limit for the servo to catch up or be held.
static const uint8_t PROBE_SETTLE_SAMPLES = 10;
static const uint32_t PROBE_SHORTEST_PERIOD_US = 5000;

static inline bool reached(uint32_t now_us, uint32_t when_us) { return (int32_t)(now_us - when_us) >= 0; }
static inline uint16_t get16(const uint8_t *bytes) { return (uint16_t)(bytes[0] | (bytes[1] << 8)); }
static inline void put16(uint8_t *bytes, uint16_t value) {
    bytes[0] = (uint8_t)(value & 0xFF);
    bytes[1] = (uint8_t)(value >> 8);
}
static inline int magnitude(int value) { return value < 0 ? -value : value; }

ServoGuardMove ServoGuardMove::parse(const uint8_t *payload) {
    ServoGuardMove move;
    move.flags = payload[0];
    move.goal = get16(payload + 1);
    move.time_ms = get16(payload + 3);
    move.speed = get16(payload + 5);
    move.accel = payload[7];
    move.stall_load = get16(payload + 8);
    move.stall_ms = get16(payload + 10);
    move.flat = payload[12];
    move.arrived = payload[13];
    move.backoff = get16(payload + 14);
    move.timeout_ms = get16(payload + 16);
    return move;
}

ServoGuardProbe ServoGuardProbe::parse(const uint8_t *payload) {
    ServoGuardProbe probe;
    probe.flags = payload[0];
    probe.direction = (int8_t)payload[1];
    probe.step = payload[2];
    probe.period_ms = payload[3];
    probe.limit = get16(payload + 4);
    probe.lag = get16(payload + 6);
    probe.load = get16(payload + 8);
    probe.backoff = get16(payload + 10);
    return probe;
}

void ServoGuardReport::pack(uint8_t *payload) const {
    payload[0] = state;
    put16(payload + 1, position);
    put16(payload + 3, (uint16_t)load);
    put16(payload + 5, mark);
    put16(payload + 7, peak_load);
    put16(payload + 9, elapsed_ms);
}

ServoGuard::ServoGuard(ServoWire &wire) : _wire(wire) {}

bool ServoGuard::active(const Slot &slot) {
    return slot.used && (slot.state == SERVO_GUARD_MOVING || slot.state == SERVO_GUARD_PROBING);
}

uint16_t ServoGuard::maxRaw(const Slot &slot) { return (slot.flags & SERVO_GUARD_FLAG_SC) ? SC_MAX_RAW : STS_MAX_RAW; }

ServoGuard::Slot *ServoGuard::find(uint8_t id) {
    for (Slot &slot : _slots) {
        if (slot.used && slot.id == id) {
            return &slot;
        }
    }
    return nullptr;
}

const ServoGuard::Slot *ServoGuard::find(uint8_t id) const {
    for (const Slot &slot : _slots) {
        if (slot.used && slot.id == id) {
            return &slot;
        }
    }
    return nullptr;
}

/*! \brief The slot a new move of this servo takes
 *
 *  Its own if it has one, a free one, or one whose servo has finished. A servo
 *  still moving, or waiting to be let go, keeps its slot.
 */
ServoGuard::Slot *ServoGuard::claim(uint8_t id) {
    if (Slot *own = find(id)) {
        return own;
    }
    for (Slot &slot : _slots) {
        if (!slot.used) {
            return &slot;
        }
    }
    for (Slot &slot : _slots) {
        if (!active(slot) && !slot.release_pending) {
            return &slot;
        }
    }
    return nullptr;
}

/*! \brief Read where the servo is and how hard it is working
 *
 *  \return 0, or the wire's error.
 */
int ServoGuard::readPresent(Slot &slot, uint8_t *status) {
    const uint8_t params[] = {REG_PRESENT, PRESENT_BYTES};
    uint8_t data[PRESENT_BYTES];
    const int result = _wire.transact(slot.id, SERVO_BUS_INST_READ, params, sizeof(params), data, sizeof(data));
    if (result < 0) {
        return result;
    }
    uint16_t position;
    uint16_t load_word;
    if (slot.flags & SERVO_GUARD_FLAG_SC) {
        position = (uint16_t)(((data[0] << 8) | data[1]) & 0x3FF);
        load_word = (uint16_t)((data[4] << 8) | data[5]);
    } else {
        position = get16(data);
        // Bit 15 is the sign, in a multi-turn mode a guarded servo is not in.
        position = (position & 0x8000) ? 0 : (position > STS_MAX_RAW ? STS_MAX_RAW : position);
        load_word = get16(data + 4);
    }
    // 0 to 1000, with bit 10 the direction.
    int16_t load = (int16_t)(load_word & 0x3FF);
    if (load_word & 0x400) {
        load = (int16_t)-load;
    }
    slot.position = position;
    slot.load = load;
    if ((uint16_t)magnitude(load) > slot.peak_load) {
        slot.peak_load = (uint16_t)magnitude(load);
    }
    if (status != nullptr) {
        *status = (uint8_t)result;
    }
    return 0;
}

int ServoGuard::writeGoal(const Slot &slot, uint16_t position, uint16_t time_ms, uint16_t speed, uint8_t accel) {
    uint8_t params[8];
    size_t length;
    if (slot.flags & SERVO_GUARD_FLAG_SC) {
        params[0] = REG_SC_GOAL;
        params[1] = (uint8_t)(position >> 8);
        params[2] = (uint8_t)(position & 0xFF);
        params[3] = (uint8_t)(time_ms >> 8);
        params[4] = (uint8_t)(time_ms & 0xFF);
        params[5] = (uint8_t)(speed >> 8);
        params[6] = (uint8_t)(speed & 0xFF);
        length = 7;
    } else {
        params[0] = REG_STS_GOAL;
        params[1] = accel;
        put16(params + 2, position);
        put16(params + 4, 0);
        put16(params + 6, speed);
        length = 8;
    }
    const int result = _wire.transact(slot.id, SERVO_BUS_INST_WRITE, params, length, nullptr, 0);
    return result < 0 ? result : 0;
}

int ServoGuard::writeTorque(uint8_t id, bool on) {
    const uint8_t params[] = {REG_TORQUE, (uint8_t)(on ? 1 : 0)};
    const int result = _wire.transact(id, SERVO_BUS_INST_WRITE, params, sizeof(params), nullptr, 0);
    return result < 0 ? result : 0;
}

/*! \brief Send a servo to a position and watch it until it gets there or cannot
 *
 *  The goal is written before the torque comes on, so a servo that was let go
 *  starts toward this goal and not toward an older one.
 */
int ServoGuard::move(uint8_t id, const ServoGuardMove &move, uint32_t now_us) {
    Slot *slot = claim(id);
    if (slot == nullptr) {
        return SERVO_GUARD_FULL;
    }
    *slot = Slot();
    slot->id = id;
    slot->flags = move.flags;
    int result = readPresent(*slot, nullptr);
    if (result == 0) {
        slot->goal = move.goal > maxRaw(*slot) ? maxRaw(*slot) : move.goal;
        result = writeGoal(*slot, slot->goal, move.time_ms, move.speed, move.accel);
    }
    if (result == 0) {
        result = writeTorque(id, true);
    }
    if (result < 0) {
        return result;
    }
    slot->used = true;
    slot->state = SERVO_GUARD_MOVING;
    slot->start = slot->position;
    slot->stall_ref = slot->position;
    slot->peak_load = 0;
    slot->stall_load = move.stall_load;
    slot->stall_us = (uint32_t)move.stall_ms * 1000;
    slot->flat = move.flat;
    slot->arrived = move.arrived;
    slot->backoff = move.backoff;
    slot->timeout_us = (uint32_t)move.timeout_ms * 1000;
    slot->began_us = now_us;
    slot->next_sample_us = now_us + SAMPLE_PERIOD_US;
    return 0;
}

/*! \brief Creep toward a limit until something holds the servo
 *
 *  The torque comes on with the goal where the servo already is, so nothing
 *  jumps. From there the goal moves one step each period.
 */
int ServoGuard::probe(uint8_t id, const ServoGuardProbe &probe, uint32_t now_us) {
    Slot *slot = claim(id);
    if (slot == nullptr) {
        return SERVO_GUARD_FULL;
    }
    *slot = Slot();
    slot->id = id;
    slot->flags = probe.flags;
    int result = readPresent(*slot, nullptr);
    if (result == 0) {
        result = writeGoal(*slot, slot->position, 0, 0, 0);
    }
    if (result == 0) {
        result = writeTorque(id, true);
    }
    if (result < 0) {
        return result;
    }
    slot->used = true;
    slot->state = SERVO_GUARD_PROBING;
    slot->start = slot->position;
    slot->goal = slot->position;
    slot->peak_load = 0;
    slot->direction = probe.direction < 0 ? -1 : 1;
    slot->step = probe.step == 0 ? 1 : probe.step;
    slot->period_us = (uint32_t)probe.period_ms * 1000;
    if (slot->period_us < PROBE_SHORTEST_PERIOD_US) {
        slot->period_us = PROBE_SHORTEST_PERIOD_US;
    }
    slot->limit = probe.limit > maxRaw(*slot) ? maxRaw(*slot) : probe.limit;
    slot->lag = probe.lag;
    slot->stall_load = probe.load;
    slot->backoff = probe.backoff;
    slot->began_us = now_us;
    slot->next_sample_us = now_us + slot->period_us;
    return 0;
}

int ServoGuard::stop(uint8_t id, bool release, uint32_t now_us) {
    (void)now_us;
    if (id == SERVO_BUS_BROADCAST_ID) {
        for (Slot &slot : _slots) {
            slot = Slot();
        }
        return writeTorque(SERVO_BUS_BROADCAST_ID, false);
    }
    Slot was;
    Slot *slot = find(id);
    const bool watched = slot != nullptr;
    if (watched) {
        was = *slot;
        *slot = Slot();
    }
    if (release) {
        return writeTorque(id, false);
    }
    if (!watched) {
        return 0; // Not moving through the guard: nothing of its to stop
    }
    const int result = readPresent(was, nullptr);
    return result < 0 ? result : writeGoal(was, was.position, 0, 0, 0);
}

void ServoGuard::forget(uint8_t id) {
    for (Slot &slot : _slots) {
        if (id == SERVO_BUS_BROADCAST_ID || (slot.used && slot.id == id)) {
            slot = Slot();
        }
    }
}

ServoGuardReport ServoGuard::report(uint8_t id, uint32_t now_us) const {
    ServoGuardReport report = {SERVO_GUARD_IDLE, 0, 0, 0, 0, 0};
    const Slot *slot = find(id);
    if (slot == nullptr) {
        return report;
    }
    const uint32_t elapsed_ms = ((active(*slot) ? now_us : slot->ended_us) - slot->began_us) / 1000;
    report.state = slot->state;
    report.position = slot->position;
    report.load = slot->load;
    report.mark = slot->mark;
    report.peak_load = slot->peak_load;
    report.elapsed_ms = elapsed_ms > 0xFFFF ? 0xFFFF : (uint16_t)elapsed_ms;
    return report;
}

void ServoGuard::end(Slot &slot, uint8_t state, uint32_t now_us) {
    slot.state = state;
    slot.ended_us = now_us;
    slot.stall_timing = false;
    if (state != SERVO_GUARD_ARRIVED && state != SERVO_GUARD_LOST && (slot.flags & SERVO_GUARD_FLAG_RELEASE_AFTER_BACKOFF)) {
        slot.release_pending = true;
        slot.release_at_us = now_us + RELEASE_DELAY_US;
    }
}

/*! \brief Send a held servo back the way it came, and say why it ended
 *
 *  \param toward +1 or -1: the direction away from what holds it.
 */
void ServoGuard::backOff(Slot &slot, int toward, uint8_t state, uint32_t now_us) {
    int target = (int)slot.position + toward * (int)slot.backoff;
    // A move never backs off past where it began.
    if (state == SERVO_GUARD_STALLED && slot.start != slot.position) {
        if ((toward > 0 && target > (int)slot.start) || (toward < 0 && target < (int)slot.start)) {
            target = slot.start;
        }
    }
    if (target < 0) {
        target = 0;
    } else if (target > (int)maxRaw(slot)) {
        target = maxRaw(slot);
    }
    slot.mark = slot.position;
    writeGoal(slot, (uint16_t)target, 0, 0, 0);
    end(slot, state, now_us);
}

void ServoGuard::holdHere(Slot &slot, uint8_t state, uint32_t now_us) {
    writeGoal(slot, slot.position, 0, 0, 0);
    end(slot, state, now_us);
}

void ServoGuard::sampleMove(Slot &slot, uint32_t now_us) {
    uint8_t status = 0;
    if (readPresent(slot, &status) < 0) {
        if (++slot.misses >= LOST_AFTER_MISSES) {
            end(slot, SERVO_GUARD_LOST, now_us);
        }
        return;
    }
    slot.misses = 0;
    if (magnitude((int)slot.position - (int)slot.goal) <= slot.arrived) {
        end(slot, SERVO_GUARD_ARRIVED, now_us);
        if (slot.flags & SERVO_GUARD_FLAG_RELEASE_ON_ARRIVAL) {
            writeTorque(slot.id, false);
        }
        return;
    }
    // The servo's own overload flag is a stall already. Short of that: loaded and
    // not moving for long enough.
    bool held = (status & STATUS_OVERLOAD) != 0;
    const bool loaded = magnitude(slot.load) >= (int)slot.stall_load;
    const bool still = magnitude((int)slot.position - (int)slot.stall_ref) < slot.flat;
    if (loaded && still) {
        if (!slot.stall_timing) {
            slot.stall_timing = true;
            slot.stall_since_us = now_us;
        } else if (reached(now_us, slot.stall_since_us + slot.stall_us)) {
            held = true;
        }
    } else {
        slot.stall_timing = false;
        slot.stall_ref = slot.position;
    }
    if (held) {
        int toward;
        if (slot.start != slot.position) {
            toward = slot.start > slot.position ? 1 : -1;
        } else {
            toward = slot.goal > slot.position ? -1 : 1;
        }
        backOff(slot, toward, SERVO_GUARD_STALLED, now_us);
        return;
    }
    if (slot.timeout_us != 0 && reached(now_us, slot.began_us + slot.timeout_us)) {
        holdHere(slot, SERVO_GUARD_TIMED_OUT, now_us);
    }
}

void ServoGuard::sampleProbe(Slot &slot, uint32_t now_us) {
    uint8_t status = 0;
    if (readPresent(slot, &status) < 0) {
        if (++slot.misses >= LOST_AFTER_MISSES) {
            end(slot, SERVO_GUARD_LOST, now_us);
        }
        return;
    }
    slot.misses = 0;
    // Held: behind its creeping goal by more than a free servo ever is, or working
    // hard. Either can come first, depending on what holds it.
    int behind = slot.direction > 0 ? (int)slot.goal - (int)slot.position : (int)slot.position - (int)slot.goal;
    if (behind < 0) {
        behind = 0;
    }
    const bool held = (status & STATUS_OVERLOAD) != 0 || behind >= (int)slot.lag ||
                      (slot.stall_load != 0 && magnitude(slot.load) >= (int)slot.stall_load);
    slot.held_samples = held ? (uint8_t)(slot.held_samples + 1) : 0;
    if (slot.held_samples >= PROBE_HELD_SAMPLES) {
        backOff(slot, -slot.direction, SERVO_GUARD_CONTACT, now_us);
        return;
    }
    if (slot.goal == slot.limit) {
        if (++slot.at_limit_samples >= PROBE_SETTLE_SAMPLES) {
            holdHere(slot, SERVO_GUARD_NO_CONTACT, now_us);
        }
        return;
    }
    int next = (int)slot.goal + slot.direction * (int)slot.step;
    if ((slot.direction > 0 && next > (int)slot.limit) || (slot.direction < 0 && next < (int)slot.limit)) {
        next = slot.limit;
    }
    slot.goal = (uint16_t)next;
    writeGoal(slot, slot.goal, 0, 0, 0);
}

void ServoGuard::tick(uint32_t now_us) {
    for (uint8_t offset = 0; offset < SERVO_GUARD_SLOTS; offset++) {
        const uint8_t index = (uint8_t)((_next_slot + offset) % SERVO_GUARD_SLOTS);
        Slot &slot = _slots[index];
        if (!slot.used) {
            continue;
        }
        if (slot.release_pending && reached(now_us, slot.release_at_us)) {
            slot.release_pending = false;
            writeTorque(slot.id, false);
        } else if (active(slot) && reached(now_us, slot.next_sample_us)) {
            if (slot.state == SERVO_GUARD_PROBING) {
                slot.next_sample_us = now_us + slot.period_us;
                sampleProbe(slot, now_us);
            } else {
                slot.next_sample_us = now_us + SAMPLE_PERIOD_US;
                sampleMove(slot, now_us);
            }
        } else {
            continue;
        }
        _next_slot = (uint8_t)((index + 1) % SERVO_GUARD_SLOTS);
        return;
    }
}
