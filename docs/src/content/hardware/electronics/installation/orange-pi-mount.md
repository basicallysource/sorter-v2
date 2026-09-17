---
layout: default
title: Orange Pi mount
type: how-to
section: hardware
slug: electronics-orange-pi-mount
kicker: Electronics — Orange Pi mount
lede: The Orange Pi 5 standing off its mount, the 40 mm fan on its arm above it, and how the mount bolts to the frame.
permalink: /hardware/electronics/installation/orange-pi-mount/
author: barthel
contributors: [spencer]
og_image: https://assets.basically.website/sorter-parts/orange-pi-mount-v1-render-full-d5893e241c96.png
last_verified: 2026-09-17
parts_needed:
  - part: sbc-orange-pi-5
    qty: 1
  - part: fan-orange-pi-5-heatsink
    qty: 1
  - part: orange-pi-extrusion-mount
    qty: 1
  - part: fan-bracket-40mm
    qty: 1
  - part: fan-40mm-24v
    qty: 1
  - part: standoff-m3-10mm
    qty: 4
  - part: hsi-m3
    qty: 6
  - part: scr-m3-6-bhcs
    qty: 4
  - part: scr-m3-16-shcs
    qty: 6
  - part: scr-m5-12-shcs
    qty: 2
  - part: tnut-m5-2020
    qty: 2
---

The fasteners and quantities in the parts list come from the parts calculator and are called out inline at each step.

{% include fastener-legend.html %}

One per machine. Which Orange Pi 5 to buy, how much RAM and storage it needs, the WiFi module, the USB hub and cooling are all on the [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) page. This page is only about bolting it to the machine, and it is close to the [control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}): 6 inserts, 4 standoffs, 4 M3 screws under the Pi, a printed arm holding the 40 mm fan over it on 6 more, and 2 M5 into the frame.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/orange-pi-mount-v1-render-full-d5893e241c96.png" alt="Onshape render of the two printed parts of the Orange Pi mount: the blue plate with its rectangular cutout and corner screw holes, and the grey fan arm standing on its front edge, reaching back over the plate with the round fan opening in its top">
  <figcaption>The two printed parts: the plate the Pi stands off (blue) and the fan arm over it (grey). The Pi, the standoffs and the fan are not shown. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
</figure>

{% include step.html n="1" title="Preparation" %}

Before assembling anything, press the heat inserts into the parts that take them, while the parts are still loose. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Orange Pi extrusion mount:</strong> 6 × M3. Four on the top face, one per standoff, and two more lying on their sides in the front edge of the plate, 32 mm apart, which are what the fan arm bolts back into.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/opi-mount-inserts-fitted-w1600-6fef8b0dd716.jpg" alt="The printed Orange Pi extrusion mount lying on the bench with its six brass heat inserts fitted: four on the top face around the rectangular opening, and two in the front edge face between them, with the two M5 frame holes at the near corners left open">
    <figcaption>All 6 inserts in: four on the top face, two in the front edge for the fan arm. The two open holes at the near corners are the M5 clearance holes for the frame. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The two in the front edge go in on their sides, so press them with the plate stood on end rather than trying to reach them flat on the bench.

The Pi, the fan and the fan arm take no inserts.

The Pi's heatsink fan goes on at this stage too, while the board is still loose on the bench. Its two pins clip underneath the board, so you want to be able to reach both faces.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Orange Pi 5:</strong> the official heatsink fan sits on the SoC, the large chip in the middle of the board. Check the revision printed on the board before you start: it fits the Orange Pi 5 v1.3.2 and the 5 Plus, and the mounting holes are not in the same place on earlier revisions.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/orange-pi-5-heatsink-fan-fitted-full-6f0bb3b7ada4.jpg" alt="An Orange Pi 5 v1.3.2 seen from above with the heatsink fan already fitted over the SoC in the middle of the board, a white spring pin clipped through the board at opposite corners of the finned block, and the red and black lead running from the fan to a small white 2-pin socket silkscreened FAN, between the CAM1 connector and the USB 2.0 port">
    <figcaption>An Orange Pi 5 v1.3.2 with the fan fitted: the heatsink over the SoC, a spring pin through the board at each of two opposite corners, and the lead in the socket marked FAN. <cite>Manufacturer photo (Orange Pi), not a Basically photo; the pale highlights are theirs.</cite></figcaption>
  </figure>
</div>

Peel the film off the thermal pad that comes in the box and lay it on the SoC. Sit the heatsink squarely on top with its two tabs over the holes either side, press both spring pins down until they click, and plug the 2-pin lead into the socket marked FAN, which on a v1.3.2 board is between the CAM1 connector and the USB 2.0 port. The pins hold it on, so there are no screws here and nothing to tighten.

