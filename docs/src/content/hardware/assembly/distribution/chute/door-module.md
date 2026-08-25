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
  - part: mg995-servo-horn
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
    qty: 16
---

The door module is the moving half of the chute. It is built on the bench as one unit and then bolted to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}). One per chute, so one per layer.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

Four things make it up:

1. **Chute door**. The flap itself, one printed part.
2. **Bearing assembly**. What the door swings on: the Bearing race, a Bearing holder (left) and a Bearing holder (right), a Bearing cover (covered side) and a Bearing cover (servo side), and two 6704-2RS bearings.
3. **Servo adapter**. Two printed parts, a servo side and a flap side, that couple the servo's output to the door. The MG995 Servo Horn that comes with the servo is clasped between the two halves, then the halves are screwed together around it: 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, driven through the flap side (it's the half with the visible screw holes) into the servo side. No heat inserts, the screws thread directly into the printed plastic.
4. **MG995 servo** in its four-part bracket: a housing, a lower arm, a side arm and a cover. Built on the bench, in the steps below.

**What each fastener is for.** The list above gives totals for the whole module; this is the split:

- **Bearing assembly, its own:** 10 {% include fastener.html size="M3" variant="heat-insert" %} (4 in the race, 3 in each holder) and 10 {% include fastener.html size="M3" variant="countersunk" length="8" %}. Six hold the covers to the holders, 3 each, and 4 hold the holders to the race, 2 each.
- **Servo adapter, its own:** 4 {% include fastener.html size="M3" variant="countersunk" length="8" %}, no heat inserts. They hold the servo-side and flap-side halves together with the MG995 Servo Horn clasped between them.
- **Servo bracket, its own:** 6 {% include fastener.html size="M3" variant="heat-insert" %} in the housing, 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} for the arms, and 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} through the servo's mounting ears.
- **Holding the finished module to the chute core:** not in the list above at all. Those screws come out of the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s own set and are counted on that page.

{% include step.html n="1" title="Preparation" %}

Four of the module's parts take heat inserts, 16 between them. Press them all in while the parts are still bare, before anything is screwed together. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

Every pocket is the same one the rest of the chute uses: Ø4.2 mm, blind, 5.7 mm deep. The two bearing covers, the chute door and the two servo adapter halves take none, so if a part is not below it needs no inserts.

The servo adapter takes no inserts, but assemble it here anyway, before the bracket steps:

<p><strong>Servo adapter:</strong> the servo-side and flap-side plates clamp the MG995 Servo Horn between them. The horn ships with the servo, it isn't printed. Lay it against the servo-side half, bring the flap-side half down over it, and drive 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws through the flap side (it's the half with the visible screw holes) into the servo side. No heat inserts, the screws cut their own thread in the printed plastic.</p>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/mg995-servo-horn-full-e3eb30ad4de0.png" alt="The MG995 Servo Horn, a two-arm splined servo arm that ships with the MG995 servo">
    <figcaption>The MG995 Servo Horn. Clasped between the two adapter halves before they're screwed together.</figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/servo-adapter-servo-side-recess-full-b4266d52934f.png" alt="The servo-side adapter half, rotated to show the recess that the MG995 Servo Horn seats into, with the four screw pilot holes around it">
    <figcaption>Servo-side half. The recess the horn seats into, plus the 4 pilot holes the screws thread into.</figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/servo-adapter-flap-side-holes-full-d9bfc444c1c4.png" alt="The flap-side adapter half, showing its four countersunk screw holes and the keyed centre hole">
    <figcaption>Flap-side half. The 4 countersunk holes the screws pass through, into the servo side.</figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Servo bracket (housing):</strong> 6 × M3, on three different faces. 4 of them take the arms and 2 take the servo's own mounting ears.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-inserts-servo-bracket-housing-full-7545917fe3d9.png" alt="Render of the servo bracket housing at an angle, with its six heat-insert pockets circled in red, two on each of three faces">
    <figcaption>All six, seen from the corner. That is the only angle that catches all three faces at once.</figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bearing race:</strong> 4 × M3, two at each end. These are the ones the holders screw down onto.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-inserts-bearing-race-full-4a30d9cbcc4a.png" alt="Render of the bearing race seen almost straight on, with its four heat-insert pockets circled in red, two at each end">
    <figcaption>Two at each end of the race.</figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bearing holder (left):</strong> 3 × M3, on the outboard face, around the bearing bore. The cover screws onto these three.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-inserts-bearing-holder-left-full-20b5c1bf8883.png" alt="Render of the left bearing holder at an angle, with its three heat-insert pockets circled in red around the bearing bore">
    <figcaption>Three around the bore on the outboard face.</figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bearing holder (right):</strong> 3 × M3, the mirror of the left one.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-inserts-bearing-holder-right-full-91e140ed31b4.png" alt="Render of the right bearing holder at an angle, with its three heat-insert pockets circled in red around the bearing bore, mirroring the left holder">
    <figcaption>The same three, mirrored.</figcaption>
  </figure>
</div>

The views are rendered from each part's STL, turned slightly off the face so the pockets shade as holes, and circle only the pockets visible from that angle. The counts match what the [parts calculator](https://parts-calculator.basically.website/assembly?focus=flap-module) asks for: 6 + 4 + 3 + 3.

**Steps 2 and 3 build the servo bracket on the bench.** The bearing assembly, the door and the servo adapter have no steps written yet, so build those from the parts themselves and correct this page as you go.

{% include step.html n="2" title="Seat the servo in its bracket housing" %}

Drop the MG995 into the housing and fasten it with 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws through the servo's own mounting ears.

Clock the horn before you commit to a position. The servo only rotates 180° and the door has to reach both of its positions inside that range; the video at the end of this page shows how it is set.

<div class="img-placeholder">Photo of the MG995 seated in the bracket housing, held by its two mounting-ear screws, with the horn already clocked to a known position before the arms go on</div>

{% include step.html n="3" title="Add the bracket arms and the cover" %}

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
