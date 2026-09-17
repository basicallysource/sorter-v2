---
layout: default
title: Feeder camera lamp (C2 and C3)
type: how-to
section: hardware
slug: assembly-feeder-camera-lamp
kicker: Feeder — Feeder camera lamp
lede: A lamp arm finished with the OV9732 720p module, clasped between its two halves and pushed into the ring, with the lamp and its cover over the top. Build two.
permalink: /hardware/assembly/feeder/camera-lamp/feeder-camera-lamp/
author: reveryx
contributors: [spencer, danny, brickcyclealice, barthel]
og_image: https://assets.basically.website/sorter-docs/camera-lamp-camera-seated-w1600-eede61656118.jpg
warning: >-
  **Step 5 is not verified against a build.** Steps 1 to 4 are photographed on real builds. Still
  open: which of the ring's two sockets the clasp is meant to use (step 3), and the arm mount's
  dovetail onto the NEMA bracket (step 5), which a builder has described but nobody has
  dimensioned or photographed. Fill the gaps in as you build.
parts_needed:
  - part: cam-ov9732
    qty: 1
  - part: camera-clasp-top
    qty: 1
  - part: camera-clasp-bottom
    qty: 1
  - part: scr-m3-8-cs
    qty: 2
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/camera-lamp/lamp-arm/' | relative_url }}">lamp arm</a> before you start.</strong> This page does not build the arm, the reflector or the cover: it takes a finished one and puts a camera in it. The arm's parts and its 12 screws are on that page.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-underside-full-0e2b1e5a0fb9.png" alt="CAD render of the camera lamp seen from below: the inside of the cover with the reflector dome, the LED hooks spaced around the rim, the camera at the centre, and the arm reaching up into it">
    <figcaption>A finished lamp arm, from below. The camera at its centre is what this page adds. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
  </figure>
</div>

This is the lamp that hangs over C2 and C3, the two feeder channels. **Build two.**

**It carries the OV9732 720p module.** That is the only thing that differs from the [classification camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/classification-camera-lamp/' | relative_url }}), which takes the IMX415 4K. The clasp, the screws and every step below are the same on both.

{% include fastener-legend.html %}

{% include step.html n="1" title="Clasp the camera between the two halves" %}

The camera board sits in the recess in the **Camera clasp top**. Put the **Camera clasp bottom** over it with the lens through the opening, and secure the two halves with 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws. They go up through the bottom half into the top, one either side of the board, and seat flush in the countersinks.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-clasp-board-seated-full-2c6684aef97a.jpg" alt="A camera board sitting in the square recess of a grey printed clasp half, component side up with the black cylindrical lens standing in the middle, and a screw hole in the plastic below the board">
  <figcaption>The board in the clasp top, photographed upside down. <cite>Photo: Danny.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-clasp-closed-full-eccd71244410.jpg" alt="The second clasp half closed over the camera board, the lens standing through the square opening in it and a black countersunk screw seated flush in the plastic at the near edge">
  <figcaption>The bottom half closed over it, one of the two screws seated. <cite>Photo: Danny.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-camera-in-clasp-no-cable-w1600-79b5a08ea522.jpg" alt="A hand holding the closed camera clasp, the camera board seated in the round grey disc with its ribbon socket empty and a rectangular slot in the plastic beside it">
  <figcaption>The camera in the clasp. Its cable is not on yet; that goes on in step 4. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="2" title="Click the reflector onto the arm" %}

**The reflector goes on before the camera does.** Push the ring on the end of the arm down into the middle of the **Lamp inner reflector** and **press firmly until it clicks**. It is a snap fit and there are no screws in it.

Do this first and the reflector cannot be dropped over a camera that is already in the ring, which is the part of this build that goes wrong.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-reflector-onto-arm-w1600-bd84acd2f247.jpg" alt="The lamp arm lying with its ring end pushed into the centre of the white inner reflector, the two turns of LED strip visible around the inside of the skirt">
    <figcaption>The arm pushed into the reflector, from above. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-reflector-on-arm-angle-w1600-5866be2e9b46.jpg" alt="The same arm and reflector held up at an angle, the reflector square on the end of the arm and the arm's two bracketed sections running away from it">
    <figcaption>Clicked home, from the side. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Push the clasp into the ring" %}

**Into the ring, no screws.** The clasped camera pushes into the camera lamp ring on the arm, down through the middle of the reflector you fitted in step 2. Nothing fastens it: the only screws in this build are the two holding the clasp's own halves together.

**This is the delicate one.** The camera is easy to drop as it goes in, and it has to go in far enough: push until the clasp sits firmly in the ring rather than stopping at first resistance. Work over the bench, not over the floor.

The clasp's two halves form a spigot that plugs into a socket in the ring. **The ring has two of these sockets, and which one is intended is not recorded.** Nothing on this page depends on it: use the one that leaves the camera's lead running clear of the arm, and check the lens points straight down before you go on. Which way round the picture arrives is set in software later, not here.

