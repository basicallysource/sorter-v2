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
  **Skeleton page.** The printed bracket this board stands off is **not in the parts registry
  yet**, so the central part of this page is missing and cannot be written from the
  [parts calculator](https://parts-calculator.basically.website/assembly?focus=ctrl-board-mount).
  What is recorded is listed below; everything else is marked in place.
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

One per machine. The board is the machine's motion and IO controller: the Pico, the stepper drivers, the servo outputs and the LED outputs are all on it. What plugs into which connector is on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) and [stepper connectors]({{ '/hardware/electronics/steppers/' | relative_url }}) pages.

{% include fastener-legend.html %}

- **One per machine**, board revision **v1.3**.
- The board does not touch the bracket: it stands on 4 M3 × 10 mm standoffs.
- The 4 M3 heat inserts go in the bracket, not in the board.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The bracket is missing from the parts registry.</b> The calculator records the board, the standoffs, the inserts and the screws, but not the printed part they all attach to. There is no STL and no render for it. Until somebody adds it, steps 2 and 3 below cannot be followed as written.</p>
</div>

{% include step.html n="1" title="Fit the Pico first" %}

The board takes a Raspberry Pi Pico on 2.54 mm headers, and the headers have to be soldered on before the Pico can seat. Do it before the board goes on the mount, while both sides are still reachable. See [Pico headers]({{ '/hardware/electronics/installation/pico-headers/' | relative_url }}).

{% include step.html n="2" title="Preparation: heat inserts in the bracket" %}

The bracket takes 4 {% include fastener.html size="M3" variant="heat-insert" %}, one per standoff. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

Which part these go into is the open question above.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Stand the board off the bracket" %}

Screw the 4 standoffs into the inserts, sit the board on them, and fasten it down with 4 M3 screws.

Neither the head type nor the length of those screws is recorded: <span class="fastener-todo">M3, type and length not recorded</span>. The standoff length is the BOM sheet's 10 mm and has not been confirmed against the board mount either.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Bolt the mount to the frame" %}

2 <span class="fastener-todo">M5, length not recorded</span> screws into the 2020 frame, the same as the PSU box and the Orange Pi mount.

Which extrusion and which orientation are not written down. See the layout photo on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }}).

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Cooling" %}

The board ends up in an enclosure with no airflow other than a fan. Fans are wanted but they are not on the 24 V bus, so they run off the board or the Pi and the voltage follows the available pins. This is open item 1 on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page and there is nothing to install yet.
