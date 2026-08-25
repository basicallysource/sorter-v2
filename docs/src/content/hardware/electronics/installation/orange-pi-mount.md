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
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/opi-ring-near-full-f66229fc5a95.png" alt="The Orange Pi extrusion mount at a slight angle off vertical, with two of the four M3 standoff insert holes circled in red, each showing a real shadowed hole rather than a flat mark">
    <figcaption>Two of the 4 insert holes, ringed, angled enough for the shadow to actually show a hole. The other 2 mirror these on the far side of the same rail — a straight top-down shot marks the spot but flattens out the shadow that makes it read as a hole at all.</figcaption>
  </figure>
</div>

The Pi itself takes no inserts, and neither does anything else on this page.

{% include step.html n="2" title="Stand the Pi off the bracket" %}

**Heat inserts first:** the bracket takes 4 × M3 inserts, one per standoff. Press them in before assembling.

Screw the 4 M3 × 10 mm standoffs into the inserts. Sit the Pi on them and fasten it down with 4 {% include fastener.html size="M3" variant="socket-button" length="6" %} screws.

Not a direct measurement — neither the standoff nor the Orange Pi 5 has a 3D model in the catalog, so there's no bore depth or board thickness to check it against — but a reasonable call rather than a placeholder: a PCB mounting hole is a plain clearance hole, never countersunk (there's no chamfer machined into the board to seat a countersunk head against), and M3×6 is the standard length for a board-to-standoff screw. It's also what the basically Embedded Control Board uses for the same kind of joint once that one was actually measured, the same size and head type, not just the same reasoning. The 10 mm standoff length is the BOM sheet's number and has not been confirmed against the bracket either.

Whether the Pi's heatsink or fan clears the standoffs is not recorded either.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/opi-screws-top2-full-9743aaed8c16.png" alt="The Orange Pi extrusion mount seen from directly above with 4 standoffs mounted in the insert holes on the middle rail and a screw head in blue on top of each, shown as plain placeholders since neither part is modelled in the catalog">
  <figcaption>The 4 standoffs mounted, with a board-retention screw on top of each (blue), drawn at the M3 × 6 mm this joint is expected to use. Both are parametric placeholders, not the real parts' geometry — there's no standoff or screw STL in the catalog. The Pi itself isn't shown for the same reason.</figcaption>
</figure>

{% include step.html n="3" title="Bolt the mount to the frame" %}

The mount hangs off the 2020 frame on 2 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws. The bracket's own holes are 5.5 mm plain clearance, no countersink, through an 8 mm-thick section, measured off the STL; 12 mm is a stack-up estimate (8 mm of bracket plus a typical M5 roll-in T-nut's engagement) rather than a confirmed length, since the T-nut itself isn't dimensioned in the catalog. The [PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }}) and the [control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}) use the same M5 screw for the same job, but their own brackets weren't remeasured here.

Which extrusion it goes on, and in which orientation, is not written down. The top-down layout photo on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }}) is the only record.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Plug it in" %}

The Pi is powered by its own 24 V to USB-C adapter off the PSU, not from the control board. That, the USB hub and the cameras are all on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.

Fan power is open item 1 on that page and is still unresolved, so there is nothing to wire for cooling yet.

The Orange Pi mount is now complete. Flashing and configuring the Pi is [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).
