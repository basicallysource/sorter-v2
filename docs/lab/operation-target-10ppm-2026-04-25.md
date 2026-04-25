---
title: Operation Target 10 PPM
type: working-note
audience: contributors tuning the live sorter runtime
applies_to: sorter-v2
owner: lab
last_verified: 2026-04-25
section: lab
slug: operation-target-10ppm-2026-04-25
kicker: Lab - Runtime Target
lede: A concrete operating target for the current live tuning phase: ten cleanly classified and distributed LEGO pieces per minute without relying on harsh C4 acceleration.
permalink: /lab/operation-target-10ppm-2026-04-25/
---

## Target

Reach a sustained operating point where the sorter cleanly classifies and distributes **10 pieces per minute** from C4 into the distributor.

The target is about stable end-to-end flow, not peak burst speed. A run only counts when pieces are:

1. tracked through the C-channel and C4 runtime path without identity churn causing operational confusion;
2. classified with a usable result;
3. handed from C4 into the distributor;
4. physically delivered without C4 overfill, repeated jams, or obvious pile-up behavior.

## Success definition

| Metric | Target |
| --- | --- |
| End-to-end throughput | >= 10 distributed pieces/min over a measured run |
| Confirmation window | First prove it on short 30-60 s runs, then on 3-5 min runs |
| C3 density | roughly 8-12 visible pieces, not clumped at one exit/intake area |
| C4 density | roughly 8-12 visible pieces, evenly spread enough for tracking and classifier capture |
| Classification | no large backlog of registered-but-unclassified pieces |
| Distributor | no sustained distributor_busy bottleneck or repeated failed handoffs |
| Mechanical smoothness | C4 motion remains audibly and visibly smooth |

## Non-goals

- Do not chase 10 PPM by making C4 acceleration harsh.
- Do not accept high C4 pile-up just because throughput briefly rises.
- Do not tune from UI impressions alone; every change needs a measured before/after.
- Do not reintroduce old tracker stacks for production runtime. BoxMot plus the stable piece layer remains the intended path.

## Preferred tuning levers

Tune in this order:

1. **Backpressure and density**
   - C2 max piece count
   - C3 max piece count
   - C3->C4 virtual slot allowance
   - C4 max zones

2. **Pulse timing**
   - C2 pulse cooldown
   - C3 pulse cooldown
   - C4 transport cooldown

3. **Gentle transport speed**
   - C4 target rpm
   - C4 transport speed scale
   - C4 transport step and max step

4. **Only last: acceleration**
   - Keep C4 transport acceleration conservative by default.
   - Raising acceleration is allowed only for a measured reason and should be rolled back if the motion sounds or looks aggressive.

## Current C4 motion baseline

As of 2026-04-25, the intended C4 baseline is:

| Field | Value |
| --- | --- |
| transport_step_deg | 3.0 |
| transport_max_step_deg | 8.0 |
| transport_cooldown_s | 0.18 |
| transport_target_rpm | 0.7 |
| transport_speed_scale | 4.0 |
| transport_acceleration_usteps_per_s2 | 4000 |
| startup_purge_speed_scale | 4.0 |
| startup_purge_acceleration_usteps_per_s2 | 20000 |
| stepper_degrees_per_tray_degree | 36.0 read-only hardware calibration |

## Test protocol

Each tuning iteration should be small:

1. Capture `/api/system/status`, `/api/rt/status`, `/api/rt/tuning`, and current C2/C3/C4 track snapshots.
2. Run a short observed test window.
   - Start with 30-60 s while behavior is uncertain.
   - Move to 3-5 min only after C4 flow is stable.
3. Record:
   - distributed pieces/min;
   - classified pieces/min;
   - registered piece backlog;
   - C2/C3/C4 live track counts;
   - C3/C4 density and clump symptoms;
   - blocked reasons from runtime status;
   - any audible or visible harsh motion.
4. Change one small cluster of related parameters.
5. Repeat and compare to the previous run.

## Density heuristic

The desired physical state is not "as empty as possible" and not "as full as possible".

Good:

- C3 and C4 show multiple separated pieces across the tray.
- The exits are fed regularly, but not buried.
- Pieces have enough spacing that tracking can hold stable identities.
- C4 has enough candidates to keep the classifier and distributor busy.

Bad:

- C2 stores a pile because the bulk bucket dumped too much at once.
- C3 exit area repeatedly forms a clump.
- C4 contains many pieces in one arc and empty space elsewhere.
- C4 must use harsh or frequent recovery motion to keep up.

## Stop conditions

Pause or back off immediately when:

- C4 starts visibly overfilling;
- C4 stepper motion sounds aggressive again;
- distributor handoff failures repeat;
- runtime blocked reasons stay stuck instead of cycling;
- track counts explode relative to visible pieces;
- pieces are being classified but not physically distributed.

## Working hypothesis

The path to 10 PPM is likely not higher C4 acceleration. It is a better density gradient:

**C2 buffers gently -> C3 singulates and spaces -> C4 stays moderately populated -> classifier and distributor remain continuously fed.**

That means the main work is runtime tuning plus observability around density, not simply making each motor faster.
