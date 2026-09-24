---
layout: default
title: Classification camera lamp (C4)
type: how-to
section: hardware
slug: assembly-classification-camera-lamp
kicker: Feeder — Classification camera lamp
lede: The IMX415 4K module clasped between its two halves, pushed into the ring on the arm, and the arm pushed up into a finished lamp. Build one.
permalink: /hardware/assembly/feeder/camera-lamp/classification-camera-lamp/
author: reveryx
contributors: [spencer, danny, brickcyclealice, barthel, daddyosbricksbill]
og_image: https://assets.basically.website/sorter-docs/assembly-camera-lamp-imx415-finished-full-ffc5214cce8a.jpg
warning: >-
  Steps 1 to 3 are photographed on a real build of the feeder lamp, which is this build apart from
  the camera module, and step 4 on a second build. The dovetail fit itself (step 4) has never been
  dimensioned. Fill the gaps in as you build.
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

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-camera-in-clasp-no-cable-w1600-79b5a08ea522.jpg" alt="A hand holding the closed camera clasp, the camera board seated in the round grey disc with its ribbon socket empty and a rectangular slot in the plastic beside it">
  <figcaption>A camera in the clasp. Its cable is not on yet; that goes on in step 4. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="2" title="Push the clasp into the ring" %}

**Into the ring, no screws.** The clasped camera pushes into the camera lamp ring on the end of the arm, with the lamp still off the arm entirely. Nothing fastens it: the only screws in this build are the two holding the clasp's own halves together.

**Push until it sits firmly**, not just until it meets resistance. The next step pushes the arm up inside the lamp, and a clasp that is not fully home lifts out on the way.

The clasp's two halves form a spigot that plugs into a socket in the ring. **The ring has two of these sockets**, and both take the clasp. The machine these steps come from uses the left-hand one on all three lamps, looking down at the lamp from above. Use the same socket on all three, keep the camera's lead running clear of the arm, and check the lens points straight down before you go on.

**Which socket changes what the camera can see**, not just which way up the picture arrives. If a channel's drop zone and its exit are not both in frame at [first setup]({{ '/sorter/first-setup/' | relative_url }}) step 7, that is the mounting, and rotating the view in the camera settings will not fix it.

**Expect it to sit loose.** The lamp's cover is what traps the clasp and holds the camera in, and that happens in the next step, once the arm is up inside the lamp. Until then the camera can lift straight back out, so do not pick the arm up by it.

**The lead plugs in from above on this one.** The IMX415's cable stands up out of the board rather than leaving flat through the cover's slot the way the OV9732's does, so leave room above the lamp for it and for the bend in the cable.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-imx415-lead-routing-w1600-ff6852248c3f.jpg" alt="The classification lamp, marked 4, from a lower angle: the camera cable standing up out of the board, the red and black lamp leads looped over the cover and cable-tied clear of it, and the rectangular slot in the cover below">
  <figcaption>On C4, with the LED leads tied clear of the camera cable. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
</figure>

{% include step.html n="3" title="Push the arm up into the lamp" %}

The [lamp arm]({{ '/hardware/assembly/feeder/camera-lamp/lamp-arm/' | relative_url }}) page leaves you a finished lamp: reflector, LED strip and cover. **It keeps its cover on for this.**

<ol class="numbered-steps">
  <li>Hold the lamp and push the arm's ring up into the middle of the reflector from underneath until it seats.</li>
  <li>Plug the camera's cable in afterwards. It goes into the top of the board, so there is nothing to thread through the cover first.</li>
</ol>

**That is what holds the camera in.** The clasp is wider than the opening in the middle of the cover, so with the arm home the cover overlaps the clasp's rim and traps it.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>It is a tight pass.</b> The clasp is 67.76 mm across and the reflector's bore is 68.0 mm at the top, a quarter of a millimetre all round, so the clasp rubs the whole way up and can lift out of the ring as it goes. If that happens, take the arm back out, push the clasp fully home and try again.</p>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-camera-in-ring-from-below-w1600-18f0664f8f5b.jpg" alt="Looking up into the reflector from below: two turns of LED strip round the skirt held by the hooks, the arm coming down through the middle, and the clasped camera seated in the ring at the centre with its lens facing out">
    <figcaption>From below, with the arm home: the camera seated in the ring at the centre. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-cover-on-cord-through-slot-w1600-9678252fab1b.jpg" alt="The finished lamp from above: the grey cover seated on the reflector, the camera clasp recessed in the central opening, and the cord coming up through the rectangular slot in the cover">
    <figcaption>Finished: the clasp recessed in the cover's opening, lead out through the slot. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-top-full-edc4616e7088.png" alt="CAD render of the assembled camera lamp from above: the grey cover with the camera clasp and board in the central opening, a slot near the rim, and the arm coming in from the lower left">
  <figcaption>The same thing as designed, with the 4K module in place of the one in the photographs. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
</figure>

{% include step.html n="4" title="Later: hang the arm on the C-channel" %}

**Not at the bench.** The lamp goes onto its channel later, when the channels are standing on the top plate. Read this step then, and put the finished lamp aside for now.

**It hangs off a dovetail, not a screw.** The outside of the channel wall carries a row of dovetails. Use the **8th one from the channel exit**, counting anticlockwise seen from above, which is the last one before the channel above covers the wall. C2 and C3 use the 5th instead. **It goes on from underneath**: offer the mount up to the bottom edge of the wall, feed its rail into the dovetail and push it up until it clips over the top edge. That is the whole joint, and the mount has no other fixing.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>The dovetail on the arm can break</strong> when a lamp needs to be removed and repositioned. Use caution if repositioning is needed.</p>
</div>

It is a printed joint and the fit has not been dimensioned, so it may be tight or it may have a little play. **Do not force it and do not file it down**: if it will not go on, say so in the Discord with a photo, because that is a part problem rather than a step you are doing wrong.

The lamp goes on during [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), onto the [classification channel]({{ '/hardware/assembly/feeder/c-channels/classification-channel/' | relative_url }}).

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
  <figcaption>What it looks like once it is on, lit. <cite>Photo: Spencer.</cite></figcaption>
</figure>

Use the dovetail the count gives you rather than the one that looks right. Where the lamp sits changes what the camera sees, and [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) afterwards is software, not a way to fix a lamp in the wrong place.

## The finished result

A finished lamp on the bench: the arm, the shaded lamp and the 4K camera seated at its centre. Build one, and it goes onto its channel later.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-imx415-finished-full-ffc5214cce8a.jpg" alt="Looking down on a finished classification lamp: the grey cover with its square opening, the 4K camera board seated in the clasp inside it, and its cable plugged into the top of the board">
  <figcaption>A finished lamp, the 4K camera seated at its centre. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
</figure>

Wiring is [Preparing the LED strip]({{ '/hardware/helpers/led-strip/' | relative_url }}) for the strip, and the [electronics]({{ '/hardware/electronics/' | relative_url }}) page for the camera.

Back to [Camera lamps]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}).
