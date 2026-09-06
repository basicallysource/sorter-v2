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
  2026-09-05, and the video below is Basically's own. Step 4 is derived from the parts'
  geometry, not from anyone who has built one. Correct it as you build.
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

Only the servo bracket, steps 2 and 3, comes from a real build. The bearing assembly in step 4 is worked out from the parts rather than reported by anyone who has built one, and the servo adapter still has no order of operations beyond screwing it together. Correct this page as you go; the fastener counts are accurate either way.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

Four things make it up:

1. **Chute door**. The flap itself, one printed part.
2. **Bearing assembly**. What the door swings on: the bearing race, a bearing holder (left) and a bearing holder (right), a bearing cover (covered side) and a bearing cover (servo side), and two 6704-2RS bearings.
3. **Servo adapter**. Two printed parts, a servo side and a flap side, that couple the servo's output to the door. The MG995 Servo Horn that comes with the servo is clasped between the two halves, then the halves are screwed together around it: 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, driven through the flap side (it's the half with the visible screw holes) into the servo side. No heat inserts, the screws thread directly into the printed plastic.
4. **MG995 servo** in its four-part bracket: a housing, a lower arm, a side arm and a cover. Built on the bench, in the steps below. **The servo itself is not screwed to anything.** It slides into the housing and the cover goes on over it, and the cover's two screws clamp the servo's mounting tabs in place.

**What each fastener is for.** The list above gives totals for the whole module; this is the split:

- **Bearing assembly, its own:** 10 {% include fastener.html size="M3" variant="heat-insert" %} (4 in the race, 3 in each holder) and 10 {% include fastener.html size="M3" variant="countersunk" length="8" %}. Six hold the covers to the holders, 3 each, and 4 hold the holders to the race, 2 each; all ten are driven in step 4. The two 6704-2RS bearings go into the holders in step 1. The covers are thin at the rim, so snug their screws down evenly rather than fully tightening one before the others.
- **Servo adapter, its own:** 4 {% include fastener.html size="M3" variant="countersunk" length="8" %}, no heat inserts. They hold the servo-side and flap-side halves together with the MG995 Servo Horn clasped between them.
- **Servo bracket, its own:** 6 {% include fastener.html size="M3" variant="heat-insert" %} in the housing, two on each of three faces, and one screw per insert. 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} hold the lower arm on, 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} hold the side arm on, and 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} hold the cover on. None of them goes through the servo.
- **Holding the finished module to the chute core:** 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} through the two bearing covers, plus one screw through each bracket arm's mounting ear, step 6. The two arms are not the same thickness there, so they do not take the same screw: the lower arm's ear is 8.40 mm and takes a {% include fastener.html size="M3" variant="countersunk" length="12" %}, the side arm's is 5.00 mm and takes a {% include fastener.html size="M3" variant="countersunk" length="8" %}. All six go into the core's own heat inserts, so there is nothing to press in here for them.

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
    <p><strong>Bearing holder (left) and bearing holder (right):</strong> 3 × M3 each, 6 between them, on the outboard face around the bearing bore.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-inserts-bearing-holder-left-full-20b5c1bf8883.png" alt="Render of the left bearing holder at an angle, with its three heat-insert pockets circled in red around the bearing bore">
    <figcaption>Three around the bore on the outboard face. The left holder is shown; the right one takes the same three. <cite>Render: Balloon.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>The two 6704-2RS bearings:</strong> one into the <strong>bearing holder (left)</strong>, one into the <strong>bearing holder (right)</strong>. They take no inserts and there is no wrong way round. Push each one square to the bottom of the bore.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/bearing-into-holder-blue-full-8cb4f2b8771b.png" alt="Two renders of the left bearing holder, one above the other: on top a 6704-2RS bearing, coloured blue, lined up with the mouth of the holder's bore, below it the same blue bearing pushed down to the bottom of the pocket">
    <figcaption>Lined up with the bore, then seated at the bottom of it. The left holder is shown; the right one takes its bearing the same way. <cite>The bearing is coloured blue to pick it out. Rendered from the holder's own geometry, not from a build. Render: Balloon.</cite></figcaption>
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

Each arm has one further hole, in the ear at its far end. Those two are not driven here; they are what bolts the finished bracket to the chute core in step 6, so leave them empty.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/servo-bracket-assembled-full-2c6c3cddb48f.png" alt="Render of the assembled servo bracket seen from the cover side: the cover with its two screw lugs and the window the servo sits behind, the side arm to the right and the lower arm below, each with the single mounting ear that bolts to the chute core">
  <figcaption>The bracket assembled, seen from the cover side. The two ears sticking out at bottom and right, one on each arm, are the pair that bolt to the chute core. <cite>Rendered from the part geometry in assembly position, not from a build. Render: Balloon.</cite></figcaption>
</figure>

{% include step.html n="4" title="Hang the door on its bearings and the race" %}

The shaft is captured at both ends once this is together, so there is only one order it goes in: the holders have to go onto the shaft before anything is bolted down.

**Check which way round the door goes first.** The shaft runs the length of the door's top edge and is Ø19.8 mm, but one end finishes in a hexagonal spigot 12.0 mm across the flats. That hex end is the servo side — it is what the servo adapter's flap-side half slides onto in step 6. The other end is plain round.

