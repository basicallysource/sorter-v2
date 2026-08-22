---
layout: default
title: Output guides
type: how-to
section: hardware
slug: assembly-output-guides
kicker: Feeder — Output guides
lede: The printed guides that carry parts from one C-channel to the next.
permalink: /hardware/assembly/feeder/output-guides/
author: barthel
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly), not from an actual build.
  The Output guide is in the parts catalog with a quantity and a colour and nothing else: it is
  in no assembly there, and where it mounts is not recorded anywhere. This page exists to be
  filled in, not to be followed.
parts_needed:
  - part: output-guide
    qty: 2
---

An output guide bridges the gap where one C-channel hands parts to the next, so a part leaving a rotor lands on the following channel instead of on the floor.

Two per machine. Which channels they sit between is not recorded: three feeder channels give two handovers, C1 to C2 and C2 to C3, so two guides is consistent with one per handover, but that is inference from the count rather than a documented fact.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Output guide:</strong> no heat inserts recorded and no fasteners of its own. Prints in the feeder colour.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

{% include step.html n="2" title="Fit a guide at each handover" %}

Build the channels and stand them first, see [arranging C-Channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}). The guide goes in once the two channels either side of it are at their final heights.

**Not recorded:** what the guide fastens to, with what, and at what angle. <span class="fastener-todo">fastener not recorded</span>

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Check the handover" %}

Turn both channels by hand with a few parts on the upstream rotor and watch the transfer before wiring anything. A part should leave one rotor and land on the next without being carried back around.

Write down here what gap and angle worked.

<div class="img-placeholder">Image coming</div>
