---
layout: default
title: Lamp arm
type: how-to
section: hardware
slug: assembly-lamp-arm
kicker: Feeder — Lamp arm
lede: The arm and the ring it carries, the reflector with its ring of LED strip, and the cover that goes over the top. The half of a camera lamp that is the same on all three. Build three.
permalink: /hardware/assembly/feeder/camera-lamp/lamp-arm/
author: reveryx
contributors: [spencer, danny, brickcyclealice, barthel]
og_image: https://assets.basically.website/sorter-docs/assembly-camera-lamp-arm-assembled-w1600-735fdcc7ecd6.jpg
warning: >-
  **Step 5, the cover, is not verified against a build.** Steps 1 to 4 are photographed on real
  builds. The cover has no build photograph yet, and it is the step whose place in the order is
  still open, because it is also what holds the camera down. Everything else here is measured
  off the published STLs. Fill the gaps in as you build.
parts_needed:
  - part: c-channel-arm-mount
    qty: 1
  - part: camera-lamp-arm
    qty: 1
  - part: arm-bracket-a
    qty: 1
  - part: arm-bracket-b
    qty: 1
  - part: camera-lamp-ring
    qty: 1
  - part: lamp-inner-reflector
    qty: 1
  - part: inner-reflector-led-hook
    qty: 6
  - part: lamp-outer-cover
    qty: 1
  - part: scr-m3-12-cs
    qty: 12
---

This page builds the part of a camera lamp that is the same on every channel: the arm with its ring at one end and its dovetail at the other, and the shaded lamp that sits over the ring. **No camera goes on here.** That is the [feeder camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/feeder-camera-lamp/' | relative_url }}) page for C2 and C3, and the [classification camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/classification-camera-lamp/' | relative_url }}) page for C4.

**The parts list above is one arm's worth. Build three**, for C2, C3 and the classification channel. **The bulk channel (C1) takes none**, because the machine does not look at it.

Build these before the channels that carry them: two of the [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}) pages need a lamp to start.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Prepare an <a href="{{ '/hardware/helpers/led-strip/' | relative_url }}">LED strip</a> before you start.</strong> One per lamp: a 950 mm length cut off the roll with two wires on the end, either clamped on or soldered. That page has the strip, the connector and the lead; step 4 here only hooks it on.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-strip-start-w1600-3d30eeb9a913.jpg" alt="The white reflector with the leading end of the LED strip started under the hooks in its skirt, the rest of the strip still carrying its blue protective film">
    <figcaption>A cut length of strip going into a reflector. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Colours.</strong> The <strong>Lamp inner reflector</strong> and its six <strong>LED hooks</strong> print ivory white, and that is not cosmetic: they are the reflector. The <strong>Lamp outer cover</strong> is ash grey. The arm, the mount, both brackets and the ring follow the channel colour like the rest of that channel's parts.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-side-full-2a681306f3a9.png" alt="CAD render of the camera lamp in profile: the disc-shaped lamp overhanging at the top, carried on an arm that steps down at an angle to the C-channel arm mount, with a bracket along each joint">
    <figcaption>The whole thing in profile. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Six LED hooks per lamp, 18 for the machine.</strong> They are the ones people come up short on.</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-reflector-hooks-w1600-ba5715705d94.jpg" alt="The printed lamp inner reflector lying face up, ivory white, with six LED hooks clipped evenly around its rim and a small grey rectangular plate sitting on the flat">
      <figcaption>The inner reflector with its six LED hooks around the rim. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-reflector-hooks-close-w1600-0b2e6c678dc5.jpg" alt="A closer view of the same reflector, two of the hooks standing off the rim and the grey rectangular plate on the flat between them">
      <figcaption>Closer, with two of the hooks in view. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
  </div>
</div>

{% include step.html n="2" title="Bracket the arm to the C-channel arm mount" %}

The arm and the mount butt together end to end, with bracket A on one face and bracket B on the other.

<ol class="numbered-steps">
  <li>Butt the arm and the mount together. The ends are shaped, so they only mate one way round. If it does not seem to fit, swap the piece end for end rather than forcing it.</li>
  <li>Lay bracket A across the joint on one face and bracket B on the other, <strong>angled ends towards the dovetail</strong>.</li>
  <li>Drive 8 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, four per bracket. Stop as each head seats.</li>
</ol>

