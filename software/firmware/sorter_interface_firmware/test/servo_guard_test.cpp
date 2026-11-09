// Desk test of ServoGuard against pretend servos: no board, no SDK.
//
//   make test-servo-guard
//
// Each pretend servo is a position that chases its goal, held by an optional hard
// stop, with a load that grows with how far it is from its goal: enough to show
// that the guard arrives, stalls, backs off, probes and gives up when it should.

#include "../ServoGuard.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <map>

namespace {

struct PretendServo {
    bool sc = true;       // SC series (big endian, 0 to 1023), else STS
    bool answers = true;
    bool torque = false;
    double position = 500;
    int goal = 500;
    double speed = 600;       // Counts a second at full effort
    double stop_above = 1e9;  // A hard stop: the position cannot pass it going up
    double stop_below = -1e9; // And one going down
    int load = 0;
    int goal_writes = 0;

    void step(double seconds) {
        if (!torque) {
            load = 0;
            return;
        }
        const double error = goal - position;
        // Effort is proportional to the error, as a servo's own control is.
        const double effort = std::fmax(-1.0, std::fmin(1.0, error / 20.0));
        double next = position + effort * speed * seconds;
        if ((error > 0 && next > goal) || (error < 0 && next < goal)) {
            next = goal;
        }
        next = std::fmax(stop_below, std::fmin(stop_above, next));
        position = next;
        load = (int)std::lround(effort * 1000.0);
    }
};

class PretendWire : public ServoWire {
  public:
    std::map<int, PretendServo> servos;
    int transactions = 0;

    int transact(uint8_t id, uint8_t instruction, const uint8_t *params, size_t params_len, uint8_t *data,
                 size_t data_len) override {
        transactions++;
        if (id == SERVO_BUS_BROADCAST_ID) {
            for (auto &entry : servos) {
                apply(entry.second, instruction, params, params_len, nullptr, 0);
            }
            return 0;
        }
        auto found = servos.find(id);
        if (found == servos.end() || !found->second.answers) {
            return SERVO_BUS_NO_REPLY;
        }
        return apply(found->second, instruction, params, params_len, data, data_len);
    }

  private:
    static int apply(PretendServo &servo, uint8_t instruction, const uint8_t *params, size_t params_len, uint8_t *data,
                     size_t data_len) {
        if (instruction == SERVO_BUS_INST_WRITE) {
            const uint8_t address = params[0];
            if (address == 40) {
                servo.torque = params[1] != 0;
            } else if (address == 42 && servo.sc && params_len >= 3) {
                servo.goal = (params[1] << 8) | params[2];
                servo.goal_writes++;
            } else if (address == 41 && !servo.sc && params_len >= 4) {
                servo.goal = params[2] | (params[3] << 8);
                servo.goal_writes++;
            }
            return 0;
        }
        if (instruction == SERVO_BUS_INST_READ && params[0] == 56 && data_len == 6) {
            const int position = (int)std::lround(servo.position);
            const int load_word = (std::abs(servo.load) & 0x3FF) | (servo.load < 0 ? 0x400 : 0);
            if (servo.sc) {
                data[0] = (uint8_t)(position >> 8);
                data[1] = (uint8_t)(position & 0xFF);
                data[4] = (uint8_t)(load_word >> 8);
                data[5] = (uint8_t)(load_word & 0xFF);
            } else {
                data[0] = (uint8_t)(position & 0xFF);
                data[1] = (uint8_t)(position >> 8);
                data[4] = (uint8_t)(load_word & 0xFF);
                data[5] = (uint8_t)(load_word >> 8);
            }
            data[2] = data[3] = 0;
            return 0;
        }
        return 0;
    }
};

int failures = 0;

void check(bool ok, const char *what, double got = 0) {
    if (!ok) {
        failures++;
        std::printf("FAIL %s (got %g)\n", what, got);
    }
}

// The whole bench: the wire, the guard and a clock that both live on.
struct Bench {
    PretendWire wire;
    ServoGuard guard{wire};
    uint32_t now_us = 4000000000u; // Near the 32-bit wrap, which the guard must survive