1. **Slide a holder onto each end of the shaft**, bearings already seated. The bearing's Ø20 bore takes the Ø19.8 shaft, and the holder's own Ø21.0 mm hole clears the shaft by 0.6 mm all round, so neither should need forcing.
2. **Lay the race along the back of the shaft**, on the opposite side from the flap, and bolt each holder down onto its end of it: 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} per holder, 4 in total, into the race's four inserts. The holder seats flat against the race's end. The race arches over the shaft with about 0.5 mm of clearance and never touches it; if it does touch, something is not seated.
3. **Put a cover on each holder**, 3 {% include fastener.html size="M3" variant="countersunk" length="8" %} each, 6 in total, into the three inserts pressed in step 1. The cover's raised rim, 5.00 mm tall, drops into the pocket on top of the bearing and clamps it against the step: if a bearing is not all the way down, its cover will not pull flat. Each cover has **two further holes that stay empty here** — they take the screws that hold the flap assembly to the chute core in step 5.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/bearing-assembly-blue-full-1cb33257bd5a.png" alt="Two renders, one above the other: on top the chute door with its shaft, the bearing race over the shaft, and the two bearing holders drawn out along the shaft with a blue bearing in each; below, the same parts pushed together so the holders sit on the ends of the race">
  <figcaption>The holders, with their bearings in blue, going onto the ends of the shaft and down onto the race. The covers are not shown. <cite>Rendered from the parts' own geometry in assembly position, not from a build. Render: Balloon.</cite></figcaption>
</figure>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>This order is derived from the parts rather than from a build: the bores, the shaft and the race line up in the CAD and only fit together one way. The fits quoted are measured off the STLs. Nobody has reported building it, so correct this step if it does not go together as described.</p>
</div>

{% include step.html n="5" title="Bolt the flap assembly to the chute core" %}

Six of the core's 18 inserts belong to this module. Four are used here, two in step 6:

- **2 bearing covers**, 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} in total, 2 per cover, into 5.00 mm of wall. These are the two holes left empty in each cover in step 4.
- **Servo bracket lower arm**, 1 {% include fastener.html size="M3" variant="countersunk" length="12" %}, and **side arm**, 1 {% include fastener.html size="M3" variant="countersunk" length="8" %} — step 6.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-core-door-module-side-4-full-f61ab38ed984.png" alt="Render of the servo side of the chute core with four heat inserts circled in red">
    <figcaption>The long side the servo sits on: two inserts for that side's bearing cover, two for the servo bracket arms. <cite>Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-core-door-module-side-2-full-c9afd2f336aa.png" alt="Render of the other long side of the chute core with two heat inserts circled in red">
    <figcaption>The other long side: two inserts, both for the second bearing cover. <cite>Render: Balloon.</cite></figcaption>
  </figure>
</div>

**The covers are what hold the flap on.** Nothing else in the bearing assembly touches the core: the race and the holders are carried by the two covers, which are already screwed to the holders from step 4. Offer the whole assembly up so a cover lands on each long side of the core, and drive 2 screws per cover into the inserts above.

8 mm is the right length because the cover is 5.00 mm at those holes, so the screw reaches 3.00 mm into the core's blind 5.70 mm insert. Measured off the STLs.

Snug all four down before tightening any of them, then cycle the door by hand through its full swing. It should turn freely on the bearings and not touch the core anywhere; if it binds, slacken off and let the assembly settle square before tightening again.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/chute-core-flap-fitted-full-3988a30ff4a4.jpg" alt="Photograph of a printed chute core lying face up with the flap assembly already bolted to it: the round bearing cover, its six screw heads and central hex boss, sits on the core's long side, and the brass heads of the core's other heat inserts are visible across the face">
  <figcaption>What you should have at the end of this step: the flap assembly on the core, held by the bearing cover you can see on the right. The servo bracket has not gone on yet. <cite>Frame at 0:01 of the video in step 6, on Basically's own YouTube channel; screenshot by barthel. Who filmed it isn't recorded.</cite></figcaption>
</figure>

{% include step.html n="6" title="Bolt the servo bracket on and couple it to the door" %}

The bracket goes on the same long side as the servo-side bearing cover, into the other two inserts in the first render above. The two arms do not take the same screw, because their mounting ears are not the same thickness:

- **Lower arm**, 1 {% include fastener.html size="M3" variant="countersunk" length="12" %} through an ear 8.40 mm thick. An 8 mm screw would not reach the insert at all; the 12 reaches 3.60 mm into it.
- **Side arm**, 1 {% include fastener.html size="M3" variant="countersunk" length="8" %} through an ear 5.00 mm thick, the same as the bearing covers'. The 8 reaches 3.00 mm in; a 12 would bottom out in the pocket.

Then couple the servo to the door through the two-piece adapter you built in step 1. Its servo side goes onto the servo's splined output, through the horn clasped inside it, and its flap side has a hexagonal socket 12.4 mm across the flats that takes **the hex end of the door's shaft** — the end step 4 told you to point at the servo. The spigot is 12.0 mm across the flats, so it is a slip fit with about 0.4 mm to spare.

Clock it before you commit: centre the servo (or let it settle at its power-on default), fit the adapter at roughly the middle of the door's swing, then fine-tune once you can check both open and closed by eye. The video below shows how it is set.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-servo-video-frame-full-1f27d2aaa634.jpg" alt="Photograph of a real door module part-way through assembly: a hand holds the assembled servo adapter, a white disc with a hexagonal boss in the middle and four countersunk screws around it, in front of the MG995 in its printed bracket">
  <figcaption>The same job on a real machine. The disc in frame is the servo adapter from step 1, screwed together with its four countersunk screws, with the hexagonal socket that takes the door's shaft facing the camera; the MG995 sits in its bracket behind it. <cite>Frame from the video below, on Basically's own YouTube channel. Who filmed it isn't recorded.</cite></figcaption>
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
