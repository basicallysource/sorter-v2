---
title: C-channel singulation
type: explanation
audience: contributor understanding the core mechanical innovation
applies_to: hardware-v2
owner: lab
last_verified: 2026-04-14
section: lab
slug: lab-c-channel-singulation
kicker: Lab — Research Area
lede: How the Sorter V2 separates tangled LEGO into single pieces using rotating C-shaped channels — a novel approach with no known published precedent.
permalink: /lab/c-channel-singulation/
---

## The question

How does Sorter V2 singulate LEGO pieces without vibration?

Traditional part feeders use vibration (bowl feeders, V-channels) to separate tangled parts. Vibration works but is loud, hard to control, and assumes roughly uniform part geometry. LEGO pieces vary wildly in size and shape. The project needed a quieter, more controllable alternative.

## The mental model

A C-channel stage has two parts: a **faceted rotor** (not round) with an angled inner cone, and a **static outer stator wall**. Together they form a C-shaped channel that pieces sit in. When the rotor turns, pieces are pushed outward along the channel toward an exit guide.

The key insight: **the drops between stages are the primary separation mechanism**, not the rotation itself. Each inter-stage drop has a probability of untangling clumped pieces. Stack three stages and the probability of a clump surviving all three drops converges toward zero.

> "You can actually take the entire v-channel concept and make it circular." — Spencer
>
> "We found a way to do v-channels through circular motion without vibration. I have not found/seen anything like this online." — Marc

## How it works

| Component | Details |
|-----------|---------|
| Stages | 3 in series (2 likely sufficient; 3 is safety margin) |
| Cameras | 3× OV9732 100° wide-angle, one centered above each channel |
| Calibration | ArUco 4×4 tags (3D-printable, two-color) define center, exit, and bulk boundary |
| Piece tracking | OpenCV MOG2 background subtraction — no training data needed |
| Anti-jam | 5-level escalating algorithm: progressively stronger back-and-forth shaking |
| Color calibration | CIELAB comparison with reference card, UVC control adjustments |
| Lighting | 50mm COB PCB LED in vertical post at center of each channel, side-mounted |

### Control loop

1. Camera detects pieces via MOG2 pixel-diff tracking.
2. Rotor advances until pieces reach the exit zone.
3. If a clump is detected (multiple contours too close), rotor reverses briefly.
4. Anti-jam escalation kicks in if reversal fails — five levels of increasingly aggressive shaking.
5. Single piece exits to the next stage or to the classification chamber.

## Performance

| Metric | Value |
|--------|-------|
| Current throughput | ~330 pieces/hour (5.5 PPM over 42-minute sustained run) |
| MVP target | 360 pieces/hour (6 PPM) — **achieved March 2026** |
| Ultimate target | 1,000 pieces/hour (~17 PPM) |
| Theoretical ceiling | ~20 PPM before carousel bottleneck |
| Bottleneck | Feeder physics, not software or classification |
| Singulation confidence (3 stages) | >99% |

## Trade-offs

- **C-channels vs V-channels** — V-channels use vibration for natural agitation but are loud. C-channels are quieter and more controllable via software, but require more physical length (3 stages) to achieve equivalent separation confidence.
- **Circular vs linear** — Circular motion gives a smaller footprint and simpler overhead camera geometry (no perspective skew). Linear paths would need longer travel distance.
- **2 vs 3 stages** — Two stages likely suffice for most loads. The third stage is a safety margin that the team kept because the cost (one more rotor + camera) is low relative to the confidence gain.
- **MOG2 vs YOLO for tracking** — MOG2 background subtraction is faster, needs no training data, and works well for the fixed-camera setup. YOLO would be overkill for binary piece-present detection.

## What this is not

- **Not a general-purpose part feeder.** The C-channel design assumes LEGO-sized pieces (~50mm sphere max). Industrial bowl feeders handle a broader size range.
- **Not vibration-free in all configurations.** The feeder upstream of the C-channels may still use vibration to move bulk LEGO into the first stage.
- **Not a published research result.** This is empirical engineering — the design emerged from iterative prototyping, not from simulation or academic study.

## Where to go next

- [Feeder experiments]({{ '/lab/feeder-experiments/' | relative_url }}) — the turntable and vibration approaches that preceded C-channels
- [Object detection research]({{ '/lab/object-detection/' | relative_url }}) — the detector models that find pieces inside the classification chamber
- [Sorter architecture]({{ '/sorter/architecture/' | relative_url }}) — how the C-channel control loop fits into the overall software
