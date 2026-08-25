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

Measured off the STLs. The Camera & LED insert's top face carries two hole patterns, both visible in the first render below: 4 countersunk M3 holes (3.4 mm clearance) in a 46 mm square around the central opening, and an outer ring of 10 larger holes (10 mm, no thread, 65 mm radius, 36° apart). The inner 46 mm square repeats on the camera extension's mount ring at the same 3.4-3.5 mm size — that's the real match, so the insert's 4 holes are the mount-ring joint, M3 like everything else on this page, not the camera board.

The camera board itself mounts to the **camera extension**, not the insert. It's a bracket with two posts, each carrying a hole near the top and near the bottom — 4 holes total, 2.6 mm, sized for the **M2** the IMX415 module's own datasheet calls for (barthel confirmed 2.6 mm is right, gave the module's board thickness — 1.57 mm — and confirmed the joint is self-tapping, straight into the post). Working from those numbers: 1.57 mm of board, then self-tapping the rest of the way into an 8 mm-deep post — {% include fastener.html size="M2" variant="socket-button" length="8" %} reaches most of the way into the post for a solid thread bite without quite bottoming out before the head seats.

**M2 is new to this catalog.** Every other screw on the site is M3, M4, M5 or M6 — there's no M2 part id yet, so this one isn't in the parts list above and doesn't have a legend colour (it renders grey). Add `scr-m2-8-shcs` (or whichever head style is correct) when this is confirmed.

The Classification dome itself has no screw holes anywhere in its own geometry — how it closes onto the rest of the chamber (screwed, clipped, or just resting in place) isn't recorded either.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/insert-iso-full-e4b396fc8c88.png" alt="Angled render of the camera and LED insert's top face, showing a ring of 10 large holes around the rim and 4 smaller countersunk holes around a central square opening">
    <figcaption>The insert's top face: 10 holes around the rim (mounts to the chamber), 4 smaller ones around the central opening (matches the extension mount, M3). Rendered from the part geometry, not from a build.</figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/extension-iso-full-8d1f0c51606f.png" alt="Angled render of the camera extension bracket, showing two posts each with a mounting hole">
    <figcaption>The camera extension: two posts, a hole near the top and bottom of each. The top pair takes the M2 camera-board screws. Rendered from the part geometry, not from a build.</figcaption>
  </figure>
</div>

**Not recorded:** what fastens through the insert's outer ring and what it threads into, how the extension's bottom pair joins the mount ring, and how the dome closes the chamber. <span class="fastener-todo">fastener not recorded</span>

{% include step.html n="3" title="Light the chamber" %}

The chamber is lit by a 24 V white/daylight LED strip, not by the 50 mm COB plate the feeder light posts use. Even, passive light is the point: the camera has to expose every part of the disc the same way. See [electronics]({{ '/hardware/electronics/' | relative_url }}) for how it is driven and for the current-limiting resistor.
