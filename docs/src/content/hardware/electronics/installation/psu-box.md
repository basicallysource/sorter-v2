---
layout: default
title: PSU box
type: how-to
section: hardware
slug: electronics-psu-box
kicker: Electronics — PSU box
lede: The printed enclosure around the Mean Well LRS-350-24, its mains inlet, and the wiring inside it.
permalink: /hardware/electronics/installation/psu-box/
author: barthel
contributors: [spencer]
og_image: https://assets.basically.website/sorter-parts/psu-24v-350w-full-72bba2c3919b.jpg
last_verified: 2026-09-18
tools_needed: ["Hex keys, 2 mm and 2.5 mm", "Screwdriver for the supply's terminal block screws"]
parts_needed:
  - part: psu-24v-350w
    qty: 1
  - part: psu-switch-fused
    qty: 1
  - part: scr-m3-8-cs
    qty: 2
  - part: meanwell-psu-back-mount
    qty: 1
  - part: meanwell-psu-connections
    qty: 1
  - part: meanwell-psu-cap
    qty: 1
  - part: scr-m4-6-cs
    qty: 4
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Make three <a href="{{ '/hardware/helpers/psu-pigtail/' | relative_url }}">PSU output pigtails</a> before you start.</strong> Each is a panel-mount barrel jack with a fork terminal crimped onto each of its two leads, and they are commonly sold with the leads already on. That page builds them; step 1 here fits and wires them.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-built-w1600-59554dc6b189.jpg" alt="An assembled PSU output pigtail: a panel-mount barrel jack with red and black 18 AWG leads, each ending in an insulated fork terminal">
    <figcaption>One finished pigtail: the jack, its red and black leads, and a fork terminal on each. <cite>Photo: Jon.</cite></figcaption>
  </figure>
</div>

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Until this box is finished it has exposed mains wiring.</b> Observe basic electrical safety precautions: do not plug a cable into the IEC inlet until the assembly is complete, the wiring is verified and the cap is on.</p>
</div>

The connections plate is populated and wired in your hand, and goes onto the supply last. Everything in steps 1 and 2 is easier with the plate loose.

{% include step.html n="1" title="Fit and wire the three jacks" %}

Push each jack through the connections plate from behind and do its nut up on the outside. The plate has six holes; use the top three.

Then land each pigtail on the supply's terminal block, one pigtail per **+V/-V** pair: **7 with 4, 8 with 5, 9 with 6**, the red terminal on the +V screw and the black on the -V screw of the same pair. Each pigtail must keep to one pair.

The screw numbers are Mean Well's own, printed on the supply beside the block.

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/psu-box-terminal-map-full-81629ce6a8e1.png" alt="Diagram of the Mean Well LRS-350-24 seen from above, its nine-way terminal block down the left edge numbered 1 at the bottom to 9 at the top, the numbers being Mean Well's own and printed on the supply. Red leads run from screws 9, 8 and 7 and black leads from 6, 5 and 4, pairing 9 with 6, 8 with 5 and 7 with 4 into three barrel jacks labelled PJ3 to the Orange Pi buck, PJ2 to the powered USB hub, and PJ1 to the basically board. Below them the IEC C14 inlet switch module is drawn upright with its illuminated rocker, fuse drawer and C14 socket, and its three factory leads run to screws 1, 2 and 3, labelled AC/L, AC/N and earth: red to screw 1 as the live, blue to screw 2 as the neutral, and yellow to screw 3 as the earth. A warning band says not to plug a cable into the IEC inlet until the assembly is complete, the wiring is verified and the cap is on.">
  <figcaption>Every lead that lands on the block, and the screw it lands on. The mains leads at the bottom are step 2. <cite>Drawn from the Mean Well LRS-350 spec sheet, the inlet's catalog entry and the harness drawings.</cite></figcaption>
</figure>

Tug-test each terminal once it is down.

{% include step.html n="2" title="Fit and wire the mains inlet" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>No mains cable in the inlet.</b> Not for this step, not for any of the ones after it, and not until the box is closed and the wiring checked.</p>
</div>

The **IEC C14 inlet, switch + 10 A fuse** is the machine's mains entry and its on/off switch. Its three leads come already attached, so there is no AC cable to make.

Push it into the rectangular cutout from the outside so its flange sits on the outer face of the plate. Fasten it with 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, one through each flange hole. The flange is countersunk for them, so the heads finish flush. They cut their own thread in the plate, so run them in until the flange is tight and stop.

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/psu-box-inlet-mounting-full-e34ceb6bf26b.png" alt="The PSU connections plate drawn twice side by side at the same scale. On the left it is bare: a tall rectangular cutout near the top, a small screw hole either side of it, and six round holes below in two columns of three. On the right the IEC C14 inlet switch module sits in the cutout, its flange covering the hole with its rocker, fuse drawer and C14 socket showing. A warning says not to plug a cable into the IEC inlet until the assembly is complete, the wiring is verified and the cap is on.">
  <figcaption>The connections plate from outside, and the same plate with the inlet in it. <cite>Plate drawn from its STL and the module from its published flange size, both at the same scale, not from a build.</cite></figcaption>
</figure>

Then land its three leads on screws 1, 2 and 3: **red on 1** (AC/L), **blue on 2** (AC/N), **yellow on 3** (earth). Those three are fixed, not a choice. The drawing in step 1 has them too.

{% include step.html n="3" title="Fasten the plates to the supply" %}

Fasten the PSU connections plate and the PSU back mount to the supply's own case with the 4 {% include fastener.html size="M4" variant="countersunk" length="6" %} screws, two into each plate. The supply has four M4 threads in its case, two at each end.

<ol class="numbered-steps">
  <li><b>PSU connections plate</b>, on the end the terminal block is on. This is the plate you have just wired.</li>
  <li><b>PSU back mount</b>, on the opposite end, which is the end that bolts to the frame. Its cutout leaves the supply's own fan clear.</li>
</ol>

**The PSU box cap takes none of the four**; it goes on in step 4.

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/psu-box-case-screws-full-8fe11b7f0d7b.png" alt="Photograph of the Mean Well LRS-350-24 seen from its back, with four of its threaded holes ringed. The two nearer the terminal block are labelled as taking the PSU connections plate, the two at the opposite end as taking the PSU back mount, each with two M4 by 6 mm countersunk screws. A note says the hex-stamped screws beside them are the case's own.">
  <figcaption>The four M4 threads on the back of the supply, and which plate each pair takes. <cite>Manufacturer photo, marked up.</cite></figcaption>
</figure>

Route every lead through the connections plate so nothing can shift and touch the mains terminals once the box is closed.

{% include step.html n="4" title="Close the box" %}

Fit the cap. It takes no screws and nothing else holds it: it sits on top, resting on the connections plate at one end and against the supply at the other. The box is closed before the machine sees mains.

<div class="img-placeholder">Image coming</div>

## The finished result

The supply with both printed plates bolted to its back, the mains inlet in the connections plate, the three jacks beside it and every lead landed on the terminal block. Shown with the cap off, because with it on there is nothing to see.

<div class="img-placeholder">Image coming: the supply on the bench, both plates on, the inlet and the three jacks in the connections plate, cap off</div>

**Bolting it to the frame is on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }})**. Everything that plugs into it is on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.
