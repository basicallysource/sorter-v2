---
layout: default
title: Orange Pi mount
type: how-to
section: hardware
slug: electronics-orange-pi-mount
kicker: Electronics — Orange Pi mount
lede: The Orange Pi 5 standing off its mount, with the 40 mm fan on its arm above it.
permalink: /hardware/electronics/installation/orange-pi-mount/
author: barthel
contributors: [spencer]
og_image: https://assets.basically.website/sorter-docs/opi-mount-assembled-w1600-d65b122c4efc.jpg
last_verified: 2026-09-17
tools_needed: ["Hex key, 2 mm for a button head or 2.5 mm for a socket head", "Soldering iron or heat-set insert press"]
parts_needed:
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
---

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

One per machine. Which Orange Pi 5 to buy, how much RAM and storage it needs, the WiFi module, the USB hub and cooling are all on the [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) page. This page is the build on the bench, and it is close to the [control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}): 6 inserts, 4 standoffs, 4 M3 screws under the Pi, and a printed arm holding the 40 mm fan over it on 6 more.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong><a href="{{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}">Prepare the Orange Pi</a> before you start.</strong> The heatsink fan, the WiFi module and the first boot that sets the network all need both faces of the board reachable, and this mount sits under it. Not covered here.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/wifi-module-bench-first-boot-w1600-c538b35694b3.jpg" alt="A prepared Orange Pi 5 on a desk, powered with its red LED lit, a USB-C lead in the power socket and two antenna leads running off the WiFi module fitted underneath the board">
    <figcaption>A prepared Orange Pi, still on the bench. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

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

The Pi's heatsink fan fits under the arm: it stands 13 mm off the board and the arm's underside passes about 38 mm above it.

{% include step.html n="2" title="Stand the Pi off the mount" %}

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

The fan is the **24 V** WINSINN 4010 on an XH2.54 2-pin lead, the same fan the [control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}) takes. It is not the Pi's own heatsink fan, which is 5 V and went into the board's `FAN` socket back in step 1.

Take the lead down through the rectangular 18 × 10 mm slot at the near end of the arm, over the upright, while the arm is still off the machine.

Leave the lead loose. It has nowhere to plug into yet, and whether this fan is needed at all is still being decided.

{% include step.html n="4" title="Bolt the fan arm to the mount" %}

Stand the arm's foot against the front edge of the mount, the arm reaching back over the Pi, and line its two holes up with the two inserts pressed into that edge in step 1. Fasten it with 2 {% include fastener.html size="M3" variant="socket-button" length="16" %} screws.

The screws pass through 12 mm of the foot before they reach the insert, so a 16 leaves about 4 mm in it. An {% include fastener.html size="M3" variant="socket-button" length="12" %} does not reach the insert at all, and an M3 × 20 bottoms out in it and jacks the arm off the plate.

## The finished result

Everything on the plate: the Pi on its standoffs over the opening, the arm bolted to the front edge and reaching back over it, and the fan on top of the arm with its lead down through the slot.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/opi-mount-assembled-w1600-d65b122c4efc.jpg" alt="The finished mount on the bench: the Orange Pi standing on its standoffs over the plate, the printed fan arm bolted to the front edge and reaching back over the board, a 40 mm fan screwed to the top of the arm with its lead down through the slot">
  <figcaption>The assembled mount, off the machine. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

**Bolting it to the frame is on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }})**, with the other two enclosures. Nothing plugs into the Pi there either: its power comes from a 24 V to 5 V buck converter off the PSU rather than from the control board, and that, the USB hub, the cameras and the arm fan's lead are all on [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), which is the next page.
