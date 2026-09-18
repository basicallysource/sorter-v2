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
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=meanwell-psu-box), not
  from an actual build. The parts and quantities are real. The assembly order is not recorded
  anywhere and no step here has been checked against a machine, so the steps below are
  placeholders with the gaps marked. Correct them as you build.
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
  - part: scr-m5-12-shcs
    qty: 2
  - part: tnut-m5-2020
    qty: 2
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Make three <a href="{{ '/hardware/helpers/psu-pigtail/' | relative_url }}">PSU output pigtails</a> before you start.</strong> One per 24V load. Each is a panel-mount barrel jack with a fork terminal crimped onto each of its two leads, and they are commonly sold with the leads already on. That page builds them and lists the jack and the terminals; step 4 here lands them on the supply and mounts them in the box.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-built-w1600-59554dc6b189.jpg" alt="An assembled PSU output pigtail: a panel-mount barrel jack with red and black 18 AWG leads, each ending in an insulated fork terminal">
    <figcaption>One finished pigtail: the jack, its red and black leads, and a fork terminal on each. <cite>Photo: Jon.</cite></figcaption>
  </figure>
</div>

The fasteners and quantities in the parts list come from the parts calculator and are called out inline at each step.

{% include fastener-legend.html %}

Several steps below refer to the supply's terminal block by screw number. Mean Well numbers them itself, and this is the assignment:

<dl class="spec-list">
  <dt>1, 2, 3</dt><dd>AC/L, AC/N, FG (earth)</dd>
  <dt>4, 5, 6</dt><dd>DC output -V</dd>
  <dt>7, 8, 9</dt><dd>DC output +V</dd>
</dl>

One DC output pigtail per +V/-V pair: 7 with 4, 8 with 5, 9 with 6. The full spec and the terminal sizes are on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page, and [make your own PSU output pigtail]({{ '/hardware/helpers/psu-pigtail/' | relative_url }}) builds the cables.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Until this box is finished it has exposed mains wiring.</b> Observe basic electrical safety precautions: do not plug a cable into the IEC inlet until the assembly is complete, the wiring is verified and the cap is on.</p>
  <p>Screws 1, 2 and 3 are the mains ones. They are fed by the inlet's own attached leads, so there is no AC cable to make.</p>
</div>

{% include step.html n="1" title="Preparation" %}

