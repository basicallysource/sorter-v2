---
layout: default
title: Camera lamp
type: how-to
section: hardware
slug: assembly-camera-lamp
kicker: Feeder — Camera lamp
lede: The arm, the shaded lamp and the camera that hang over a C-channel.
permalink: /hardware/assembly/feeder/camera-lamp/
author: reveryx
contributors: [spencer, danny]
og_image: https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg
warning: >-
  **Steps 6, 7 and 8 are not verified against a build.** Steps 1 to 5 are photographed on
  real builds, BrickCycleAlice's and Danny's, and the 12 screws into 6 holes in steps 2 and
  3 were confirmed by ReveryX against the parts. Still open: which of the ring's two sockets
  the clasp is meant to use (step 6); how the arm mount fastens to a C-channel, which nobody
  has written down and the CAD does not show (step 7); and the cover going on, which has no
  build photograph yet (step 8). Wiring the strip back to the board is not on this page at
  all. Everything else is measured off the published STLs. Fill the gaps in as you build.
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
  - part: camera-clasp-bottom
    qty: 1
  - part: camera-clasp-top
    qty: 1
  - part: cam-ov9732
    qty: 1
  - part: lamp-inner-reflector
    qty: 1
  - part: inner-reflector-led-hook
    qty: 6
  - part: lamp-outer-cover
    qty: 1
  - part: scr-m3-12-cs
    qty: 12
  - part: scr-m3-8-cs
    qty: 2
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channel/' | relative_url }}">C-channel</a> before you start.</strong> The lamp hangs over one, on an arm that mounts to it. This page builds the lamp, not the channel.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
    <figcaption>A finished C-channel, from the C-channel page. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The camera lamp is one arm carrying one light and one camera over a channel. The light is a ring of LED strip inside a white reflector, under a grey cover, so what reaches the parts is bounced rather than aimed straight at them, and the camera looks straight down through the hole in the middle of the reflector.

It replaces the [light post]({{ '/hardware/assembly/feeder/light-post/' | relative_url }}) and the [overhead camera mount]({{ '/hardware/assembly/feeder/camera-mount/' | relative_url }}), which were the previous side-light-plus-rod-arm arrangement and are retired.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
  <figcaption>The finished thing, over a channel, lit. <cite>Photo: Spencer.</cite></figcaption>
</figure>

**The parts list above is one lamp's worth.** A machine takes three lamps, so three of everything on it: C2 and C3 with the OV9732, and the classification channel with the [IMX415]({{ '/hardware/assembly/feeder/classification-chamber/' | relative_url }}) 4K module instead. Everything else is identical between the three. **C1, the bulk bucket, takes no lamp**: it is fed in bulk and nothing reads vision off it.

<div class="callout">
  <p><b>If you printed four, one set is spare.</b> The parts list gave C1 a lamp of its own until 2026-09-08, when Jon confirmed the machine takes three. The software agrees: the crop zones are the second channel, the third channel and the classification channel, and nothing reads vision off the bulk channel, so C1 needs neither the lamp nor an OV9732. Question raised by BrickCycleAlice, 2026-09-05.</p>
</div>

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

**No heat inserts anywhere on this assembly.** Every screw is self-tapping into printed plastic. Measured across all seven printed parts, the holes come in exactly two sizes: 2.8 mm, which is the thread-forming pilot, and 3.5 mm, which is clearance for a screw on its way into one of those pilots. There is nothing in the 4.2 mm range an insert would need.

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
    <p><strong>Print counts, if you are printing for the whole machine:</strong> 3 each of the mount, arm, bracket A, bracket B, ring, both clasp halves, reflector and cover, and <strong>18</strong> LED hooks, six per lamp. The hooks are the ones people come up short on.</p>
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

**Which way round the brackets go:** their angled ends come in towards the end where the dovetail is printed, not away from it.

**The ends of the arm are shaped**, so the two only mate one way round. If it does not seem to fit, swap the piece end for end rather than forcing it.

**The two brackets share their screw holes.** Each pilot runs 19.8 mm straight through the joint, so bracket A's screw enters one end and bracket B's the other: eight screws into four holes.

Drive all 8 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, four per bracket, and stop as each head seats: you are cutting a thread in plastic and the far half of the hole is somebody else's screw. **12 mm is the only length that fits**, two 16s would meet inside the hole before either seated.

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

