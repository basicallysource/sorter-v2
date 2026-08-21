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
  **Skeleton page.** The printed bracket the Pi stands off is **not in the parts registry
  yet**, so the central part of this page is missing and cannot be written from the
  [parts calculator](https://parts-calculator.basically.website/assembly?focus=orange-pi-mount).
  What is recorded is listed below; everything else is marked in place.
parts_needed:
  - part: sbc-orange-pi-5
    qty: 1
  - part: standoff-m3-10mm
    qty: 4
  - part: hsi-m3
    qty: 4
  - part: scr-m3-tbd
    qty: 4
  - part: scr-m5-shcs-tbd
    qty: 2
---

One per machine. Which Orange Pi 5 to buy, how much RAM and storage it needs, the WiFi module, the USB hub and cooling are all on the [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) page. This page is only about bolting it to the machine.

{% include fastener-legend.html %}

- **One per machine.**
- The mount is the same shape as the [control board mount]({{ '/hardware/electronics/installation/control-board-mount/' | relative_url }}): 4 standoffs, 4 inserts, 4 M3 screws, 2 M5 into the frame.
- The Pi is powered by its own 24 V to USB-C adapter off the PSU, not from the control board.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The bracket is missing from the parts registry.</b> The calculator records the Pi, the standoffs, the inserts and the screws, but not the printed part they all attach to. There is no STL and no render for it. Until somebody adds it, steps 1 and 2 below cannot be followed as written.</p>
</div>

{% include step.html n="1" title="Preparation: heat inserts in the bracket" %}

The bracket takes 4 {% include fastener.html size="M3" variant="heat-insert" %}, one per standoff. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Stand the Pi off the bracket" %}

Screw the 4 standoffs into the inserts, sit the Pi on them, and fasten it down with 4 M3 screws.

Neither the head type nor the length of those screws is recorded: <span class="fastener-todo">M3, type and length not recorded</span>. The standoff length is the BOM sheet's 10 mm and has not been confirmed against the board mount either.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Bolt the mount to the frame" %}

2 <span class="fastener-todo">M5, length not recorded</span> screws into the 2020 frame, the same as the PSU box and the control board mount.

Which extrusion and which orientation are not written down. See the layout photo on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }}).

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Plug it in" %}

Power, the USB hub and the cameras are all on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page. Flashing and configuring the Pi is [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).

Whether the Pi's heatsink or fan fits with the mount in place, and where the fan is fed from, is not recorded. Fan power is open item 1 on the wire harness page.
