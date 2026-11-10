// The step clock, on this computer: no board. Build and run with `make test-step-clock`.
//
// Each check drives a StepClock the way the firmware's step interrupt does: look,
// make the steps that are due, then come back when the clock says the next one is,
// or at the poll period, whichever is sooner.

#include "../StepClock.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <vector>

static int failures = 0;

#define CHECK(condition, ...)                                                                                          \
    do {                                                                                                               \
        if (!(condition)) {                                                                                            \
            failures++;                                                                                                \
            std::printf("FAILED %s:%d: ", __FILE__, __LINE__);                                                         \
            std::printf(__VA_ARGS__);                                                                                  \
            std::printf("\n");                                                                                         \
        }                                                                                                              \
    } while (0)

static const uint32_t POLL_US = 100;
static const int MAX_BURST = 4;

// Runs a clock for `duration_us` and returns the time of every step. `speed_at`
// is the motor's speed at a time. `late_us` is how long after the asked-for
// moment each look really happens.
static std::vector<uint32_t> run(uint32_t start_us, uint32_t duration_us, const std::function<uint32_t(uint32_t)> &speed_at,
                                 uint32_t late_us = 3) {
    StepClock clock;
    std::vector<uint32_t> steps;
    uint32_t elapsed = 0;
    while (elapsed < duration_us) {
        const uint32_t now = start_us + elapsed;
        const uint32_t speed = speed_at(elapsed);
        clock.advance(now, speed);
        for (int made = 0; clock.due(); made++) {
            if (made == MAX_BURST) {
                clock.dropBacklog();
                break;
            }
            steps.push_back(elapsed);
            clock.stepped();
        }
        uint32_t wait = clock.waitUs(speed);
        if (wait > POLL_US) {
            wait = POLL_US;
        }
        elapsed += wait + late_us;
    }
    return steps;
}

static void intervals(const std::vector<uint32_t> &steps, uint32_t *shortest, uint32_t *longest) {
    *shortest = 0xFFFFFFFF;
    *longest = 0;
    for (size_t i = 1; i < steps.size(); i++) {
        const uint32_t gap = steps[i] - steps[i - 1];
        if (gap < *shortest) *shortest = gap;
        if (gap > *longest) *longest = gap;
    }
}

static void steadySpeedsStepEvenly() {
    // 3000 and 4000 are the ones a 10 kHz tick made worst: 300/400 and 200/300 in turn.
    const uint32_t speeds[] = {16, 300, 800, 1600, 2000, 3000, 4000, 7777, 20000, 60000};
    for (uint32_t speed : speeds) {
        const std::vector<uint32_t> steps = run(0, 2000000, [speed](uint32_t) { return speed; });
        uint32_t shortest, longest;
        intervals(steps, &shortest, &longest);
        const double ideal = 1000000.0 / speed;
        // A look is up to 3 us late, and a step is placed on a whole microsecond.
        CHECK(shortest + 5 >= ideal && longest <= ideal + 5, "%u steps/s: steps %u to %u us apart, should all be %.1f", speed,
              shortest, longest, ideal);
        const double expected = 2.0 * speed;
        CHECK(steps.size() + 2 >= expected && steps.size() <= expected + 2, "%u steps/s: %zu steps in 2 s, expected %.0f",
              speed, steps.size(), expected);
    }
}

static void aRampStartsAtOnceAndOnlyGetsFaster() {
    // From 16 steps a second up by 10000 steps/s^2, as a move starts: the speed is
    // set once a millisecond.
    auto speed_at = [](uint32_t elapsed_us) {
        const uint32_t speed = 16 + (elapsed_us / 1000) * 10;
        return speed > 3000 ? 3000u : speed;
    };
    const std::vector<uint32_t> steps = run(0, 600000, speed_at);
    CHECK(!steps.empty() && steps[0] < 20000, "the first step of a ramp came at %u us, not within 20 ms",
          steps.empty() ? 0 : steps[0]);
    for (size_t i = 2; i < steps.size(); i++) {
        const uint32_t before = steps[i - 1] - steps[i - 2];
        const uint32_t gap = steps[i] - steps[i - 1];
        CHECK(gap <= before + 5, "step %zu of a ramp came %u us after one that came %u us after its own", i, gap, before);
    }
}

static void aLateLookFallsBehindInsteadOfBursting() {
    StepClock clock;
    clock.advance(1000, 3000);
    clock.advance(1000 + 50000, 3000); // Away for 50 ms: 150 steps would be owed
    int made = 0;
    while (clock.due() && made < MAX_BURST) {
        clock.stepped();
        made++;
    }
    clock.dropBacklog();
    CHECK(made == MAX_BURST, "a late look made %d steps, not the %d it may", made, MAX_BURST);
    CHECK(clock.waitUs(3000) >= 1 && clock.waitUs(3000) <= 2, "after a late look the next step is due in %u us, not at once",
          clock.waitUs(3000));
}

static void aStoppedMotorStartsAFreshStep() {
    StepClock clock;
    clock.advance(0, 1000);
    clock.advance(900, 1000); // Nine tenths of the way through a step
    clock.stop();
    clock.advance(5000, 1000);
    CHECK(!clock.due(), "a step was due the moment a stopped motor started");
    CHECK(clock.waitUs(1000) == 1000, "a restarted motor's first step is due in %u us, not a whole step", clock.waitUs(1000));
}

static void aStandstillWaitsForever() {
    StepClock clock;
    clock.advance(0, 0);
    clock.advance(100000, 0);
    CHECK(!clock.due(), "a step came due at a standstill");
    CHECK(clock.waitUs(0) == StepClock::NEVER, "a standstill does not wait forever");
}

static void theClockRunsAcrossTheTimersWrap() {
    // The 32-bit microsecond time wraps every 71 minutes.
    const std::vector<uint32_t> steps = run(0xFFFFFFFF - 500000, 1000000, [](uint32_t) { return 3000u; });
    uint32_t shortest, longest;
    intervals(steps, &shortest, &longest);
    CHECK(shortest >= 329 && longest <= 339, "across the wrap the steps were %u to %u us apart", shortest, longest);
}

int main() {
    steadySpeedsStepEvenly();
    aRampStartsAtOnceAndOnlyGetsFaster();
    aLateLookFallsBehindInsteadOfBursting();
    aStoppedMotorStartsAFreshStep();
    aStandstillWaitsForever();
    theClockRunsAcrossTheTimersWrap();
    if (failures == 0) {
        std::printf("step clock: all checks passed\n");
        return 0;
    }
    std::printf("step clock: %d checks failed\n", failures);
    return 1;
}
