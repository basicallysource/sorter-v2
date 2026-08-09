---
title: Feeder experiments
type: explanation
audience: contributor understanding singulation history
applies_to: hardware-v2
owner: lab
last_verified: 2026-04-14
section: lab
slug: lab-feeder-experiments
kicker: Lab — Research Area
lede: The turntable, vibration, and chute experiments that preceded the C-channel design — what was tested, what failed, and what the results taught us.
permalink: /lab/feeder-experiments/
---

## The question

What feeder mechanisms were tested before the project settled on C-channels, and what did each experiment reveal?

The path to the current [C-channel singulation]({{ '/lab/c-channel-singulation/' | relative_url }}) design was not linear. Multiple approaches were prototyped and tested. This page records what was tried, what the data showed, and which insights survived.

## Turntable experiments

### Spiral labyrinth

A spinning disc with spiral/wavy walls intended to use centrifugal force and tangential velocity to separate pieces over distance.

**Result:** Clumping persists without vibration. Pieces mostly drift outward and do not interact with spiral walls as expected. Scaled-down prototypes do not replicate full-scale physics — small prototypes gave misleadingly optimistic results.

**Key finding:** Larger diameter (300mm) + longer spiral path improves separation, but the footprint grows unacceptably. Two stacked turntables can actually **re-clump** pieces that were already separated.

### Flat rotating V-channel

A flat turning table tested for separation behavior.

**Result:** Provides conveyor-like function (linear arrangement with predictable exit points) but **no agitation**. Cannot separate on its own — assumes pre-separated pieces upstream. A single table is insufficient for throughput; requires 2+ tables with strategic pausing via computer vision.

### Industry comparison

The team found existing rotary turntables with diverters in the industrial unscrambler market. Similar spiral/chicane concepts exist for belt systems, but these assume uniform product geometry — unusable for LEGO's shape variety. PTFE (low-friction) surfaces on vertical walls were noted in industrial designs.

## Vibration feeders

Linear vibratory feeders with compression springs (ISO 10243 die springs from 3D printer suppliers) were tested.

| Spring source | Stiffness | Notes |
|---------------|-----------|-------|
| Bambu Lab compression springs | Standard | Baseline stiffness |
| Creality springs | 2–3× stiffer | Too stiff for fine control |
| ISO 10243 yellow die springs (8×4×20mm) | Medium | Selected — globally available, $0.50/piece |

**Motor:** RS-385 DC 12V (replaced V1's uxcell Micro Motor which became unavailable in EU/US).

**Result:** Vibration provides natural agitation and effective separation, but is **loud**. V-channels work well but the noise profile is unacceptable for home/workshop use. This drove the search for a quieter alternative.

## Chute drop tests

Spencer tested piece drop accuracy at three heights to validate the bin distribution system.

| Height | Success rate | Failures | Primary failure modes |
|--------|-------------|----------|----------------------|
| Short (~2nd layer) | 73% (19/26) | 7 | 4 bounced out front, 2 adjacent bin, 1 stuck |
| Medium (~3rd layer) | 90% (19/21) | 2 | 1 adjacent bin, 1 bounced out |
| High (~5th layer) | 73% (16/22) | 6 | 2 stuck in chute, 2 bounced out, 2 adjacent bin |

**Failure mode breakdown (all heights combined):**

| Mode | Frequency | Fix |
|------|-----------|-----|
| Bounced out front | ~10% | Soft flap/curtain at chute exit to dampen momentum |
| Into adjacent bin | ~7% | Increase bin wall height, keep bins vertically supported |
| Stuck in chute | ~4% | Hard 90° funnel walls instead of flared taper |

Large pieces can bump bins out of alignment — bins need vertical support, not gravity alone.

## Camera and imaging experiments

| Experiment | Finding |
|------------|---------|
| Rolling shutter + moving pieces | Pieces need ~0.1s stationary for clean image. Current solution: stop carousel briefly during exposure |
| Global shutter (OV9281) | Tested — still produced distortion when pieces were moving. Strobe lighting explored but adds complexity |
| Arducam vs Anker C200 edge test | Anker C200 retains better sharpness toward frame edges. Arducam has steeper falloff |
| Lighting evolution | Started with overhead COB LED (too bright, washed out ArUco tags). Evolved to side-mounted COB strip + vertical light posts per channel |

## The key insight

> "The drops between channels is far more important [than vibration itself]."

This observation — that **inter-stage drops** are the primary separation mechanism, not vibration or rotation — led directly to the C-channel design. If drops do the work, you can replace vibration with quiet rotation and achieve equivalent singulation by stacking enough stages.

## Where to go next

- [C-channel singulation]({{ '/lab/c-channel-singulation/' | relative_url }}) — the design that emerged from these experiments
- [Object detection research]({{ '/lab/object-detection/' | relative_url }}) — the detector models used for piece tracking in the chamber
