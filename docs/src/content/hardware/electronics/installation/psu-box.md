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
  **Skeleton page.** The parts are recorded in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=meanwell-psu-box); the
  assembly order is not recorded anywhere, so this page lists what the box is made of and
  marks what is missing. No step here has been checked against a machine.
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

The supply is a **Mean Well LRS-350-24**: 24 V, 14.6 A, 350 W, single output. Three printed parts wrap it, and the whole box bolts to the frame. Everything downstream of it, including the three DC output pigtails, is on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.

{% include fastener-legend.html %}

- **One per machine.**
- The three printed parts fasten to the supply's **own case threads**, which are M4. That is what the 4 {% include fastener.html size="M4" variant="countersunk" length="6" %} screws are for.
- The box takes no heat inserts.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Mains wiring.</b> Screws 1, 2 and 3 on the supply's terminal block are live AC. They are fed by the fused IEC inlet switch's own pre-terminated leads, so there is no AC cable to make, but the box has to be closed before the machine is plugged in.</p>
</div>

{% include step.html n="1" title="Print the three parts" %}

Back mount, connections plate, and cap. All three print in the frame colour. Print settings and the STL for each are on the [parts calculator](https://parts-calculator.basically.website/assembly?focus=meanwell-psu-box).

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Wire the terminal block before closing the box" %}

The terminal block is 9 screws and Mean Well numbers them: **1** AC/L, **2** AC/N, **3** FG, **4-6** DC output -V, **7-9** DC output +V. One DC output pigtail per +V/-V pair, 7 with 4, 8 with 5, 9 with 6. Full spec, terminal sizes and the pigtail build are on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) and [PSU pigtail]({{ '/hardware/electronics/psu-pigtail/' | relative_url }}) pages.

The order the plates go on relative to the wiring is not recorded. It matters, because the connections plate is what the cables pass through.

{% include step.html n="3" title="Assemble the box" %}

Fit the back mount, the connections plate and the cap to the supply's case with 4 {% include fastener.html size="M4" variant="countersunk" length="6" %} screws.

Which part takes which screws, and in what order, is not recorded: <span class="fastener-todo">assembly order not recorded</span>.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Bolt the box to the frame" %}

The box hangs off the 2020 frame on 2 <span class="fastener-todo">M5, length not recorded</span> screws, the same as the other two electronics mounts.

Which extrusion it goes on, and in which orientation, is not written down. The top-down layout photo on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }}) is the only record.

<div class="img-placeholder">Image coming</div>
