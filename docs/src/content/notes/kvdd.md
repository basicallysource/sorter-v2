---
title: A partial power stress run on Kitbash
type: reference
permalink: /n/kvdd/
slug: note-kvdd
kicker: Engineering notes — kvdd
lede: What one sorter drew from the wall while every stepper, servo and the chute ran at once, and what that says about sizing its power supply.
owner: hardware
audience: anyone sizing a sorter's power supply
applies_to: sorter v2 on the v1.3 distribution board
last_verified: 2026-08-25
---

On 25 August 2026 Kitbash (`spencer-02`) ran the backend's power stress test
with a smart plug measuring its wall draw. The run was cut short: 7 min 7 s of
the planned 10 min completed. It still gives a useful provisional envelope.

Across the 427 seconds, wall draw averaged **62.9 W**, reached **68.3 W at the
95th percentile**, and peaked at **69.9 W**, about **7.45 Wh** in all. The run
stopped because the firmware rejected a command to move servo channel 2 to 0°,
not because of power: the plug read 62.9 W at 118.0 V on that sample, and
Kitbash went back to `ready` with no hardware error.

This is not a completed worst-case qualification. Only 19 of the planned 200
mixed-mode seconds ran, the plug samples about once a second and can miss
shorter peaks, and the servos had no mechanical load.

<div class="img-row">
  <figure>
  <img src="https://assets.basically.website/sorter-docs/note-kvdd-wall-power-w1600-97b37c4df5aa.jpg" alt="Wall power over the run: a short spike for the first 12,000 microsteps per second attempt, then a plateau near 65 W through the stable phase, a slightly lower and noisier plateau through the random phase, and a drop to about 26 W after the servo rejection">
  <figcaption>Wall power through the run, about one reading a second, with the phases shaded.</figcaption>
  </figure>
</div>

## What ran

| Item | Setting |
| --- | ---: |
| Target duration | 600 s |
| General stepper speed | 6,000 microsteps/s |
| Chute speed | 3,000 microsteps/s |
| Chute maximum | 345° |
| Non-chute steppers | 4 |
| Servos | 3 |
| LED outputs | 2, full on during the run |
| Perception workers | 3 of 3 alive |
| Configured camera roles | 5 |
| Distribution firmware | `firmware/v0.8.0`, `distribution-v1-2` target |
| Run id | `9fafd9e1-178a-46bc-ba4d-00bd19981b29` |

The chute homed before motion began. The physical v1.3 distribution board
identifies as, and is released under, the `distribution-v1-2` firmware target.

## Wall power

| Window | Completed | Mean | Over the pre-run floor | P95 | Peak | Energy, about |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pre-run ready floor | 28 s sampled | 20.7 W | | 21.9 W | 22.0 W | 0.16 Wh |
| Preparation and chute home | 5.4 s | 24.8 W | +4.1 W | 25.9 W | 25.9 W | 0.03 Wh |
| Stable: all four steppers continuous, chute and servos sweeping | 201.1 s | **64.8 W** | **+44.1 W** | **69.0 W** | **69.9 W** | 3.60 Wh |
| Random: all four steppers bursting, chute and servos random | 200.9 s | 61.9 W | +41.2 W | 65.0 W | 67.9 W | 3.43 Wh |
| Mixed segment 1: two continuous and two burst steppers | 19.0 of 45 s | 63.6 W | +42.9 W | 66.9 W | 67.3 W | 0.33 Wh |
| **Whole main run** | **427.0 s** | **62.9 W** | **+42.2 W** | **68.3 W** | **69.9 W** | **7.45 Wh** |
| Post-run ready state | 55 s sampled | 25.6 W | +4.9 W | 26.6 W | 26.8 W | 0.38 Wh |

The plug held 117.9 to 118.5 V through the run. Mean AC input current was
0.883 A and the highest reading 0.975 A. Voltage times current gives about
104 VA mean and 115 VA peak; the gap to real watts is the load's power factor,
which matters for upstream AC wiring, a UPS or an inverter.

The highest sustained load was the stable phase, all four non-chute steppers
running continuously. Random stopping and starting did not exceed it at the
plug's one-second resolution.

## How the load is spread

<div class="img-row">
  <figure>
  <img src="https://assets.basically.website/sorter-docs/note-kvdd-power-profile-w1600-3049f57f11f2.jpg" alt="Left, box plots of power by mode: about 21 W ready, 25 W preparing, 65 W stable, 62 W random, 64 W mixed. Right, the load-duration curve: 68.3 W for 5% of samples, 63.3 W for half, 59.2 W for 95%">
  <figcaption>Power by sorter mode, and the share of the run spent at or above each load.</figcaption>
  </figure>
</div>

This was a sustained load, not one spike. Half the main-run samples were at or
above 63.3 W, a quarter at or above 65.0 W, and 5% at or above 68.3 W. Even 95%
were at or above 59.2 W; the low tail is preparation and the cleanup between
phases.

Stable continuous motion had a 65.0 W median and a 64.8 W mean, random burst
motion a 61.9 W median and mean. That 2.8 W difference between the modes is
more useful for sizing than the command rate.

## Power and what the sorter was doing

