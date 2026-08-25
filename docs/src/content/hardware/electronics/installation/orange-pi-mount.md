---
layout: default
title: Orange Pi mount
type: how-to
section: hardware
slug: electronics-orange-pi-mount
kicker: Electronics — Orange Pi mount
lede: The Orange Pi 5 standing off its bracket, and how the bracket mounts to the frame.
permalink: /hardware/electronics/installation/orange-pi-mount/
author: barthel
contributors: [spencer]
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
  - part: standoff-m3-10mm
    qty: 4
  - part: hsi-m3
    qty: 4
  - part: scr-m3-6-bhcs
    qty: 4
  - part: scr-m5-12-shcs
    qty: 2
---

The fasteners and quantities in the parts list come from the parts calculator and are called out inline at each step.

{% include fastener-legend.html %}

One per machine. Which Orange Pi 5 to buy, how much RAM and storage it needs, the WiFi module, the USB hub and cooling are all on the [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) page. This page is only about bolting it to the machine, and it is the same shape as the [control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}): 4 inserts, 4 standoffs, 4 M3 screws, 2 M5 into the frame.

{% include step.html n="1" title="Preparation" %}

Before assembling anything, press the heat inserts into the parts that take them, while the parts are still loose. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Orange Pi extrusion mount:</strong> 4 × M3, one per standoff</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/opi-landscape-ringed-full-aa8aaac704ff.png" alt="The Orange Pi extrusion mount lying on its long edge, with all four M3 standoff insert holes circled in red near the four corners of the frame, each showing a real shadowed hole">
    <figcaption>The 4 insert holes, ringed, near the four corners of the frame.</figcaption>
  </figure>
</div>

The Pi itself takes no inserts, and neither does anything else on this page.

{% include step.html n="2" title="Stand the Pi off the bracket" %}

<figure class="figure-float-right">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/opi-landscape-standoffs-full-cefb56a912b0.png" alt="The Orange Pi extrusion mount lying on its long edge with 4 standoffs mounted in the corner insert holes and a screw head in blue on top of each, shown as plain placeholders since neither part is modelled in the catalog">
  <figcaption>The 4 standoffs and their retention screws (blue), drawn as parametric placeholders.</figcaption>
</figure>

**Heat inserts first:** the bracket takes 4 × M3 inserts, one per standoff. Press them in before assembling.

Screw the 4 M3 standoffs into the inserts. Sit the Pi on them and fasten it down with 4 {% include fastener.html size="M3" variant="socket-button" length="6" %} screws. The 10 mm standoffs are used.

<div class="clear-float"></div>

{% include step.html n="3" title="Bolt the mount to the frame" %}

The mount hangs off the 2020 frame on 2 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws.

Which extrusion it goes on, and in which orientation, is not written down. The top-down layout photo on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }}) is the only record.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Plug it in" %}

The Pi is powered by its own 24 V to USB-C adapter off the PSU, not from the control board. That, the USB hub and the cameras are all on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.

The Orange Pi mount is now complete. Flashing and configuring the Pi is [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).
