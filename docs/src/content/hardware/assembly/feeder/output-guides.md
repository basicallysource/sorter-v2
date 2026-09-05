---
layout: default
title: Output guides
type: how-to
section: hardware
slug: assembly-output-guides
kicker: Feeder — Output guides
lede: The printed guide on each channel's exit that stops parts riding round instead of dropping off.
permalink: /hardware/assembly/feeder/output-guides/
author: barthel
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly), not from an actual build.
  The tree records which channels take a guide and that it is held by friction, but not where on
  the channel it sits, at what angle, or how far it projects. This page exists to be filled in,
  not to be followed.
parts_needed:
  - part: output-guide
    qty: 4
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build and <a href="{{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}">arrange the C-channels</a> before you start.</strong> It's a required stage before this page, not optional or covered here — a guide only goes in once its channel and the one below it are standing at their final heights.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
    <figcaption>A finished C-channel, from the C-channel page. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

An output guide sits on one channel's exit and stops a part riding round past it. Without one a piece that doesn't drop off at the exit carries on round the rotor instead, so the guide is a wall that forces it off.

**Four per machine, one on every channel**, C1 and the classification channel included (see [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for what these names mean). It belongs to the channel it's mounted on rather than to the gap between two, which is why the count is four and not three.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Output guide:</strong> no heat inserts recorded and no fasteners of its own. Prints ash grey.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

{% include step.html n="2" title="Fit a guide on each channel" %}

The guide pushes onto the C-channel drive and is held by the fit alone: no screws, no inserts, nothing to tighten. Fit it once its channel is at its final height.

**Not recorded:** where on the drive it seats, at what angle, and how far it projects over the exit.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Check the handover" %}

Turn both channels by hand with a few parts on the upstream rotor and watch the transfer before wiring anything. A part should leave one rotor and land on the next without being carried back around.

Write down here what gap and angle worked.

<div class="img-placeholder">Image coming</div>
