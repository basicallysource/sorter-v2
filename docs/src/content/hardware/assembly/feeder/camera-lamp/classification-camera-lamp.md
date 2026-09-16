---
layout: default
title: Classification camera lamp (C4)
type: how-to
section: hardware
slug: assembly-classification-camera-lamp
kicker: Feeder — Classification camera lamp
lede: A lamp arm finished with the IMX415 4K module, clasped between its two halves and pushed into the ring, with the lamp and its cover over the top. Build one.
permalink: /hardware/assembly/feeder/camera-lamp/classification-camera-lamp/
author: reveryx
contributors: [spencer, danny, brickcyclealice, barthel]
og_image: https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg
warning: >-
  **Steps 3 and 4 are not verified against a build.** Steps 1 and 2 are photographed on real
  builds. Still open: which of the ring's two sockets the clasp is meant to use (step 2); the
  cover going on, which has no build photograph yet (step 3); and the arm mount's dovetail onto
  the NEMA bracket (step 4), which a builder has described but nobody has dimensioned or
  photographed. Everything else is measured off the published STLs. Fill the gaps in as you build.
parts_needed:
  - part: cam-imx415
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

This is the lamp that hangs over the classification channel, the stage the machine identifies the part on. **Build one.**

**It carries the IMX415 4K module.** That is the only thing that differs from the [feeder camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/feeder-camera-lamp/' | relative_url }}), which takes the OV9732 720p. The clasp, the screws and every step below are the same on both.

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

{% include step.html n="2" title="Push the clasp into the ring" %}

**Into the ring, no screws.** The clasped camera pushes into the camera lamp ring on the arm. Nothing fastens it: the only screws in this build are the two holding the clasp's own halves together.

The clasp's two halves form a spigot that plugs into a socket in the ring. **The ring has two of these sockets, and which one is intended is not recorded.** Nothing on this page depends on it: use the one that leaves the camera's lead running clear of the arm, and check the lens points straight down before you go on. Which way round the picture arrives is set in software later, not here.

**Expect it to sit loose.** The cover, two steps down, is what traps the clasp and holds the camera in. Until then the camera can lift straight back out, so do not pick the lamp up by it.

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

{% include step.html n="3" title="Lamp over the top, then the cover" %}

Set the reflector on the arm over the clasped camera, then push the **Lamp outer cover** down over it.

**The lamp is not fastened to the arm at all.** It sits on it under its own weight, which is how it is recorded and how it comes apart again for a print change. The cover is a friction fit too, with no screw hole anywhere.

Order matters here in one place only: the camera has to be in the clasp and the clasp in the ring before the cover goes over the top, because the cover closes around the clasp and is what holds the camera down.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-top-full-edc4616e7088.png" alt="CAD render of the assembled camera lamp from above: the grey cover with the camera clasp and board in the central opening, a slot near the rim, and the arm coming in from the lower left">
  <figcaption>Assembled, from above. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-camera-seated-w1600-eede61656118.jpg" alt="Looking down on the top of an assembled camera lamp: the grey cover with a circular opening at its centre, the camera board seated in the clasp inside it, its lead plugged in and running off to one side">
  <figcaption>The camera sits at the centre of the lamp, looking straight down through the reflector. <cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include step.html n="4" title="Later: hang the arm on the C-channel" %}

**Not at the bench.** The lamp goes onto its channel later, when the channels are standing on the top plate. Read this step then, and put the finished lamp aside for now.

**It hangs off a dovetail, not a screw.** Slide the dovetail on the bottom of the arm mount down onto the bottom of the channel's NEMA bracket until it stops. That is the whole joint: the mount has no other fixing, and the lamp's weight holds it in the rail.

It is a printed joint and nobody has measured the fit yet, so it may be tight or it may have a little play. **Do not force it and do not file it down**: if it will not go on, say so in the Discord with a photo, because that is a part problem rather than a step you are doing wrong.

**Do this when the channels are standing in place, not on the bench.** The lamps go on during [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), onto the [classification channel]({{ '/hardware/assembly/feeder/c-channels/classification-channel/' | relative_url }}).

Write down where the lamp ended up over its channel. Its height and overhang change what the camera sees, and [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) afterwards is software, not a way to fix a lamp in the wrong place.

## The finished result

An arm, a lamp and the 4K camera hanging over the classification channel, lit. Build one.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
  <figcaption>A finished lamp over its channel, lit. <cite>Photo: Spencer.</cite></figcaption>
</figure>

Wiring is [Preparing the LED strip]({{ '/hardware/helpers/led-strip/' | relative_url }}) for the strip, and the [electronics]({{ '/hardware/electronics/' | relative_url }}) page for the camera.

Back to [Camera lamps]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}).
