---
layout: default
title: Bulk input
type: how-to
section: hardware
slug: assembly-bulk-input
kicker: Feeder — Bulk input
lede: The bucket and cap that hold unsorted parts over the first C-channel.
permalink: /hardware/assembly/feeder/bulk-input/
author: barthel
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=bulk-cap) and the
  extrusion list on the bill of materials, not from an actual build. The bulk bucket itself is not
  published yet, so this page is mostly the shape of what is missing. Fill it in as you build.
parts_needed:
  - part: bulk-cap
    qty: 1
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channel/' | relative_url }}">C-channel</a> before you start.</strong> It's a required component of this page, not optional or covered here — Step 2 slides the Bulk cap onto one, it doesn't build one.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
    <figcaption>A finished C-channel, from the C-channel page (pictured with the finned rotor; C1 takes the faceted one). <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The bulk input is where unsorted parts go in: a bucket held above the first C-channel, feeding parts down onto the rotor as the channel turns. Parts dropped here start the feeder cascade: they leave C1's rotor for C2, then C3, and finally the classification channel, each stage spacing them out further before classification.

One per machine, on the first of the three feeder channels (called C1 in the software; see [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for the full naming). The Bulk cap is the only part of this stage in the catalog today.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bulk cap:</strong> no heat inserts, no screws recorded. It slides onto the C1 stator on a dovetail. Print it in the feeder colour.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bulk bucket:</strong> not published. It is a separate print, roughly a full bed, and is not in the parts catalog, so there is no file to link and no quantity to give. Ask in the Discord server before printing a stand-in part; the bulk bucket isn't published yet, so there's no verified file to copy.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Use the current Bulk cap. The v2 revision (2026-08-18) opened up the dovetail clearance because v1 needed too much force to slide on. If yours is a fight, check the file first rather than forcing it.</p>
</div>

{% include step.html n="2" title="Fit the bulk cap to the first channel" %}

Slide the Bulk cap onto the stator of the first [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), along its dovetail. No screws are recorded for this joint.

**Not recorded:** which way it faces relative to the handover to C2.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Mount the bucket supports" %}

Three pieces of 2020 extrusion cut to 270 mm carry the bucket above the channel. They are on the bill of materials as bulk bucket supports.

**Not recorded:** where they land on the [C-channel stand]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), what fastens them at either end, and how high the bucket sits above the rotor.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Fit the bucket" %}

Not documented, and the part is not published. Record the file, the fixings and the drop height here when it is.

<div class="img-placeholder">Image coming</div>
