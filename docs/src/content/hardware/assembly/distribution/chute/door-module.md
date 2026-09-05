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
last_verified: 2026-09-05
warning: >-
  **AI-generated first draft, apart from the servo bracket.** Written from the machine assembly
  tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=flap-module), not from
  an actual build. Steps 2 and 3 are a builder's account, corrected against a real machine on
  2026-09-05, and the video below is Basically's own. The door, the bearing assembly and the
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
    qty: 5
  - part: scr-m3-8-cs
    qty: 21
---

The door module is the moving half of the chute. Build it on the bench as one unit, then bolt it to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}). One per chute, so one per layer.

The door pivots on two bearings held in the bearing assembly. The MG995 servo, coupled through the two-piece servo adapter, swings it between its open and closed positions, and the layer's [layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) controls when it opens, releasing the part only once the chute stack has rotated the funnel into position over the right bin.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-overview-full-9fb10a1573e7.png" alt="Render of the door module: the chute door on the left with its pivot shaft, the two servo adapter halves stacked on the end of that shaft, and the servo bracket on the right">
  <figcaption>How the module sits together, left to right: the chute door and its pivot shaft, the two servo adapter halves on the end of the shaft, and the servo in its bracket. The bearing assembly, which goes on the shaft between the door and the adapter, is not shown. <cite>Rendered from the part geometry in assembly position, not from a build. Render: Balloon.</cite></figcaption>
</figure>

Three of the four sub-assemblies below have no assembly steps written yet: the door, the bearing assembly and the servo adapter. Only the servo bracket (steps 2 and 3) comes from a real build. Build the other three from the parts themselves, and correct this page as you go. The fastener counts below are accurate even though the order of operations for those three isn't written down.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

Four things make it up:

1. **Chute door**. The flap itself, one printed part.
2. **Bearing assembly**. What the door swings on: the bearing race, a bearing holder (left) and a bearing holder (right), a bearing cover (covered side) and a bearing cover (servo side), and two 6704-2RS bearings.
3. **Servo adapter**. Two printed parts, a servo side and a flap side, that couple the servo's output to the door. The MG995 Servo Horn that comes with the servo is clasped between the two halves, then the halves are screwed together around it: 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, driven through the flap side (it's the half with the visible screw holes) into the servo side. No heat inserts, the screws thread directly into the printed plastic.
4. **MG995 servo** in its four-part bracket: a housing, a lower arm, a side arm and a cover. Built on the bench, in the steps below. **The servo itself is not screwed to anything.** It slides into the housing and the cover goes on over it, and the cover's two screws clamp the servo's mounting tabs in place.

**What each fastener is for.** The list above gives totals for the whole module; this is the split:

- **Bearing assembly, its own:** 10 {% include fastener.html size="M3" variant="heat-insert" %} (4 in the race, 3 in each holder) and 10 {% include fastener.html size="M3" variant="countersunk" length="8" %}. Six hold the covers to the holders, 3 each, and 4 hold the holders to the race, 2 each. The two 6704-2RS bearings are sealed on both sides (that's what "2RS" means), so they're symmetric: there's no wrong way round to seat them. The covers are thin printed plastic, so snug their screws down evenly rather than fully tightening one before the others.
- **Servo adapter, its own:** 4 {% include fastener.html size="M3" variant="countersunk" length="8" %}, no heat inserts. They hold the servo-side and flap-side halves together with the MG995 Servo Horn clasped between them.
- **Servo bracket, its own:** 6 {% include fastener.html size="M3" variant="heat-insert" %} in the housing, two on each of three faces, and one screw per insert. 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} hold the lower arm on, 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} hold the side arm on, and 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} hold the cover on. None of them goes through the servo.
- **Holding the finished module to the chute core:** 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} through the two bearing covers, plus one screw through each bracket arm's mounting ear, step 4. The two arms are not the same thickness there, so they do not take the same screw: the lower arm's ear is 8.40 mm and takes a {% include fastener.html size="M3" variant="countersunk" length="12" %}, the side arm's is 5.00 mm and takes a {% include fastener.html size="M3" variant="countersunk" length="8" %}. All six go into the core's own heat inserts, so there is nothing to press in here for them.