    void run(int milliseconds) {
        for (int ms = 0; ms < milliseconds; ms++) {
            for (auto &entry : wire.servos) {
                entry.second.step(0.001);
            }
            now_us += 1000;
            guard.tick(now_us);
        }
    }
    int state(int id) { return guard.report((uint8_t)id, now_us).state; }
};

ServoGuardMove moveTo(int goal, uint8_t flags = SERVO_GUARD_FLAG_SC) {
    ServoGuardMove move = {};
    move.flags = flags;
    move.goal = (uint16_t)goal;
    move.stall_load = 400;
    move.stall_ms = 150;
    move.flat = 3;
    move.arrived = 8;
    move.backoff = 30;
    move.timeout_ms = 4000;
    return move;
}

ServoGuardProbe probeToward(int direction, int limit, uint8_t flags = SERVO_GUARD_FLAG_SC) {
    ServoGuardProbe probe = {};
    probe.flags = flags;
    probe.direction = (int8_t)direction;
    probe.step = 3;
    probe.period_ms = 20;
    probe.limit = (uint16_t)limit;
    probe.lag = 12;
    probe.load = 700;
    probe.backoff = 15;
    return probe;
}

void aFreeMoveArrivesAndLetsGo() {
    Bench bench;
    bench.wire.servos[1].position = 300;
    check(bench.guard.move(1, moveTo(640, SERVO_GUARD_FLAG_SC | SERVO_GUARD_FLAG_RELEASE_ON_ARRIVAL), bench.now_us) == 0,
          "free move accepted");
    check(bench.state(1) == SERVO_GUARD_MOVING, "free move is moving", bench.state(1));
    bench.run(2500);
    check(bench.state(1) == SERVO_GUARD_ARRIVED, "free move arrived", bench.state(1));
    check(!bench.wire.servos[1].torque, "let go on arrival");
    check(std::fabs(bench.wire.servos[1].position - 640) <= 8, "ended at the goal", bench.wire.servos[1].position);
}

void aMoveIntoAStopStallsAndBacksOff() {
    Bench bench;
    PretendServo &servo = bench.wire.servos[2];
    servo.position = 300;
    servo.stop_above = 520;
    check(bench.guard.move(2, moveTo(700), bench.now_us) == 0, "blocked move accepted");
    bench.run(700);
    // 220 counts at 600 a second, then 150 ms held: inside 700 ms.
    check(bench.state(2) == SERVO_GUARD_STALLED, "blocked move stalled", bench.state(2));
    const ServoGuardReport report = bench.guard.report(2, bench.now_us);
    check(std::abs((int)report.mark - 520) <= 2, "stall marked at the stop", report.mark);
    check(report.peak_load >= 400, "peak load seen", report.peak_load);
    check(servo.goal == 490, "goal set back 30 counts toward the start", servo.goal);
    bench.run(300);
    check(std::fabs(servo.position - 490) <= 2, "backed off", servo.position);
    check(servo.torque, "holds after backing off unless asked to let go");
}

void aStallCanLetGoAfterBackingOff() {
    Bench bench;
    PretendServo &servo = bench.wire.servos[3];
    servo.position = 600;
    servo.stop_below = 450;
    check(bench.guard.move(3, moveTo(200, SERVO_GUARD_FLAG_SC | SERVO_GUARD_FLAG_RELEASE_AFTER_BACKOFF), bench.now_us) == 0,
          "blocked downward move accepted");
    bench.run(500);
    check(bench.state(3) == SERVO_GUARD_STALLED, "downward move stalled", bench.state(3));
    check(servo.goal == 480, "backed off upward", servo.goal);
    check(servo.torque, "still driving while it backs off");
    bench.run(300);
    check(!servo.torque, "let go once backed off");
}

void aBackOffNeverPassesTheStart() {
    Bench bench;
    PretendServo &servo = bench.wire.servos[4];
    servo.position = 500;
    servo.stop_above = 510;
    check(bench.guard.move(4, moveTo(700), bench.now_us) == 0, "short blocked move accepted");
    bench.run(500);
    check(bench.state(4) == SERVO_GUARD_STALLED, "short move stalled", bench.state(4));
    check(servo.goal == 500, "backs off to the start, no further", servo.goal);
}

void aProbeFindsAStop() {
    Bench bench;
    PretendServo &servo = bench.wire.servos[5];
    servo.position = 400;
    servo.stop_above = 655;
    check(bench.guard.probe(5, probeToward(1, 1023), bench.now_us) == 0, "probe accepted");
    check(servo.torque && servo.goal == 400, "probe starts holding where it is", servo.goal);
    bench.run(4000);
    check(bench.state(5) == SERVO_GUARD_CONTACT, "probe found the stop", bench.state(5));
    const ServoGuardReport report = bench.guard.report(5, bench.now_us);
    check(std::abs((int)report.mark - 655) <= 2, "contact marked at the stop", report.mark);
    check(report.peak_load < 1000, "never pushed with everything it has", report.peak_load);
    check(std::fabs(servo.position - 640) <= 3, "came back 15 counts", servo.position);
}

void aProbeDownwardFindsAStop() {
    Bench bench;
    PretendServo &servo = bench.wire.servos[6];
    servo.position = 400;
    servo.stop_below = 210;
    check(bench.guard.probe(6, probeToward(-1, 0), bench.now_us) == 0, "downward probe accepted");
    bench.run(4000);
    check(bench.state(6) == SERVO_GUARD_CONTACT, "downward probe found the stop", bench.state(6));
    check(std::abs((int)bench.guard.report(6, bench.now_us).mark - 210) <= 2, "downward contact marked",
          bench.guard.report(6, bench.now_us).mark);
}

void aProbeWithNothingInItsWayReachesItsLimit() {
    Bench bench;
    PretendServo &servo = bench.wire.servos[7];
    servo.position = 400;
    check(bench.guard.probe(7, probeToward(1, 520), bench.now_us) == 0, "free probe accepted");
    bench.run(3000);
    check(bench.state(7) == SERVO_GUARD_NO_CONTACT, "free probe reached its limit", bench.state(7));
    check(std::fabs(servo.position - 520) <= 3, "stopped at the limit", servo.position);
}

void aServoThatStopsAnsweringIsLost() {
    Bench bench;
    bench.wire.servos[8].position = 300;
    check(bench.guard.move(8, moveTo(700), bench.now_us) == 0, "move accepted");
    bench.run(50);
    bench.wire.servos[8].answers = false;
    const int goal_writes = bench.wire.servos[8].goal_writes;
    bench.run(200);
    check(bench.state(8) == SERVO_GUARD_LOST, "silent servo is lost", bench.state(8));
    check(bench.wire.servos[8].goal_writes == goal_writes, "nothing written to a lost servo");
}

void aServoThatIsNotThereIsRefused() {
    Bench bench;
    check(bench.guard.move(9, moveTo(500), bench.now_us) == SERVO_BUS_NO_REPLY, "absent servo refused");
    check(bench.state(9) == SERVO_GUARD_IDLE, "absent servo is not watched", bench.state(9));
}

void aTooSlowMoveTimesOutWhereItIs() {
    Bench bench;
    PretendServo &servo = bench.wire.servos[10];
    servo.position = 100;
    servo.speed = 300; // Moving all the while, but 900 counts take three seconds
    ServoGuardMove move = moveTo(1000);
    move.timeout_ms = 1000;
    check(bench.guard.move(10, move, bench.now_us) == 0, "slow move accepted");
    bench.run(1200);
    check(bench.state(10) == SERVO_GUARD_TIMED_OUT, "slow move timed out", bench.state(10));
    check(std::abs(servo.goal - (int)std::lround(servo.position)) <= 2, "held where it was", servo.goal);
}

void theHostTakingOverEndsTheWatch() {
    Bench bench;
    bench.wire.servos[11].position = 300;
    check(bench.guard.move(11, moveTo(700), bench.now_us) == 0, "move accepted");
    bench.guard.forget(11);
    check(bench.state(11) == SERVO_GUARD_IDLE, "forgotten servo is idle", bench.state(11));
    const int transactions = bench.wire.transactions;
    bench.run(100);
    check(bench.wire.transactions == transactions, "a forgotten servo is not read");
}

void stopLetsGoOrHolds() {
    Bench bench;
    PretendServo &held = bench.wire.servos[12];
    held.position = 300;
    check(bench.guard.move(12, moveTo(900), bench.now_us) == 0, "move accepted");
    bench.run(200);
    check(bench.guard.stop(12, false, bench.now_us) == 0, "stop and hold accepted");
    check(std::abs(held.goal - (int)std::lround(held.position)) <= 1, "held where it stopped", held.goal);
    check(held.torque, "still holding");
    check(bench.guard.stop(SERVO_BUS_BROADCAST_ID, true, bench.now_us) == 0, "stop all accepted");
    check(!held.torque, "stop all lets every servo go");
}

void theOtherSeriesReadsTheOtherWay() {
    Bench bench;
    PretendServo &servo = bench.wire.servos[13];
    servo.sc = false;
    servo.position = 1000;
    servo.speed = 3000;
    servo.stop_above = 2600;
    ServoGuardMove move = moveTo(3000, 0);
    move.speed = 2000;
    move.accel = 50;
    move.backoff = 100;
    check(bench.guard.move(13, move, bench.now_us) == 0, "STS move accepted");
    bench.run(1500);
    check(bench.state(13) == SERVO_GUARD_STALLED, "STS move stalled", bench.state(13));
    check(std::abs((int)bench.guard.report(13, bench.now_us).mark - 2600) <= 2, "STS stall marked",
          bench.guard.report(13, bench.now_us).mark);
    check(servo.goal == 2500, "STS backed off", servo.goal);
}

void moreServosThanSlotsAreRefusedOnlyWhileAllMove() {
    Bench bench;
    for (int id = 20; id < 20 + SERVO_GUARD_SLOTS + 1; id++) {
        bench.wire.servos[id].position = 100;
        bench.wire.servos[id].speed = 50;
    }
    for (int id = 20; id < 20 + SERVO_GUARD_SLOTS; id++) {
        check(bench.guard.move((uint8_t)id, moveTo(900), bench.now_us) == 0, "slot taken");
    }
    const int extra = 20 + SERVO_GUARD_SLOTS;
    check(bench.guard.move((uint8_t)extra, moveTo(900), bench.now_us) == SERVO_GUARD_FULL, "ninth moving servo refused");
    bench.guard.stop(20, true, bench.now_us);
    check(bench.guard.move((uint8_t)extra, moveTo(900), bench.now_us) == 0, "a freed slot is taken");
    // All eight are read in turn: none starves.
    bench.run(100);
    for (int id = 21; id <= extra; id++) {
        check(bench.guard.report((uint8_t)id, bench.now_us).position > 100, "every watched servo is read", id);
    }
}

void thePayloadsParseAsDocumented() {
    const uint8_t move_bytes[ServoGuardMove::BYTES] = {0x03, 0x34, 0x02, 0xE8, 0x03, 0x00, 0x00, 0x07, 0x90,
                                                       0x01, 0x96, 0x00, 3,    8,    30,   0,    0xA0, 0x0F};
    const ServoGuardMove move = ServoGuardMove::parse(move_bytes);
    check(move.flags == 3 && move.goal == 0x234 && move.time_ms == 1000 && move.speed == 0 && move.accel == 7,
          "move head parsed");
    check(move.stall_load == 400 && move.stall_ms == 150 && move.flat == 3 && move.arrived == 8 && move.backoff == 30 &&
              move.timeout_ms == 4000,
          "move tail parsed");
    const uint8_t probe_bytes[ServoGuardProbe::BYTES] = {0x01, 0xFF, 3, 20, 0x00, 0x00, 12, 0, 0xBC, 0x02, 15, 0};
    const ServoGuardProbe probe = ServoGuardProbe::parse(probe_bytes);
    check(probe.direction == -1 && probe.step == 3 && probe.period_ms == 20 && probe.limit == 0 && probe.lag == 12 &&
              probe.load == 700 && probe.backoff == 15,
          "probe parsed");
    ServoGuardReport report = {SERVO_GUARD_STALLED, 520, -431, 519, 1000, 345};
    uint8_t packed[ServoGuardReport::BYTES];
    report.pack(packed);
    check(packed[0] == 3 && packed[1] == 0x08 && packed[2] == 0x02 && packed[3] == 0x51 && packed[4] == 0xFE &&
              packed[9] == 0x59 && packed[10] == 0x01,
          "report packed");
}

} // namespace

int main() {
    aFreeMoveArrivesAndLetsGo();
    aMoveIntoAStopStallsAndBacksOff();
    aStallCanLetGoAfterBackingOff();
    aBackOffNeverPassesTheStart();
    aProbeFindsAStop();
    aProbeDownwardFindsAStop();
    aProbeWithNothingInItsWayReachesItsLimit();
    aServoThatStopsAnsweringIsLost();
    aServoThatIsNotThereIsRefused();
    aTooSlowMoveTimesOutWhereItIs();
    theHostTakingOverEndsTheWatch();
    stopLetsGoOrHolds();
    theOtherSeriesReadsTheOtherWay();
    moreServosThanSlotsAreRefusedOnlyWhileAllMove();
    thePayloadsParseAsDocumented();
    if (failures == 0) {
        std::printf("servo guard: all checks passed\n");
        return 0;
    }
    std::printf("servo guard: %d checks failed\n", failures);
    return 1;
}
