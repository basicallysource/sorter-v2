---
layout: default
title: Control board mount
type: how-to
section: hardware
slug: electronics-control-board-mount
kicker: Electronics — Control board mount
lede: The basically Embedded Control Board v1.3 standing off its bracket, and how the bracket mounts to the frame.
permalink: /hardware/electronics/installation/control-board-mount/
author: barthel
contributors: [spencer]
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=ctrl-board-mount), not
  from an actual build. The parts and quantities are real, but the printed bracket the board
  stands off is **not in the parts registry**, and no step here has been checked against a
  machine. The steps below are placeholders with the gaps marked.
parts_needed:
  - part: ctrl-board-basically
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

The fasteners and quantities in the parts list come from the parts calculator and are called out inline at each step.

{% include fastener-legend.html %}

One board per machine, revision v1.3. It is the machine's motion and IO controller: the Pico, the stepper drivers, the servo outputs and the LED outputs are all on it. What plugs into which connector is on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) and [stepper connectors]({{ '/hardware/electronics/steppers/' | relative_url }}) pages.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The bracket is missing from the parts registry.</b> The calculator records the board, the standoffs, the inserts and the screws, but not the printed part they all attach to. There is no STL and no render for it, so steps 1 and 3 below cannot be followed as written until somebody adds it.</p>
</div>

{% include step.html n="1" title="Preparation" %}

Before assembling anything, press the heat inserts into the parts that take them, while the parts are still loose. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Control board bracket:</strong> 4 × M3, one per standoff</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

The board itself takes no inserts, and neither does anything else on this page.

{% include step.html n="2" title="Fit the Pico" %}

The board carries a Raspberry Pi Pico on 2.54 mm headers, and the headers have to be soldered on before the Pico can seat. Do it now, while both sides of the board are still reachable. See [Pico headers]({{ '/hardware/electronics/installation/pico-headers/' | relative_url }}).

{% include step.html n="3" title="Stand the board off the bracket" %}

**Heat inserts first:** the bracket takes 4 × M3 inserts, one per standoff. Press them in before assembling.

Screw the 4 M3 × 10 mm standoffs into the inserts. Sit the board on them and fasten it down with 4 M3 screws.

Neither the head type nor the length of those screws is recorded: <span class="fastener-todo">M3, type and length not recorded</span>. The 10 mm standoff length is the BOM sheet's number and has not been confirmed against the bracket either.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Bolt the mount to the frame" %}

The mount hangs off the 2020 frame on 2 <span class="fastener-todo">M5, length not recorded</span> screws, the same as the [PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }}) and the [Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}).

Which extrusion it goes on, and in which orientation, is not written down. The top-down layout photo on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }}) is the only record.

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Cooling" %}

The board ends up in an enclosure with no airflow other than a fan. Fans are wanted, but they are not on the 24 V bus, so they run off the board or the Pi and the voltage follows the available pins. This is open item 1 on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page and there is nothing to install yet.

The control board mount is now complete. Everything that plugs into the board is on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.
