---
layout: default
title: PSU box
type: how-to
section: hardware
slug: electronics-psu-box
kicker: Electronics — PSU box
lede: The printed enclosure around the Mean Well LRS-350-24, and how it mounts to the frame.
permalink: /hardware/electronics/installation/psu-box/
author: barthel
contributors: [spencer]
warning: >-
  **Skeleton page.** The parts and quantities are real, from the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=meanwell-psu-box). The
  assembly order is not recorded anywhere and no step here has been checked against a machine,
  so the steps below are placeholders with the gaps marked. Correct them as you build.
parts_needed:
  - part: psu-24v-350w
    qty: 1
  - part: meanwell-psu-back-mount
    qty: 1
  - part: meanwell-psu-connections
    qty: 1
  - part: meanwell-psu-cap
    qty: 1
  - part: scr-m4-6-cs
    qty: 4
  - part: scr-m5-shcs-tbd
    qty: 2
---

The fasteners and quantities in the parts list come from the parts calculator and are called out inline at each step.

{% include fastener-legend.html %}

Several steps below refer to the supply's terminal block by screw number. Mean Well numbers them itself, and this is the assignment:

<dl class="spec-list">
  <dt>1, 2, 3</dt><dd>AC/L, AC/N, FG (earth)</dd>
  <dt>4, 5, 6</dt><dd>DC output -V</dd>
  <dt>7, 8, 9</dt><dd>DC output +V</dd>
</dl>

One DC output pigtail per +V/-V pair: 7 with 4, 8 with 5, 9 with 6. The full spec, the terminal sizes and the pigtail build are on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) and [make your own PSU pigtail]({{ '/hardware/electronics/psu-pigtail/' | relative_url }}) pages.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Screws 1, 2 and 3 are live mains.</b> They are fed by the fused IEC inlet switch's own pre-terminated leads, so there is no AC cable to make, but the cap goes on before the machine is plugged in.</p>
</div>

{% include step.html n="1" title="Preparation" %}

Print the three enclosure parts: the PSU back mount, the PSU connections plate and the PSU box cap. All three are one per machine and print in the frame colour. The STL and the print settings for each are on the [parts calculator](https://parts-calculator.basically.website/assembly?focus=meanwell-psu-box).

**No heat inserts:** nothing in this box takes one. The printed parts fasten into the supply's own case threads, which are M4, so there is nothing to press in before assembling.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Fit the printed parts to the supply" %}

Fasten the PSU back mount, the PSU connections plate and the PSU box cap to the supply's case with 4 {% include fastener.html size="M4" variant="countersunk" length="6" %} screws.

Which part takes which of the four screws, and the order they go on in, is not recorded: <span class="fastener-todo">assembly order not recorded</span>. It matters, because the connections plate is the end the cables pass through and the terminal block has to still be reachable.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Wire the terminal block" %}

Land the fused IEC inlet switch's leads on screws 1, 2 and 3, and the three DC output pigtails on the +V/-V pairs above. Route them out through the connections plate.

Whether this happens before or after the plates go on is the open question in step 2.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Close the box" %}

Fit the cap. The box is closed before the machine sees mains.

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Bolt the box to the frame" %}

The box hangs off the 2020 frame on 2 <span class="fastener-todo">M5, length not recorded</span> screws, the same as the [control board mount]({{ '/hardware/electronics/installation/control-board-mount/' | relative_url }}) and the [Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}).

Which extrusion it goes on, and in which orientation, is not written down. The top-down layout photo on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }}) is the only record.

<div class="img-placeholder">Image coming</div>

The PSU box is now complete. Everything that plugs into it is on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.