{% include step.html n="1" title="Preparation" %}

Four of the module's parts take heat inserts, 16 between them. Press them all in while the parts are still bare, before anything is screwed together. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

Every pocket is the same one the rest of the chute uses: Ø4.2 mm, blind, 5.7 mm deep. The two bearing covers, the chute door and the two servo adapter halves take none, so if a part is not below it needs no inserts.

The servo adapter takes no inserts, but assemble it here anyway, before the bracket steps:

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Servo adapter:</strong> the servo-side and flap-side plates clamp the MG995 Servo Horn between them. The horn ships with the servo, it isn't printed. Lay it against the servo-side half, bring the flap-side half down over it, and drive 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws through the flap side (it's the half with the visible screw holes) into the servo side. No heat inserts, the screws cut their own thread in the printed plastic.</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/mg995-servo-horn-square-full-150991b8cde4.png" alt="The MG995 Servo Horn, a two-arm splined servo arm that ships with the MG995 servo">
      <figcaption>The MG995 Servo Horn. Clasped between the two adapter halves before they're screwed together. <cite>Reference photo of the stock part, not from a build. Photographer not recorded.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/servo-adapter-servo-side-recess-full-e4d5c312826a.png" alt="The servo-side adapter half, rotated to show the recess that the MG995 Servo Horn seats into, with the four screw pilot holes around it">
      <figcaption>Servo-side half. The recess the horn seats into, plus the 4 pilot holes the screws thread into. <cite>Rendered from the part geometry, not from a build.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/servo-adapter-flap-side-door-face-full-871c96a5ad23.png" alt="The flap-side adapter half, rotated 180 degrees from the screw side to show the hexagonal boss and keyed bore that the chute door's shaft inserts into">
      <figcaption>Flap-side half, other face. The hex boss the chute door's shaft inserts into. <cite>Rendered from the part geometry, not from a build.</cite></figcaption>
    </figure>
  </div>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Servo bracket (housing):</strong> 6 × M3, two on each of three faces. 2 take the lower arm, 2 take the side arm and 2 take the cover. The servo does not screw to the housing at all, so none of these is for it.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-inserts-servo-bracket-housing-full-7545917fe3d9.png" alt="Render of the servo bracket housing at an angle, with its six heat-insert pockets circled in red, two on each of three faces">
    <figcaption>All six, seen from the corner. That is the only angle that catches all three faces at once. <cite>Render: Balloon.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bearing race:</strong> 4 × M3, two at each end. These are the ones the holders screw down onto.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-inserts-bearing-race-full-4a30d9cbcc4a.png" alt="Render of the bearing race seen almost straight on, with its four heat-insert pockets circled in red, two at each end">
    <figcaption>Two at each end of the race. <cite>Render: Balloon.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bearing holder (left):</strong> 3 × M3, on the outboard face, around the bearing bore. The cover screws onto these three.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-inserts-bearing-holder-left-full-20b5c1bf8883.png" alt="Render of the left bearing holder at an angle, with its three heat-insert pockets circled in red around the bearing bore">
    <figcaption>Three around the bore on the outboard face. <cite>Render: Balloon.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bearing holder (right):</strong> 3 × M3, the mirror of the left one.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-inserts-bearing-holder-right-full-91e140ed31b4.png" alt="Render of the right bearing holder at an angle, with its three heat-insert pockets circled in red around the bearing bore, mirroring the left holder">
    <figcaption>The same three, mirrored. <cite>Render: Balloon.</cite></figcaption>
  </figure>
</div>

The views are rendered from each part's STL, turned slightly off the face so the pockets shade as holes, and circle only the pockets visible from that angle. The counts match what the [parts calculator](https://parts-calculator.basically.website/assembly?focus=flap-module) asks for: 6 + 4 + 3 + 3.

{% include step.html n="2" title="Slide the servo into the housing and close it with the cover" %}

**The servo is not screwed down.** Slide the MG995 into the housing's pocket, then lay the cover over the open face and drive its 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws into the housing's inserts. Tightening those two is what holds the servo: the cover traps the servo's mounting tabs between itself and the housing.