This is a second fan, not a replacement for the 40 mm one on the arm: the heatsink fan sits on the chip, and the arm fan blows down over the whole board from above. It fits underneath: the heatsink stands 13 mm off the board and the arm's underside passes about 38 mm above it.

{% include step.html n="2" title="Stand the Pi off the mount" %}

(Inserts already pressed in step 1.)

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Static caution: the Orange Pi is ESD-sensitive like any other bare board. Touch a grounded metal surface before handling it, and avoid doing this on carpet in dry weather.</p>
</div>

Screw the 4 M3 standoffs into the inserts. Sit the Pi on them and fasten it down with 4 {% include fastener.html size="M3" variant="socket-button" length="6" %} screws. The 10 mm standoffs are used.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The standoff's own thread strips easily.</b> They are a soft plastic, closer to a hard rubber than to metal, so the thread that gives is theirs and not the brass insert's. Start each one by hand, keep it square to the plate, and stop turning the moment it seats. A stripped standoff is scrap: fit a new one rather than trying to persuade it.</p>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/opi-mount-with-standoffs-loose-w1600-d31e70d2bea2.jpg" alt="The mount plate with its four black M3 standoffs lying loose on the bench beside it">
    <figcaption>Four standoffs, one per insert on the top face. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/opi-mount-standoffs-in-w1600-dd57fc1042ae.jpg" alt="The same plate with all four standoffs screwed into the top face inserts, standing up around the rectangular opening">
    <figcaption>Screwed in, standing off the plate. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/opi-pi-on-standoffs-w1600-b837e6e88b65.jpg" alt="The Orange Pi 5 sitting on the four standoffs over the plate's opening, ports along the far edge and the board's underside clear of the plastic">
    <figcaption>The Pi on the standoffs, its underside clear of the plate. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Fit the fan to the arm" %}

Easier with the arm still loose on the bench. The fan sits on the flat top face of the arm, over the round opening, with its label side down so it blows down through the opening onto the Pi. The four holes take 4 {% include fastener.html size="M3" variant="socket-button" length="16" %} screws, self-tapping straight into the plastic. There are no inserts in the arm.

Take the lead down through the rectangular 18 × 10 mm slot at the near end of the arm, over the upright, while the arm is still off the machine.

{% include step.html n="4" title="Bolt the fan arm to the mount" %}

Stand the arm's foot against the front edge of the mount, the arm reaching back over the Pi, and line its two holes up with the two inserts pressed into that edge in step 1. Fasten it with 2 {% include fastener.html size="M3" variant="socket-button" length="16" %} screws.

The screws pass through 12 mm of the foot before they reach the insert, so a 16 leaves about 4 mm in it. An {% include fastener.html size="M3" variant="socket-button" length="12" %} does not reach the insert at all, and an M3 × 20 bottoms out in it and jacks the arm off the plate.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/opi-mount-assembled-w1600-d65b122c4efc.jpg" alt="The finished mount on the bench: the Orange Pi standing on its standoffs over the plate, the printed fan arm bolted to the front edge and reaching back over the board, a 40 mm fan screwed to the top of the arm with its lead down through the slot">
  <figcaption>Everything on the plate: the Pi on its standoffs, the arm bolted to the front edge and the fan over the board. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="5" title="Bolt the mount to the frame" %}

The mount hangs off the 2020 frame on 2 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws into 2 {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %} in the extrusion slot. It goes on the [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}) belonging to the top interface; the [layout render]({{ '/hardware/electronics/installation/' | relative_url }}) on the installation overview shows where it sits relative to the chute stepper.

<div class="callout">
  <p><b>No problem if you forgot them.</b> The {% include fastener.html size="M5" variant="t-nut" text="T-nut" %} this build specifies is the spring-loaded roll-in kind, which drops into the slot anywhere along its length, so it can still go in now without taking the frame apart. See <a href="{{ '/hardware/helpers/t-nuts/' | relative_url }}">Fitting T-nuts</a>.</p>
</div>

<div class="img-placeholder">Image coming</div>

{% include step.html n="6" title="Plug it in" %}

The Pi is powered by its own 24 V to USB-C adapter off the PSU, not from the control board. Confirm the buck converter's output is 5V and correctly polarized before connecting it to the Pi for the first time; a wrong connection here can destroy the board. That, the USB hub and the cameras are all on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.

The fan on the arm is the **24 V** WINSINN 4010, the same fan the [control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}) takes, on an XH2.54 2-pin lead. The Pi's heatsink fan is a different, 5 V fan and plugs straight into the board's own `FAN` socket back in step 1, so there is only one lead to find a home for here.

Where that lead lands is not settled. The Orange Pi has no 24 V rail and no fan header of its own, so the fan has to come off the control board, and whether it goes on one of that board's LED ports (which is how the control board housing's own fan is wired) is still being decided.

The Orange Pi mount is now complete. Flashing and configuring the Pi is [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).