**The two brackets share their holes**, four holes with a screw into each end, so half of every hole belongs to the other bracket's screw. **Use the 12 mm here.** Two 16 mm screws would meet inside a hole before either seated.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-arm-bracket-joint-w1600-a0beb5ce60b8.jpg" alt="The camera lamp arm butted to its mount with a bracket screwed across the joint, two countersunk screws in it, and the printed dovetail at the far end of the arm">
    <figcaption>The joint with a bracket on, angled end towards the dovetail. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-arm-ring-section-w1600-27f1be3340df.jpg" alt="The far section of the camera lamp arm lying on the bench, the lamp ring at one end and the shaped mating end at the other">
    <figcaption>The other section, ring end and shaped end. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-mounted-wide-w1600-247fb837f4f8.jpg" alt="A wider view of a camera lamp on the machine, showing the full length of the arm from the lamp down to the C-channel, with a bracket screwed along the joint and the LED leads cable-tied along the arm">
    <figcaption>The same joint on the machine, leads running down the arm. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Screw the camera lamp ring onto the arm" %}

The ring goes on the far end of the arm, and is what the lamp and the camera hang from. It straddles the arm, and it works the same way as the joint below it: 4 more {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, two per side, into the same two holes.

That is **12 M3 × 12 per arm**: 8 at the mount joint, 4 here. Six holes, a screw into each end of every one.

{% include step.html n="4" title="Hook the prepared LED strip onto the reflector" %}

Push the six **Inner reflector LED hooks** into the sockets around the rim of the **Lamp inner reflector**, evenly spaced. They are a friction fit and there are no screws. Each hook holds the LED strip against the reflector.

The strip itself is cut and wired on [Preparing the LED strip]({{ '/hardware/helpers/led-strip/' | relative_url }}): 950 mm, cut on a printed mark, with a red and a black wire on the cut end. Have one ready before you start this step.

**Fitting it.** Two turns, LEDs facing inwards.

1. Peel the blue film off the first stretch of the strip and start it under one of the hooks, adhesive against the inside of the skirt, with the wired end where you want the leads to leave the lamp.
2. Work it round the skirt until you are back where you started. That is one turn.
3. Drop down to the next clips and go round again for the second turn, peeling the film as you go.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-strip-first-turn-w1600-101009ec515a.jpg" alt="The strip run once around the inside of the reflector skirt, back at its starting point, with the blue film being peeled off the length still to go">
    <figcaption>One turn round, peeling as you go. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-strip-second-turn-w1600-e7a417c98b26.jpg" alt="Both turns of strip in the skirt, one above the other, film gone, with the red and black leads leaving the reflector at one side">
    <figcaption>Second turn in, on the next clips down, leads out at one side. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

**Wiring it back to the board** is [Make your own LED drop]({{ '/hardware/electronics/led-drop/' | relative_url }}): the run from those two wires to an LED header. Nothing is joined end to end here, so the far end of the strip stays dead. The strip runs at 24 V off the basically board.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-lit-from-below-w1600-bb9d54f4f43e.jpg" alt="The lamp lit, photographed from underneath: a ring of LED strip glowing around the outside of the white reflector, the reflector's central funnel in the middle, and the arm behind it">
  <figcaption>Lit, from below. The strip rings the reflector and the light reaches the parts off the white. <cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include step.html n="5" title="The outer cover" %}

The **Lamp outer cover** pushes down over the reflector. It is a friction fit and has no screw hole anywhere. It stands slightly proud of the reflector, so the camera clasp ends up recessed in the opening at its centre.

**Leave it off until the camera is in.** The cover is what holds the camera down: the clasp is wider than the opening in the middle of the cover, so the cover overlaps its rim and traps it, and until then the camera lifts straight back out. Both camera pages put the cover on as their last bench step, after the clasp is in the ring.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-underside-full-0e2b1e5a0fb9.png" alt="CAD render of the camera lamp seen from below: the inside of the cover with the reflector dome, the LED hooks spaced around the rim, the camera at the centre, and the arm reaching up into it">
  <figcaption>From below, with the reflector inside the cover and the hooks around the rim. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
</figure>

<div class="img-placeholder">Photo of the cover going on, or on: pending from the build.</div>

## The finished result

An arm with its dovetail at one end and its ring at the other, plus a reflector wired and ready to go over that ring. Build three of each, and take them to the camera page for the channel they belong to.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-arm-assembled-w1600-735fdcc7ecd6.jpg" alt="The whole camera lamp arm assembled on the bench: the dovetailed mount end, the bracket running along the joint with its screws, the bend, and the lamp ring at the far end">
  <figcaption>Both sections joined, dovetail at one end and the ring at the other. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

Back to [Camera lamps]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}).
