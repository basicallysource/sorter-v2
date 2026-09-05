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

Fasten the PSU back mount and the PSU connections plate to the supply's case with the 4 {% include fastener.html size="M4" variant="countersunk" length="6" %} screws, before wiring: the connections plate's cable routing needs to be in place first.

Which part takes which screw isn't fully recorded, but the parts' own STLs answer most of it: the back mount has one clearance hole into the case (at the end away from the terminal block, the same end that bolts to the frame in step 5), and the connections plate has two, spread along the case nearer the terminal-block end. That's three of the four screws. The PSU box cap's STL has no case-screw holes at all, so it isn't fastened here despite this step covering all three parts in the parts list; see step 4. <span class="fastener-todo">Read from the STLs, not confirmed against a built box — worth checking against a real assembly, and the fourth screw's hole isn't accounted for either way.</span>

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Wire the terminal block" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The PSU must be unplugged from the wall for this entire step. Screws 1-3 carry mains voltage whenever it's plugged in; after unplugging, wait a few seconds before touching the terminal block.</p>
</div>

Land the fused IEC inlet switch's leads on screws 1, 2 and 3, and the three DC output pigtails on the +V/-V pairs above. Tug-test each connection, then route every wire through the connections plate so nothing can shift and touch the mains terminals once the box is closed.

The connections plate is already fastened at this point (step 2); the cap isn't on yet (step 4).

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Close the box" %}

Fit the cap. It carries no screws of its own — its STL has no case-screw holes, and its footprint sits directly over the connections plate's face, which reads as a friction or snap fit rather than a fastened one, but that isn't confirmed against a built box either. The box is closed before the machine sees mains.

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Bolt the box to the frame" %}

The box hangs off the 2020 frame on 2 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws into 2 {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %} in the extrusion slot. It goes on the [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}) belonging to the top interface; the [layout render]({{ '/hardware/electronics/installation/' | relative_url }}) on the installation overview shows where it sits relative to the chute stepper.

<div class="callout">
  <p><b>No problem if you forgot them.</b> The {% include fastener.html size="M5" variant="t-nut" text="T-nut" %} this build specifies is the spring-loaded roll-in kind, which drops into the slot anywhere along its length, so it can still go in now without taking the frame apart. See <a href="{{ '/hardware/helpers/t-nuts/' | relative_url }}">Fitting T-nuts</a>.</p>
</div>

<div class="img-placeholder">Image coming</div>

The PSU box is now complete. Everything that plugs into it is on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.
