---
layout: default
title: Overhead camera mount
type: how-to
section: hardware
slug: assembly-overhead-camera-mount
kicker: Feeder — Overhead camera mount
lede: The rod arm that hangs a detection camera over a C-channel.
permalink: /hardware/assembly/feeder/camera-mount/
author: barthel
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=camera-mount), not from an
  actual build. The A/B connector's joint is now measured off the STLs. The rod mounts, the camera
  fixing and every photograph are still missing. Fill it in as you build.
parts_needed:
  - part: camera-mount-part-6
    qty: 1
  - part: camera-mount-part-37
    qty: 1
  - part: camera-mount-part-37b
    qty: 1
  - part: camera-mount-rod-mount
    qty: 2
  - part: rod-steel-3-8
    qty: 2
  - part: scr-m3-12-cs
    qty: 3
  - part: nut-m3
    qty: 3
---

The overhead camera mount is a pair of 3/8 in steel rods clamped to a [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), carrying a printed arm that holds a detection camera above the channel.

The fasteners and quantities in the parts list come from the parts registry and are called out inline at each step. **The list above is one arm's worth**, and the machine takes 2, so 4 rod mounts and 4 rod pieces in total.

The camera these carry is the **OV9732 720p module**, which the parts registry lists as the C-channel and drop plate detection camera. The 4K IMX415 is a different camera and belongs to the [classification chamber]({{ '/hardware/assembly/feeder/classification-chamber/' | relative_url }}).

{% include fastener-legend.html %}

Two arms for three feeder channels is not a mistake. The software's `split_feeder` camera layout puts a camera on C2, on C3 and on the carousel, which lines up with the two arms and the two [light posts]({{ '/hardware/assembly/feeder/light-post/' | relative_url }}). That pairing is inferred from the part counts and the software config, not from a build.

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Steel rod:</strong> bought as 4 ft stock and cut down. One length yields all four pieces, roughly 1 ft each. <strong>The exact cut length is not recorded.</strong></p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Printed parts:</strong> no heat inserts recorded. The arm uses 3 M3 nuts rather than inserts, so nothing needs pressing in before assembly.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

Colour does not matter on any of these parts.

{% include step.html n="2" title="Clamp the rod mounts to the C-channel" %}

Two Rod-to-C-channel mounts (Part 33) carry the rods on the channel.

**Not recorded:** which holes on the channel they use, what fastens them, and how far apart they sit. <span class="fastener-todo">fastener not recorded</span>

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Fit the rods" %}

Slide a cut rod into each mount.

**Not recorded:** how the rods are clamped and how far they stand proud of the mounts.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Join arm A to the connector" %}

Overhead camera mount A (part 37) bolts to the A/B connector (part 6) with the 3 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws and 3 M3 nuts in the list above — measured off the two STLs, both parts carry the same bolt circle: 12 holes, 3.3 mm across, evenly spaced 30° apart on a 27 mm radius. Only 3 of the 12 are used at once, so the joint sets the arm's **angle**, not its reach — pick which 3 (every 4th hole, 120° apart, matching the 3-screw pattern) to fix the rotation you want, in 30° steps.

**Not recorded:** which 3 of the 12 holes are the intended ones, and how part B (part 37b) joins in — it doesn't share this bolt circle, so it connects some other way. <span class="fastener-todo">fastener not recorded</span>

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/connector-iso-full-9426650a084d.png" alt="Angled render of the A/B connector, showing all 12 holes of its bolt circle">
  <figcaption>The connector's bolt circle: 12 holes, 30° apart. Any 3 spaced 120° apart (every 4th hole) fix one of 4 possible rotations. Rendered from the part geometry, not from a build.</figcaption>
</figure>

{% include step.html n="5" title="Fit the camera and set the height" %}

**Not recorded:** how the camera fastens to the arm, how high above the channel it sits, and how it is squared to the channel. All three change what the detection zones see, so write down what worked. <span class="fastener-todo">fastener not recorded</span>

Build the second arm the same way. Setting the zones up afterwards is software, see [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}).

<div class="img-placeholder">Image coming</div>
