---
layout: default
title: Orange Pi mount
type: how-to
section: hardware
slug: electronics-orange-pi-mount
kicker: Electronics — Orange Pi mount
lede: The Orange Pi 5 standing off its mount on four standoffs, cooled by the heatsink fan on its own SoC.
permalink: /hardware/electronics/installation/orange-pi-mount/
author: barthel
contributors: [spencer]
og_image: https://assets.basically.website/sorter-docs/opi-pi-on-standoffs-w1600-b837e6e88b65.jpg
last_verified: 2026-09-17
tools_needed: ["Hex key, 2 mm for a button head or 2.5 mm for a socket head", "Soldering iron or heat-set insert press"]
parts_needed:
  - part: orange-pi-extrusion-mount
    qty: 1
  - part: standoff-m3-10mm
    qty: 4
  - part: hsi-m3
    qty: 4
  - part: scr-m3-6-bhcs
    qty: 4
---

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

One per machine. Which Orange Pi 5 to buy, how much RAM and storage it needs, the WiFi module, the USB hub and cooling are all on the [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) page. This page is the build on the bench, and it is a short one: 4 inserts, 4 standoffs, 4 M3 screws, and the Pi is on.

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
    <p><strong>Orange Pi extrusion mount:</strong> 4 × M3, on the top face, one per standoff. The plate also has two pockets lying on their sides in its front edge: leave those empty, they held the 40 mm fan arm the machine no longer uses.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/opi-mount-inserts-fitted-w1600-6fef8b0dd716.jpg" alt="The printed Orange Pi extrusion mount lying on the bench with its six brass heat inserts fitted: four on the top face around the rectangular opening, and two in the front edge face between them, with the two M5 frame holes at the near corners left open">
    <figcaption>The four top-face inserts are the ones this build needs. This plate was photographed with the two front-edge inserts in as well, from when the fan arm was still part of the build. The two open holes at the near corners are the M5 clearance holes for the frame. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The Pi itself takes no inserts. Nothing sits above it on this mount, so its heatsink fan has all the room it needs.

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
</div>

## The finished result

Everything on the plate: the Pi standing on its four standoffs over the opening, its underside clear of the plastic, and nothing above it.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/opi-pi-on-standoffs-w1600-b837e6e88b65.jpg" alt="The Orange Pi 5 sitting on the four standoffs over the plate's opening, ports along the far edge and the board's underside clear of the plastic">
  <figcaption>The assembled mount, off the machine. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

**Bolting it to the frame is on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }})**, with the other two enclosures. Nothing plugs into the Pi there either: its power comes from a 24 V to 5 V buck converter off the PSU rather than from the control board, and that, the USB hub and the cameras are all on [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), which is the next page.
