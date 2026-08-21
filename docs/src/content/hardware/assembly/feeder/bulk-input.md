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
  **Skeleton page.** Written from the parts registry in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=bulk-cap) and the
  extrusion list on the [bill of materials]({{ '/hardware/BOM' | relative_url }}), not from a
  build. The bulk bucket itself is not published yet. Fill it in as you build.
parts_needed:
  - part: bulk-cap
    qty: 1
---

The bulk input is where unsorted parts go in: a bucket held above the first C-channel, feeding parts down onto the rotor as the channel turns.

- **One per machine**, on the first feeder channel (C1).
- **The Bulk cap** slides onto the C1 [stator]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}) on a dovetail. It is the only part of this stage in the catalog today. The v2 revision (2026-08-18) opened up the dovetail clearance, because v1 needed too much force to slide on. If yours is a fight, check you have the current file.
- **The bulk bucket is not published.** It is a separate print, roughly a full bed, and is not in the parts catalog yet, so there is no file to link and no quantity to give. Ask before printing something in its place.
- **Its supports are on the BOM.** The extrusion list gives 3 pieces of 2020 at 270 mm as bulk bucket supports. How they attach at either end is not recorded.

{% include step.html n="1" title="Fit the bulk cap to the first channel" %}

Slide the Bulk cap onto the stator of the first C-channel, along its dovetail. No screws are recorded for this joint.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Mount the bucket supports" %}

Three 270 mm 2020 extrusions carry the bucket above the channel. Where they land on the [C-channel stand]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), what fastens them, and how high the bucket sits above the rotor, are all unrecorded.

{% include step.html n="3" title="Fit the bucket" %}

Not documented, and the part is not published. Record the file, the fixings and the drop height here when it is.