Print the three enclosure parts: the PSU back mount, the PSU connections plate and the PSU box cap. All three are one per machine and print in the frame colour. The STL and the print settings for each are on the [parts calculator](https://parts-calculator.basically.website/assembly?focus=meanwell-psu-box).

**No heat inserts:** nothing in this box takes one. The printed parts fasten into the supply's own case threads, which are M4, so there is nothing to press in before assembling.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Fit the printed parts to the supply" %}

Fasten the PSU back mount and the PSU connections plate to the supply's case with the 4 {% include fastener.html size="M4" variant="countersunk" length="6" %} screws, before wiring: the connections plate's cable routing needs to be in place first.

Which part takes which screw isn't fully recorded, but the parts' own STLs answer most of it: the back mount has one clearance hole into the case (at the end away from the terminal block, the same end that bolts to the frame in step 6), and the connections plate has two, spread along the case nearer the terminal-block end. That's three of the four screws. The PSU box cap's STL has no case-screw holes at all, so it isn't fastened here despite this step covering all three parts in the parts list; see step 5. <span class="fastener-todo">Read from the STLs, not confirmed against a built box — worth checking against a real assembly, and the fourth screw's hole isn't accounted for either way.</span>

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Fit the mains inlet" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>No mains cable in the inlet.</b> Not for this step, not for the next one, and not until the box is closed and the wiring checked.</p>
</div>

The **IEC C14 inlet, switch + 10 A fuse** is the machine's mains entry and its on/off switch, and it goes in the rectangular cutout in the connections plate. Its three 18 AWG leads come already attached — red, blue and yellow, 27 cm each, a push-on spade at the module end and a fork terminal at the other — so there is no AC cable to make. This step mounts the module; step 4 lands those leads on the terminal block.

Push it into the cutout from the outside so its flange sits on the outer face of the plate. Fasten it with 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, one through each flange hole. The flange is countersunk for them, so the heads finish flush. They cut their own thread in the plate, so run them in until the flange is tight and stop. <span class="fastener-todo">Read off the connections plate's STL, not confirmed against a built box.</span>

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/psu-box-inlet-mounting-full-e34ceb6bf26b.png" alt="The PSU connections plate drawn twice side by side at the same scale. On the left it is bare: a tall rectangular cutout near the top, a small screw hole either side of it, and six round holes below in two columns of three. On the right the IEC C14 inlet switch module sits in the cutout, its flange covering the hole with its rocker, fuse drawer and C14 socket showing. A warning says not to plug a cable into the IEC inlet until the assembly is complete, the wiring is verified and the cap is on.">
  <figcaption>The connections plate from outside, and the same plate with the inlet in it. <cite>Plate drawn from its STL and the module from its published flange size, both at the same scale, not from a build.</cite></figcaption>
</figure>

{% include step.html n="4" title="Wire the terminal block and mount the jacks" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>No mains cable in the inlet for this step.</b> Screws 1, 2 and 3 are mains and they are exposed until the cap goes on. If the machine has been powered, wait a few seconds after unplugging before you touch the terminal block.</p>
</div>

Land the inlet's three leads on screws 1, 2 and 3. **The yellow one is the earth and goes on screw 3.** Red and blue go on screws 1 and 2, either way round: the supply's AC input is not polarity-sensitive, and the fuse and the switch are both inside the inlet module. The module's colours are its own and do not follow any national code, so do not read live and neutral from them. Then take one pigtail per +V/-V pair: **7 with 4, 8 with 5, 9 with 6**, red terminal on the +V screw and black on the -V screw of the same pair.

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/psu-box-terminal-map-full-c373a1f9e370.png" alt="Diagram of the Mean Well LRS-350-24 seen from above, its nine-way terminal block down the left edge numbered 1 at the bottom to 9 at the top. Red leads run from screws 9, 8 and 7 and black leads from 6, 5 and 4, pairing 9 with 6, 8 with 5 and 7 with 4 into three barrel jacks labelled PJ3 to the Orange Pi buck, PJ2 to the powered USB hub, and PJ1 to the basically board. Below them the IEC C14 inlet switch module is drawn upright with its illuminated rocker, fuse drawer and C14 socket, and its three factory leads run to screws 1, 2 and 3, labelled AC/L, AC/N and earth: the yellow lead to screw 3, which is the earth, and the red and blue to screws 1 and 2, bracketed as interchangeable. A warning band says not to plug a cable into the IEC inlet until the assembly is complete, the wiring is verified and the cap is on.">
  <figcaption>Every lead that lands on the block, and the screw it lands on. <cite>Drawn from the Mean Well LRS-350 spec sheet, the inlet's catalog entry and the harness drawings, not from a build.</cite></figcaption>
</figure>

All three +V screws are the same rail inside the supply, and so are all three -V screws, so the pairing is about splitting the current rather than about which load goes where. What matters is that each pigtail keeps to one pair.

Tug-test every connection once they are all on.

Mount the three jacks in the connections plate. It is drilled with six 12 mm holes, two columns of three, 16 mm apart across and 20 mm apart down; the jack body goes behind the plate and its nut does up on the outside. <span class="fastener-todo">The hole size and spacing are read off the plate's STL. Which three of the six the jacks use, and what the other three are for, isn't recorded.</span>

Then route every wire through the connections plate so nothing can shift and touch the mains terminals once the box is closed. The connections plate is already fastened at this point (step 2) and the inlet is in it (step 3); the cap isn't on yet (step 5).

{% include step.html n="5" title="Close the box" %}

Fit the cap. It carries no screws of its own — its STL has no case-screw holes, and its footprint sits directly over the connections plate's face, which reads as a friction or snap fit rather than a fastened one, but that isn't confirmed against a built box either. The box is closed before the machine sees mains.

<div class="img-placeholder">Image coming</div>

{% include step.html n="6" title="Bolt the box to the frame" %}

The box hangs off the 2020 frame on 2 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws into 2 {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %} in the extrusion slot. It goes on the [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}) belonging to the top interface; the [layout render]({{ '/hardware/electronics/installation/' | relative_url }}) on the installation overview shows where it sits relative to the chute stepper.

<div class="callout">
  <p><b>No problem if you forgot them.</b> The {% include fastener.html size="M5" variant="t-nut" text="T-nut" %} this build specifies is the spring-loaded roll-in kind, which drops into the slot anywhere along its length, so it can still go in now without taking the frame apart. See <a href="{{ '/hardware/helpers/t-nuts/' | relative_url }}">Fitting T-nuts</a>.</p>
</div>

<div class="img-placeholder">Image coming</div>

The PSU box is now complete. Everything that plugs into it is on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.