<div class="img-row">
  <figure>
  <img src="https://assets.basically.website/sorter-docs/note-kvdd-power-vs-activity-w1600-4dd7a199f3bf.jpg" alt="Three stacked charts over the run: wall power on top, the number of non-chute steppers moving in the middle (four throughout the stable phase, zero to four in the random phase), and commands per five seconds at the bottom, far more in the random phase">
  <figcaption>Wall power lined up with the actuator commands in the sorter's journal, commands counted in five-second bins.</figcaption>
  </figure>
</div>

The chart lines the plug's readings up with the `move_at_speed`, servo-target
and chute-move messages in the sorter's journal. Which non-chute steppers were
running was reconstructed from every nonzero and zero speed command.

| Mode | Non-chute steppers | Stepper start/stop commands | Servo target commands | Chute move commands | Mean power |
| --- | --- | ---: | ---: | ---: | ---: |
| Stable | all 4 moving continuously | 4 | 318 | 19 | 64.8 W |
| Random | 0 to 4 moving as bursts overlap | 946 | 473 | 172 | 61.9 W |
| Mixed, partial | 2 continuous plus 2 bursting | 41 | 42 | 1 | 63.6 W |

**Command count is not a power proxy.** Random mode sent far more commands
and drew less power than stable mode. Within the random and mixed runs,
one-second power against the number of non-chute steppers moving had a
Pearson `r` of about 0.04, no meaningful linear relationship at this
resolution: enabled drivers hold current while stopped, bursts change faster
than the plug integrates, and the chute and servo loads overlap.

The operating mode says more than individual commands: four continuously
moving steppers added about 2.8 W over burst mode, and both stayed on a 62 to
65 W plateau. Size a supply from the phase envelope and the observed peak, not
from a per-command estimate.

## Timeline

Warehouse time, EDT.

| Time | Event |
| --- | --- |
| 22:03:39 | First attempt at 12,000 microsteps/s started. |
| 22:03:44 | It stopped after 5.2 s on a stall on channel 4. It peaked at 59.6 W and never reached a steady state. |
| 22:04:18 | Main run at 6,000 microsteps/s started; chute homing began. |
| 22:04:23 | Chute home completed at 66.75°, LEDs set fully on, all three perception workers alive. Stable phase started. |
| 22:07:45 | Stable phase completed: 106 to 108 servo commands per channel, one continuous command per non-chute stepper. Random phase started. |
| 22:11:06 | Random phase completed: 233 to 241 stepper start/stop commands and 157 to 161 servo commands per channel. Mixed segment 1 started: channels 1 and 3 in bursts, 2 and 4 continuous, servos random, the chute sweeping. |
| 22:11:24 | Servo channel 2 was sent from 180° to 0°; the firmware rejected the command as busy or disabled. |
| 22:11:25 | The runner recorded the failure and cleaned up. |
| 22:11:29 | Wall draw was down to 26.4 W. |

## Why it stopped

The run ended on `Servo 2 rejected target 0`. The host had seen the servo as
stopped before sending the move, but the firmware refused it, and its answer
does not tell a transient busy state from a disabled one, so the firmware-side
cause is still open.

Nothing points at the incoming power:

- The plug read 118.0 V at the failure, inside the run's 117.9 to 118.5 V.
- Real power was still 62.9 W when the failure was recorded.
- No plug reading was missed during the test.
- Kitbash stayed online, cleanup ran, and the hardware returned to `ready` with
  no error.

The first attempt at 12,000 microsteps/s stopped on channel 4's stall guard.
The 6,000 microsteps/s run then carried all four steppers through the whole
stable and random phases, so 6,000 is the highest speed this session
demonstrated, not a physical or electrical maximum.

## What it means for the power supply

For one supply covering the same load as this outlet:

- **Measured wall peak:** 69.9 W real power, sampled once a second.
- **Provisional minimum:** 100 W continuous, about 43% over the measured peak.
- **Provisional preference:** 120 W continuous, about 72% over the peak, for
  transients shorter than a second, loaded servos and the mixed sequence that
  did not run.
- **Upstream AC or UPS:** at least 115 VA from the measured voltage times
  current, plus the usual design margin.

This does not settle the current any single DC rail needs. The plug measures
the whole AC input: the Orange Pi, cameras, NPU, lighting, servos, motor
electronics and conversion losses. Choosing the DC supply still needs output
voltage and rail current measured, or a known rail layout and efficiency
budget.

## Limits of the measurement

- The plug samples about once a second. Shorter motor and servo transients can
  go above 69.9 W.
- It measures one outlet: Kitbash and its distribution motor rail. Anything
  powered from another outlet is not in it.
- The mixed phase ran for 19 seconds, and four later mixed segments did not
  run: about 70% of the scheduled motion completed.
- The servos were driven but mechanically free. Installed mechanisms can draw
  more servo current.
- Each plug reading is timed when it arrived, so it lines up with the machine's
  events to within about a second.

The run's own records are the backend's power stress runs
`85a0595f-48e1-4509-9ff0-5795daafcd27` and
`9fafd9e1-178a-46bc-ba4d-00bd19981b29`, the sorter journal for 22:03 to 22:12
EDT, and about 700 one-second plug readings covering the test and the baseline
around it.

## Next measurement

Once the servo rejection is handled, repeat the 600-second run at 6,000
microsteps/s, and treat the result as final only after all five mixed segments
complete. If the supply decision lands close to this envelope, measure rail
current at a higher rate before going below the 120 W provisional figure.

<div class="callout">
  <p>This note is permanent and is not edited after the fact. If the situation
  changes, a new note supersedes it and this one stays where it is.</p>
</div>