The cover is 6.65 mm thick at the screw, so a 12 mm screw reaches 5.35 mm into the housing's blind 5.70 mm insert and an 8 mm one would reach only 1.35 mm. Snug both down evenly rather than pulling one home first, so the cover seats flat on the tabs.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/housing-cover-open-full-eb4bde91c9c0.png" alt="Render of the servo bracket housing with the cover pulled off it, showing the open pocket the servo slides into and the two screw lugs that line up between the cover and the housing">
  <figcaption>The cover pulled off the housing. The servo goes into the open pocket, and the two lugs the cover screws through are the only fasteners holding it. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

{% include step.html n="3" title="Add the bracket arms" %}

The two arms land on two other faces of the housing, so they are independent of the servo and can go on before or after it.

- **Lower arm:** 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} into the housing's inserts. The arm is 4.25 mm thick at the screws, so an 8 mm one reaches 3.75 mm in.
- **Side arm:** 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} into the housing's inserts. This arm is 8.40 mm thick at the screws, so an 8 mm one would not reach them at all.

Each arm has one further hole, in the ear at its far end. Those two are not driven here; they are what bolts the finished bracket to the chute core in step 4, so leave them empty.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/servo-bracket-assembled-full-2c6c3cddb48f.png" alt="Render of the assembled servo bracket seen from the cover side: the cover with its two screw lugs and the window the servo sits behind, the side arm to the right and the lower arm below, each with the single mounting ear that bolts to the chute core">
  <figcaption>The bracket assembled, seen from the cover side. The two ears sticking out at bottom and right, one on each arm, are the pair that bolt to the chute core. <cite>Rendered from the part geometry in assembly position, not from a build. Render: Balloon.</cite></figcaption>
</figure>

{% include step.html n="4" title="Fit the module to the chute core" %}

Six of the core's 18 inserts are for this module, and the screws for them are in the list above:

- **2 bearing covers**, 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} in total, 2 per cover, into 5.00 mm of wall.
- **Servo bracket lower arm**, 1 {% include fastener.html size="M3" variant="countersunk" length="12" %} through its ear.
- **Servo bracket side arm**, 1 {% include fastener.html size="M3" variant="countersunk" length="8" %} through its ear.

Every one of those is 8 mm except the lower arm's, and the reason is the wall it goes through. The bearing covers and the side arm's ear are both 5.00 mm, so an 8 mm screw reaches 3.00 mm into the core's blind 5.70 mm insert. The lower arm's ear is 8.40 mm, so an 8 mm screw would not reach the insert at all and it takes a 12, which reaches 3.60 mm. All measured off the STLs.

The servo output then couples to the door through the two-piece servo adapter, servo side and flap side. Push the adapter onto the servo's splined output and clock it before you commit: centre the servo (or let it settle at its power-on default), fit it at roughly the middle of the door's swing, then fine-tune once you can check both open and closed by eye. The video below shows how it is set.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-servo-video-frame-full-1f27d2aaa634.jpg" alt="Photograph of a real door module part-way through assembly: a hand holds the assembled servo adapter, a white disc with a hexagonal boss in the middle and four countersunk screws around it, in front of the MG995 in its printed bracket">
  <figcaption>The same job on a real machine. The disc in frame is the servo adapter from step 1, screwed together with its four countersunk screws, with the hexagonal boss that takes the door's shaft facing the camera; the MG995 sits in its bracket behind it. <cite>Frame from the video below, on Basically's own YouTube channel. Who filmed it isn't recorded.</cite></figcaption>
</figure>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The MG995 only rotates 180°. Install the servo so the door can reach <strong>both</strong> its fully open and fully closed positions inside that range: clock the horn and set the mounting angle so neither extreme falls outside the servo's travel. Before you tighten anything down, cycle the door by hand through both positions to confirm it swings freely and doesn't bind on the bearings or the core.</p>
</div>

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/TMo_xE-Zyy0"
      title="How to install the MG995 servo"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: Basically's own YouTube channel. Who filmed it isn't recorded.</cite></figcaption>
</figure>