This is the joint between the arm's two sections. The ring end goes onto the far end of the arm, and is what the lamp and the camera hang from. It works the same way as the joint below it: four 3.5 mm clearance holes in the ring, two 2.8 mm pilot holes through the end of the arm, so the remaining 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws go two per side into the same two holes. The ring straddles the arm.

That is all 12 of the M3 × 12 in the parts list: 8 at the mount joint, 4 here. **Six holes, a screw into each end of every one of them.** ReveryX confirmed that count against the parts on 2026-09-05; everything else about these two steps is off the STLs.

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

**Expect it to sit loose until the cover goes on.** The clasp top is 65.5 mm across and the opening in the middle of the Lamp outer cover is 65.0 mm, so it is the cover, in the last step, that traps the clasp and holds the camera down. Until then it can lift straight back out, so do not pick the lamp up by the camera.

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

Six **Inner reflector LED hooks** friction-fit into the rim of the **Lamp inner reflector**, evenly spaced 60° apart, one per 2.7 mm socket around its outside. Each hook retains the LED strip against the reflector. No screws.

**How much strip, measured off the reflector.** The strip sits against the inner face of the reflector's outer skirt, which is 147 mm across and about 18 mm tall, so one turn around it is **462 mm**. The photograph below shows two turns side by side in that skirt, which puts a lamp at roughly **0.92 m** and a three-lamp machine at about **2.8 m**. The strip in the parts calculator is a 24 V daylight-white 6000 K COB strip sold as a 5 m roll, one roll per machine, which covers all three.

**Fitting it.** Two turns, and **950 mm** on the build photographed here.

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

**Still open:** how the strip is joined and wired back from here. The strip is not a line in the lamp's parts list, and the drop to the board is its own job. Spencer said on 2026-09-06 that the strips run at 24 V off the LED headers on the basically board.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-lit-from-below-w1600-bb9d54f4f43e.jpg" alt="The lamp lit, photographed from underneath: a ring of LED strip glowing around the outside of the white reflector, the reflector's central funnel in the middle, and the arm behind it">
  <figcaption>Lit, from below. The strip rings the reflector and the light reaches the parts off the white. <cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include step.html n="6" title="Bring the three together" %}

Plug the clasped camera into the ring, then set the lamp on top. **The lamp is not fastened to the arm at all.** It sits on it under its own weight, which is how it is recorded and how it comes apart again for a print change.

The clasp is what carries the camera into the lamp: its two halves form a 4 mm spigot on the diagonal, which plugs into a 4.2 mm socket in the camera lamp ring. The ring has two of those sockets at the same radius; which one is intended, and whether the module is meant to come out again, is not recorded. <span class="fastener-todo">fastener not recorded</span>

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

**Not recorded, and not in the CAD either.** The C-channel arm mount carries exactly two holes, the pair the brackets use, and nothing that would fasten it to a channel, so how it is held there is a real gap rather than a missing sentence. The mount is 83 mm long and stands off the channel wall; the photographs show it against the outside of the channel with the arm rising over the rim. <span class="fastener-todo">fastener not recorded</span>

Write down what you did, and where the lamp ended up relative to the channel: height and overhang both change what the camera sees, and the [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) step afterwards is software, not a way to fix a lamp in the wrong place.


{% include step.html n="8" title="Cover the reflector" %}

The **Lamp outer cover** friction-fits down over the reflector, and that is the whole joint: it has no screw hole anywhere in its geometry. The reflector is 150 mm across, the cover 153 mm, and the cover stands about 1.5 mm proud of the reflector at the top so the camera clasp sits recessed in the opening at its centre.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-underside-full-0e2b1e5a0fb9.png" alt="CAD render of the camera lamp seen from below: the inside of the cover with the reflector dome, the LED hooks spaced around the rim, the camera at the centre, and the arm reaching up into it">
  <figcaption>From below, with the reflector inside the cover and the hooks around the rim. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
</figure>

<div class="img-placeholder">Photo of the cover going on, or on: pending from the build.</div>

Wiring, for both the LED strip and the camera, is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page. Build the other three lamps the same way, and see [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for how the channels themselves sit together.
