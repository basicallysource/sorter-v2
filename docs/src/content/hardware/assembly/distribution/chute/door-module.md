---
layout: default
title: Door module
type: landing
section: hardware
slug: assembly-door-module
kicker: Chute — Door module
lede: The per-layer door mechanism that releases parts into a bin.
permalink: /hardware/assembly/distribution/chute/door-module/
author: spencer
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=flap-module), not from
  an actual build. Nothing here has been checked against a machine, and only the servo has
  build pages: the door, the bearing assembly and the servo adapter have no assembly steps
  written yet. Correct it as you build.
parts_needed:
  - part: chute-door
    qty: 1
  - part: bearing-race
    qty: 1
  - part: bearing-holder-left
    qty: 1
  - part: bearing-holder-right
    qty: 1
  - part: bearing-cover-covered
    qty: 1
  - part: bearing-cover-servo
    qty: 1
  - part: servo-adapter-servo-side
    qty: 1
  - part: servo-adapter-flap-side
    qty: 1
  - part: brg-6704-2rs
    qty: 2
  - part: hsi-m3
    qty: 10
  - part: scr-m3-8-cs
    qty: 10
---

The door module is the moving half of the chute. It is built on the bench as one unit and then bolted to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}), which is where all of its mounting screws land. One per chute, so one per layer.

Four things make it up:

1. **Chute door**. The flap itself, one printed part.
2. **Bearing assembly**. What the door swings on: the Bearing race, a Bearing holder (left) and a Bearing holder (right), a Bearing cover (covered side) and a Bearing cover (servo side), and two 6704-2RS bearings. It carries 10 M3 heat inserts of its own, 4 in the race and 3 in each holder, and takes 10 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws: 6 hold the covers to the holders, 3 each, and 4 hold the holders to the race, 2 each. Those are separate from the chute core's 18 inserts.
3. **Servo adapter**. Two printed parts, a servo side and a flap side, that couple the servo's output to the door.
4. **[MG995 servo]({{ '/hardware/assembly/distribution/chute/mg995-servo/' | relative_url }})** in its four-part bracket. Build it and clock the horn on the [Servo mount]({{ '/hardware/assembly/distribution/chute/mg995-servo/servo-mount/' | relative_url }}) page, then see [How to install]({{ '/hardware/assembly/distribution/chute/mg995-servo/how-to-install/' | relative_url }}).

## How it mounts to the chute core

Six of the core's 18 inserts are for this module, and the screws come out of the core's own set rather than being extra:

- **2 bearing covers**, 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} in total, 2 per cover.
- **Servo bracket arms**, 2 {% include fastener.html size="M3" variant="countersunk" length="12" %}.

The full split across the core's 14 countersunk screws is on the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) page, which is the one place it is written down.
