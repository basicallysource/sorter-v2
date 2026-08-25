---
layout: default
title: Classification chamber
type: how-to
section: hardware
slug: assembly-classification-chamber
kicker: Feeder — Classification chamber
lede: Where parts are imaged for classification.
permalink: /hardware/assembly/feeder/classification-chamber/
author: spencer
contributors: [barthel]
warning: >-
  **AI-generated first draft.** Written from the parts registry in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=classification-chamber),
  not from an actual build. The assembly order is still not recorded, so this page mostly lists
  what the chamber is made of rather than how it goes together — one fastener is now measured
  off the STLs, everything else about how the pieces join is still open. Correct it as you build.
parts_needed:
  - part: classification-dome
    qty: 1
  - part: rotor-finned
    qty: 1
  - part: camera-led-insert
    qty: 1
  - part: camera-extension
    qty: 1
  - part: camera-extension-mount
    qty: 1
  - part: cam-imx415
    qty: 1
---

The classification chamber is where a part is lit and photographed on its way through. It sits on the fourth [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), the classification-channel one.

The parts are in the list above. Most fasteners for this stage still aren't recorded; what is, is called out in Step 2.

{% include fastener-legend.html %}

- **One per machine.**
- The three chamber parts print **white** rather than charcoal, so the chamber bounces light onto the part instead of absorbing it.
- The Classification dome is large, roughly a full print bed.
- The camera sits on its own extension: a 50 mm extension tube and a clamp ring hold the 4K camera module. The overhead camera mount that hangs off the C-channels is a different part.

{% include step.html n="1" title="Build the classification C-channel" %}

Build the classification channel as a normal [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), but with the finned rotor rather than a faceted one, and in ash grey rather than charcoal.

{% include step.html n="2" title="Fit the insert, the camera and the dome" %}

Fit the Camera & LED insert, then the camera on its extension tube and mount ring, then close the chamber with the dome.

Measured off the Camera & LED insert's own STL: its top face carries two separate hole patterns, both visible in the render below. Four countersunk M3 holes (3.4 mm clearance) sit in a 46 mm square around the central opening — most likely the camera board's own mounting holes. A second, outer ring of 10 larger holes (10 mm, no thread, 65 mm radius, 36° apart) runs around the rim — almost certainly what fastens the insert to the rest of the chamber, but nothing records what goes through them or what they thread into. The Classification dome itself has no screw holes anywhere in its own geometry — how it closes onto the rest of the chamber (screwed, clipped, or just resting in place) isn't recorded either.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/insert-iso-full-e4b396fc8c88.png" alt="Angled render of the camera and LED insert's top face, showing a ring of 10 large holes around the rim and 4 smaller countersunk holes around a central square opening">
  <figcaption>The insert's top face: 10 larger holes around the rim (what it mounts to the chamber with), 4 smaller countersunk ones around the central opening (likely the camera board). Rendered from the part geometry, not from a build.</figcaption>
</figure>

**Not recorded:** what fastens through the outer ring and what it threads into, what screw the inner 4 holes take, how the extension tube and mount ring join, and how the dome closes the chamber. <span class="fastener-todo">fastener not recorded</span>

{% include step.html n="3" title="Light the chamber" %}

The chamber is lit by a 24 V white/daylight LED strip, not by the 50 mm COB plate the feeder light posts use. Even, passive light is the point: the camera has to expose every part of the disc the same way. See [electronics]({{ '/hardware/electronics/' | relative_url }}) for how it is driven and for the current-limiting resistor.
