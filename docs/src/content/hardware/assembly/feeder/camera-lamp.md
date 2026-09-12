---
layout: default
title: Camera lamps
type: how-to
section: hardware
slug: assembly-camera-lamp
kicker: Feeder — Camera lamps
lede: The arm, the shaded lamp and the camera that hang over C2, C3 and the classification channel. Build three.
permalink: /hardware/assembly/feeder/camera-lamp/
author: reveryx
contributors: [spencer, danny, brickcyclealice]
og_image: https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg
warning: >-
  **Steps 6, 7 and 8 are not verified against a build.** Steps 1 to 5 are photographed on real
  builds. Still open: which of the ring's two sockets the clasp is meant to use (step 6); the
  arm mount's dovetail onto the NEMA bracket (step 7), which a builder has described but nobody
  has dimensioned or photographed; and the cover going on, which has no build photograph yet
  (step 8). Everything else is measured off the published STLs. Fill the gaps in as you build.
parts_needed:
  - part: c-channel-arm-mount
    qty: 3
  - part: camera-lamp-arm
    qty: 3
  - part: arm-bracket-a
    qty: 3
  - part: arm-bracket-b
    qty: 3
  - part: camera-lamp-ring
    qty: 3
  - part: camera-clasp-bottom
    qty: 3
  - part: camera-clasp-top
    qty: 3
  - part: lamp-inner-reflector
    qty: 3
  - part: inner-reflector-led-hook
    qty: 18
  - part: lamp-outer-cover
    qty: 3
  - part: cam-ov9732
    qty: 2
  - part: cam-imx415
    qty: 1
  - part: scr-m3-12-cs
    qty: 36
  - part: scr-m3-8-cs
    qty: 6
  - part: led-strip-24v
    qty: 3
  - part: led-strip-connector-8mm
    qty: 3
  - part: dupont-lead-2p-1m
    qty: 3
---

A camera lamp is one arm carrying one light and one camera over a channel. The light is a ring of LED strip inside a white reflector, under a grey cover, so the light reaches a part bounced off the white rather than aimed straight at it. The camera looks down through the hole in the middle of the reflector.

**Build three.** C2, C3 and the classification channel each take one. **The bulk channel (C1) takes none**, because the machine does not look at it.

**Two of the three carry the OV9732 camera. The classification channel's carries the IMX415 4K module instead.** Nothing else differs between the three lamps.

**The parts list above is the whole machine, all three lamps.** The steps below build one lamp. Repeat them three times, with the right camera in each.

<div class="callout">
  <p><b>If you printed four sets, one is spare.</b> The parts list gave C1 a lamp of its own until 2026-09-08. It takes none.</p>
</div>

Build the lamps before the channels that carry them: two of the [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}) pages need one to start. A lamp is built on the bench and goes onto its channel later, in step 7.

It replaces the [light post]({{ '/hardware/assembly/feeder/light-post/' | relative_url }}) and the [overhead camera mount]({{ '/hardware/assembly/feeder/camera-mount/' | relative_url }}), which are retired.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Colours.</strong> The <strong>Lamp inner reflector</strong> and its six <strong>LED hooks</strong> print ivory white, and that is not cosmetic: they are the reflector. The <strong>Lamp outer cover</strong> is ash grey. The arm, the mount, both brackets, the ring and both clasp halves follow the channel colour like the rest of that channel's parts.</p>
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

That is **12 M3 × 12 per lamp**: 8 at the mount joint, 4 here. Six holes, a screw into each end of every one.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-arm-assembled-w1600-735fdcc7ecd6.jpg" alt="The whole camera lamp arm assembled on the bench: the dovetailed mount end, the bracket running along the joint with its screws, the bend, and the lamp ring at the far end">
  <figcaption>Both sections joined, dovetail at one end and the ring at the other. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="4" title="Clasp the camera between the two halves" %}

The camera board sits in the recess in the **Camera clasp top**. Put the **Camera clasp bottom** over it with the lens through the opening, and secure the two halves with 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws. They go up through the bottom half into the top, one either side of the board, and seat flush in the countersinks.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-clasp-board-seated-full-2c6684aef97a.jpg" alt="A camera board sitting in the square recess of a grey printed clasp half, component side up with the black cylindrical lens standing in the middle, and a screw hole in the plastic below the board">
  <figcaption>The board in the clasp top, photographed upside down. <cite>Photo: Danny.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-clasp-closed-full-eccd71244410.jpg" alt="The second clasp half closed over the camera board, the lens standing through the square opening in it and a black countersunk screw seated flush in the plastic at the near edge">
  <figcaption>The bottom half closed over it, one of the two screws seated. <cite>Photo: Danny.</cite></figcaption>
</figure>

**Into the ring, no screws.** The clasped camera pushes into the camera lamp ring. Nothing fastens it: the only screws in this step are the two holding the clasp's own halves together.

**Expect it to sit loose until the cover goes on.** The cover, in the last step, is what traps the clasp and holds the camera down. Until then the camera can lift straight back out, so do not pick the lamp up by it.

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

{% include step.html n="5" title="Hook the LED strip onto the reflector" %}

