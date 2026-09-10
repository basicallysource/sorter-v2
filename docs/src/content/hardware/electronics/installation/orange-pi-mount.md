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
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=orange-pi-mount), not
  from an actual build. The parts and quantities are real, but no step here has been checked
  against a machine. The steps below are placeholders with the gaps marked.
parts_needed:
  - part: sbc-orange-pi-5
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
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/opi-mount-six-inserts-full-09f831150f82.png" alt="The Orange Pi extrusion mount lying on its long edge, with six M3 insert holes circled in red: four on the top face near the corners of the frame, and two in the front edge face between them, each showing a real shadowed hole">
    <figcaption>All 6 insert holes, ringed: four on the top face at the corners of the frame, two in the front edge for the fan arm. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

The two in the front edge go in on their sides, so press them with the plate stood on end rather than trying to reach them flat on the bench.

The Pi, the fan and the fan arm take no inserts.

{% include step.html n="2" title="Stand the Pi off the mount" %}

<figure class="figure-float-right">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/opi-landscape-standoffs-full-cefb56a912b0.png" alt="The Orange Pi extrusion mount lying on its long edge with 4 standoffs mounted in the corner insert holes and a screw head in blue on top of each, shown as plain placeholders since neither part is modelled in the catalog">
  <figcaption>The 4 standoffs and their retention screws (blue), drawn as parametric placeholders. <cite>Render: Balloon.</cite></figcaption>
</figure>

(Inserts already pressed in step 1.)

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Static caution: the Orange Pi is ESD-sensitive like any other bare board. Touch a grounded metal surface before handling it, and avoid doing this on carpet in dry weather.</p>
</div>

Screw the 4 M3 standoffs into the inserts. Sit the Pi on them and fasten it down with 4 {% include fastener.html size="M3" variant="socket-button" length="6" %} screws. The 10 mm standoffs are used.

<div class="clear-float"></div>

{% include step.html n="3" title="Fit the fan to the arm" %}

<figure class="figure-float-right">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/opi-fan-arm-fan-holes-full-7b678b45ebd7.png" alt="The 40 mm fan arm on its own, standing on its foot, with the four fan screw holes around the round opening in its top plate circled in red">
  <figcaption>The 4 fan holes in the top of the arm, ringed, on the standard 32 × 32 mm pattern around the opening. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

Easier with the arm still loose on the bench. The fan sits on the flat top face of the arm, over the round opening, with its label side down so it blows down through the opening onto the Pi. The four holes take 4 {% include fastener.html size="M3" variant="socket-button" length="16" %} screws, self-tapping straight into the plastic. There are no inserts in the arm.

Take the lead down through the rectangular 18 × 10 mm slot at the near end of the arm, over the upright, while the arm is still off the machine.

<div class="clear-float"></div>

{% include step.html n="4" title="Bolt the fan arm to the mount" %}

<figure class="figure-float-right">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/opi-fan-arm-on-mount-full-6b0470d81e3f.png" alt="The fan arm in blue standing on the front edge of the grey Orange Pi extrusion mount, its arm reaching back over the plate, with the two screw holes through its foot circled in red">
  <figcaption>The arm (blue) on the mount, with the 2 screws through its foot ringed. The arm reaches back over the Pi. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

Stand the arm's foot against the front edge of the mount, the arm reaching back over the Pi, and line its two holes up with the two inserts pressed into that edge in step 1. Fasten it with 2 {% include fastener.html size="M3" variant="socket-button" length="16" %} screws.

The screws pass through 12 mm of the foot before they reach the insert, so a 16 leaves about 4 mm in it. An {% include fastener.html size="M3" variant="socket-button" length="12" %} does not reach the insert at all, and an M3 × 20 bottoms out in it and jacks the arm off the plate.

<div class="clear-float"></div>

{% include step.html n="5" title="Bolt the mount to the frame" %}

The mount hangs off the 2020 frame on 2 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws into 2 {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %} in the extrusion slot. It goes on the [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}) belonging to the top interface; the [layout render]({{ '/hardware/electronics/installation/' | relative_url }}) on the installation overview shows where it sits relative to the chute stepper.

<div class="callout">
  <p><b>No problem if you forgot them.</b> The {% include fastener.html size="M5" variant="t-nut" text="T-nut" %} this build specifies is the spring-loaded roll-in kind, which drops into the slot anywhere along its length, so it can still go in now without taking the frame apart. See <a href="{{ '/hardware/helpers/t-nuts/' | relative_url }}">Fitting T-nuts</a>.</p>
</div>

<div class="img-placeholder">Image coming</div>

{% include step.html n="6" title="Plug it in" %}

The Pi is powered by its own 24 V to USB-C adapter off the PSU, not from the control board. Confirm the buck converter's output is 5V and correctly polarized before connecting it to the Pi for the first time; a wrong connection here can destroy the board. That, the USB hub and the cameras are all on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.

The parts list carries the 24 V WINSINN 4010, the same fan as the [control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}) uses, on an XH2.54 2-pin lead. A 24 V fan here has to reach one of that board's LED ports with its bypass jumper bridged, because the Orange Pi has no 24 V rail and no fan header of its own. The Pi's own manual instead has you run a **5 V** fan off two pins of its 26-pin header, which needs no board port at all, and the same 40 mm frame is sold in both voltages. Which of the two this fan is, and where its lead lands, is not settled.

The Orange Pi mount is now complete. Flashing and configuring the Pi is [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).