**Expect it to sit loose.** The next step, the cover, is what traps the clasp and holds the camera in. Until then the camera can lift straight back out, so do not pick the lamp up by it.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-clasp-in-ring-back-w1600-84825cdaec58.jpg" alt="The clasped camera snapped into the lamp ring, seen from behind: the board's back and its ribbon connector inside the round clasp, with the arm running off to the left">
    <figcaption>From behind, snapped into the ring. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-clasp-in-ring-front-w1600-431110b2f55b.jpg" alt="The same from the front, the lens standing through the opening in the clasp and the two clasp screws above and below it">
    <figcaption>From the front, lens through the opening. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-camera-in-ring-from-below-w1600-18f0664f8f5b.jpg" alt="Looking up into the reflector from below: two turns of LED strip round the skirt held by the hooks, the arm coming down through the middle, and the clasped camera seated in the ring at the centre with its lens facing out">
  <figcaption>From below, with the reflector already on: the camera seated in the ring at the centre. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="4" title="Thread the cable through the cover, then press it on" %}

Plug the camera's cable into the board now, if it is not on already, and route it out of the lamp before the cover goes over the top. The cover has a rectangular slot near its rim for it.

<ol class="numbered-steps">
  <li>Thread the camera cable up through the slot in the <strong>Lamp outer cover</strong> <strong>before</strong> you offer the cover up. Doing it afterwards means taking the cover back off.</li>
  <li>Put the lamp flat on the table, cover on top, and press straight down until it seats.</li>
</ol>

**It is a friction fit with no screw hole anywhere**, and it is what holds the camera down: the clasp is wider than the opening in the middle of the cover, so the cover overlaps its rim and traps it.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-cable-through-cover-w1600-455f0670387d.jpg" alt="The reflector on the arm with the clasped camera in its centre, lying beside the grey outer cover turned upside down, the black camera cable running from the board across to the cover's central opening">
    <figcaption>Cable through the cover first, then the cover goes on. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-cover-pressed-on-w1600-c4ab9aef9369.jpg" alt="The cover pressed down onto the reflector, seen from above at an angle, the camera board in the central opening and the cable leaving through the slot near the rim">
    <figcaption>Pressed on flat, cable out through the slot. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-cover-on-cord-through-slot-w1600-9678252fab1b.jpg" alt="The finished lamp from above: the grey cover seated on the reflector, the camera clasp recessed in the central opening, and the cord coming up through the rectangular slot in the cover">
    <figcaption>The cord up through the cover's slot. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-cover-on-cord-out-flat-w1600-6a44a9927184.jpg" alt="The same finished lamp lying flat, the cover on and the camera board centred in its opening, cord running off to one side">
    <figcaption>The same, flat on the bench. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-cover-on-cord-out-angle-w1600-a6243cca6314.jpg" alt="The finished lamp from a lower angle with the arm running off to the left, the cover on and the camera cord leaving the slot">
    <figcaption>And from the side, arm out to the left. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="5" title="Later: hang the arm on the C-channel" %}

**Not at the bench.** The lamp goes onto its channel later, when the channels are standing on the top plate. Read this step then, and put the finished lamp aside for now.

**It hangs off a dovetail, not a screw.** Slide the dovetail on the bottom of the arm mount down onto the bottom of the channel's NEMA bracket until it stops. That is the whole joint: the mount has no other fixing, and the lamp's weight holds it in the rail.

It is a printed joint and nobody has measured the fit yet, so it may be tight or it may have a little play. **Do not force it and do not file it down**: if it will not go on, say so in the Discord with a photo, because that is a part problem rather than a step you are doing wrong.

The lamp goes on during [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), onto the two [feeder channels]({{ '/hardware/assembly/feeder/c-channels/feeder-channels/' | relative_url }}).

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
  <figcaption>What it looks like once it is on, lit. <cite>Photo: Spencer.</cite></figcaption>
</figure>

Write down where the lamp ended up over its channel. Its height and overhang change what the camera sees, and [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) afterwards is software, not a way to fix a lamp in the wrong place.

## The finished result

A finished lamp on the bench: the arm, the shaded lamp and the 720p camera seated at its centre. Build two, and they go onto their channels later.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-camera-seated-w1600-eede61656118.jpg" alt="Looking down on the top of an assembled camera lamp: the grey cover with a circular opening at its centre, the camera board seated in the clasp inside it, its lead plugged in and running off to one side">
  <figcaption>A finished lamp on the bench, camera seated at its centre. <cite>Photo: Spencer.</cite></figcaption>
</figure>

Wiring is [Preparing the LED strip]({{ '/hardware/helpers/led-strip/' | relative_url }}) for the strip, and the [electronics]({{ '/hardware/electronics/' | relative_url }}) page for the camera.

Back to [Camera lamps]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}).