Push the six **Inner reflector LED hooks** into the sockets around the rim of the **Lamp inner reflector**, evenly spaced. They are a friction fit and there are no screws. Each hook holds the LED strip against the reflector.

**Cut 950 mm of strip for each lamp**, which is two turns around the inside of the skirt. **Cut only on the printed marks**, never between them: the solder pads are at the marks, so a cut anywhere else leaves nothing to connect to. One 5 m roll gives five of these lengths, so a roll covers all three lamps.

**Fitting it.** Two turns, LEDs facing inwards.

1. Peel the blue film off the first stretch of the strip and start it under one of the hooks, adhesive against the inside of the skirt.
2. Work it round the skirt until you are back where you started. That is one turn.
3. Drop down to the next clips and go round again for the second turn, peeling the film as you go.

The bare wires at the starting end are trimmed later, when the drop to the board is made up. Only the first strip has them: the other two lamps take plain cut lengths off the roll.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-strip-start-w1600-3d30eeb9a913.jpg" alt="The white reflector with the leading end of the LED strip started under the hooks in its skirt, the rest of the strip still carrying its blue protective film">
    <figcaption>Starting it, film peeled back only as far as needed. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-strip-first-turn-w1600-101009ec515a.jpg" alt="The strip run once around the inside of the reflector skirt, back at its starting point, with the blue film being peeled off the length still to go">
    <figcaption>One turn round, peeling as you go. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-strip-second-turn-w1600-e7a417c98b26.jpg" alt="Both turns of strip in the skirt, one above the other, film gone, with the red and black leads leaving the reflector at one side">
    <figcaption>Second turn in, on the next clips down, leads out at one side. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

**Wiring it back to the board** is [Make your own LED drop]({{ '/hardware/electronics/led-drop/' | relative_url }}): the clamp-on connector onto those bare wires, and the run to an LED header. Nothing is joined end to end here, so the far end of the strip stays dead. The strip runs at 24 V off the basically board.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-lit-from-below-w1600-bb9d54f4f43e.jpg" alt="The lamp lit, photographed from underneath: a ring of LED strip glowing around the outside of the white reflector, the reflector's central funnel in the middle, and the arm behind it">
  <figcaption>Lit, from below. The strip rings the reflector and the light reaches the parts off the white. <cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include step.html n="6" title="Bring the three together" %}

Plug the clasped camera into the ring, then set the lamp on top. **The lamp is not fastened to the arm at all.** It sits on it under its own weight, which is how it is recorded and how it comes apart again for a print change.

The clasp is what carries the camera into the lamp: its two halves form a spigot that plugs into a socket in the camera lamp ring. **Not recorded:** the ring has two of those sockets, and which one is intended is not written down anywhere. <span class="fastener-todo">fastener not recorded</span>

Order matters here in one place only: the camera has to be in the clasp and the clasp in the ring before the cover goes over the top, because the cover closes around the clasp.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-top-full-edc4616e7088.png" alt="CAD render of the assembled camera lamp from above: the grey cover with the camera clasp and board in the central opening, a slot near the rim, and the arm coming in from the lower left">
  <figcaption>Assembled, from above. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-camera-seated-w1600-eede61656118.jpg" alt="Looking down on the top of an assembled camera lamp: the grey cover with a circular opening at its centre, the camera board seated in the clasp inside it, its lead plugged in and running off to one side">
  <figcaption>The camera sits at the centre of the lamp, looking straight down through the reflector. <cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include step.html n="7" title="Mount the arm on the C-channel" %}

**It hangs off a dovetail, not a screw.** Slide the dovetail on the bottom of the arm mount onto the bottom of the channel's NEMA bracket. That is the whole joint: the mount has no other fixing. **Not recorded:** the mating faces are not dimensioned yet.

**Do this when the channels are standing in place, not on the bench.** The lamp goes on during [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}).

Write down where the lamp ended up over its channel. Its height and overhang change what the camera sees, and [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) afterwards is software, not a way to fix a lamp in the wrong place.


{% include step.html n="8" title="Cover the reflector" %}

Push the **Lamp outer cover** down over the reflector. It is a friction fit and has no screw hole anywhere. It stands slightly proud of the reflector, so the camera clasp ends up recessed in the opening at its centre, and it is what holds the camera down.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-underside-full-0e2b1e5a0fb9.png" alt="CAD render of the camera lamp seen from below: the inside of the cover with the reflector dome, the LED hooks spaced around the rim, the camera at the centre, and the arm reaching up into it">
  <figcaption>From below, with the reflector inside the cover and the hooks around the rim. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
</figure>

<div class="img-placeholder">Photo of the cover going on, or on: pending from the build.</div>

## The finished result

One arm, one lamp, one camera, hanging over its channel and lit. Build three.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
  <figcaption>A finished lamp over its channel, lit. <cite>Photo: Spencer.</cite></figcaption>
</figure>

Wiring is [Make your own LED drop]({{ '/hardware/electronics/led-drop/' | relative_url }}) for the strip, and the [electronics]({{ '/hardware/electronics/' | relative_url }}) page for the camera. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for how the channels themselves sit together.
