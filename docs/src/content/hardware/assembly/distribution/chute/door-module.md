---
layout: default
title: Door module
type: how-to
section: hardware
slug: assembly-door-module
kicker: Chute — Door module
lede: The per-layer door mechanism that releases parts into a bin.
permalink: /hardware/assembly/distribution/chute/door-module/
author: spencer
contributors: [barthel]
warning: >-
  **AI-generated first draft, apart from the servo.** Written from the machine assembly tree in
  the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=flap-module), not from
  an actual build. The servo steps and the video below came from an earlier page and are the
  only part of this that has been through a real build. The door, the bearing assembly and the
  servo adapter have no assembly steps written yet. Correct it as you build.
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
  - part: servo-bracket-housing
    qty: 1
  - part: servo-bracket-lower-arm
    qty: 1
  - part: servo-bracket-side-arm
    qty: 1
  - part: servo-bracket-cover
    qty: 1
  - part: servo-mg995
    qty: 1
  - part: brg-6704-2rs
    qty: 2
  - part: hsi-m3
    qty: 16
  - part: scr-m3-12-cs
    qty: 4
  - part: scr-m3-8-cs
    qty: 12
---

The door module is the moving half of the chute. It is built on the bench as one unit and then bolted to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}), which is where all of its mounting screws land. One per chute, so one per layer.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

Four things make it up:

1. **Chute door**. The flap itself, one printed part.
2. **Bearing assembly**. What the door swings on: the Bearing race, a Bearing holder (left) and a Bearing holder (right), a Bearing cover (covered side) and a Bearing cover (servo side), and two 6704-2RS bearings.
3. **Servo adapter**. Two printed parts, a servo side and a flap side, that couple the servo's output to the door.
4. **MG995 servo** in its four-part bracket: a housing, a lower arm, a side arm and a cover. Built on the bench, in the steps below.

**Which fasteners belong to what**, since the list above cannot say it:

- **Bearing assembly, its own:** 10 {% include fastener.html size="M3" variant="heat-insert" %} (4 in the race, 3 in each holder) and 10 {% include fastener.html size="M3" variant="countersunk" length="8" %}. Six hold the covers to the holders, 3 each, and 4 hold the holders to the race, 2 each.
- **Servo bracket, its own:** 6 {% include fastener.html size="M3" variant="heat-insert" %} in the housing, 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} for the arms, and 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} through the servo's mounting ears.
- **Holding the finished module to the chute core:** not in the list above. Those screws come out of the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s own set, and are on that page.

{% include step.html n="1" title="Preparation" %}

Press the inserts into the servo bracket housing while it is still bare, and into the bearing race and the two holders. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Servo bracket (housing):</strong> 6 × M3</p>
    <p><strong>Bearing race:</strong> 4 × M3. <strong>Bearing holder (left)</strong> and <strong>(right)</strong>: 3 × M3 each.</p>
  </div>
  <div class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </div>
</div>

{% include step.html n="2" title="Seat the servo in the housing" %}

Drop the MG995 into the housing and fasten it with 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws through the servo's own mounting ears.

Clock the horn before you commit to a position. The servo only rotates 180°, and the door has to reach both of its positions inside that range, which is what the video further down is about.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Add the arms and the cover" %}

Fit the lower arm and the side arm to the housing and fasten them with the 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws into the housing's inserts. Clip the cover on last; it takes no screws.

{% include step.html n="4" title="Fit the module to the chute core" %}

Six of the core's 18 inserts are for this module, and the screws come out of the core's own set rather than being extra:

- **2 bearing covers**, 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} in total, 2 per cover.
- **Servo bracket arms**, 2 {% include fastener.html size="M3" variant="countersunk" length="12" %}.

The full split across the core's 14 countersunk screws is on the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) page, which is the one place it is written down.

The servo output then couples to the door through the two-piece servo adapter, servo side and flap side.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The MG995 only rotates 180°. Install the servo so the door can reach <strong>both</strong> its fully open and fully closed positions inside that range: clock the horn and set the mounting angle so neither extreme falls outside the servo's travel.</p>
</div>

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/TMo_xE-Zyy0"
    title="How to install the MG995 servo"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>
