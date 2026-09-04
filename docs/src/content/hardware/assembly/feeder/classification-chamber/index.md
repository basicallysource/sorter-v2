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
  what the chamber is made of rather than how it goes together — two fasteners are now measured
  off the STLs, everything else about how the pieces join is still open. Correct it as you build.
parts_needed:
  - part: classification-dome
    qty: 1
  - part: camera-led-insert
    qty: 1
  - part: camera-extension
    qty: 1
  - part: camera-extension-mount
    qty: 1
  - part: cam-imx415
    qty: 1
  - part: scr-m2-8-shcs
    qty: 4
  - part: scr-m3-12-bhcs
    qty: 4
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channel/' | relative_url }}">classification C-channel</a> before you start.</strong> It's a required component of this page. Step 2 below walks through building it, using the C-channel page's own steps, with the finned rotor rather than faceted — Step 3 then bolts the chamber's own parts onto it.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
    <figcaption>A finished classification C-channel, from the C-channel page. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The classification chamber is where a part is lit and photographed on its way through. It sits on the fourth [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), the classification-channel one.

The parts are in the list above. Most fasteners for this stage still aren't recorded; what is, is called out in Step 2.

{% include fastener-legend.html %}

- **One per machine.**
- The Classification dome and the Camera & LED insert print **white**, so the chamber bounces light onto the part instead of absorbing it. The finned rotor is ash grey like the rest of the channel, and it's part of the classification C-channel build in Step 2, not listed again here.
- The Classification dome is large, roughly a full print bed.
- The camera sits on its own extension: a 50 mm extension tube and a clamp ring hold the 4K camera module. The overhead camera mount that hangs off the C-channels is a different part.

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Classification dome:</strong> prints white, roughly a full print bed. No screw holes anywhere in its geometry; how it closes onto the chamber is not recorded.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Camera &amp; LED insert:</strong> prints white. Takes 4 × {% include fastener.html size="M3" variant="socket-button" length="12" %} screws into the camera extension's mount ring (Step 3) and sits inside an outer ring of 10 holes to the rest of the chamber.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Camera extension and mount ring:</strong> a 50 mm extension tube and clamp ring that hold the 4K camera module above the insert. No heat inserts recorded.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>4K IMX415 camera module:</strong> mounts to the camera extension with 4 × {% include fastener.html size="M2" variant="socket-button" length="8" %} screws, self-tapping into the extension's two posts (Step 3).</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

{% include step.html n="2" title="Build the classification C-channel" %}

Build the classification channel as a normal [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), but with the finned rotor rather than a faceted one. Nothing else about it differs, colour included.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
  <figcaption>The classification channel, finned rotor fitted in the stator. Same photo as the C-channel page's step 5, since it's the same build. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Fit the insert, the camera and the dome" %}

Fit the Camera & LED insert, then the camera on its extension tube and mount ring, then close the chamber with the dome.

- **Insert to camera extension's mount ring:** 4 × {% include fastener.html size="M3" variant="socket-button" length="12" %} screws, 46 mm square pattern around the central opening. Measured off the STLs: the mount ring is a plain 6 mm clearance hole, and the insert takes a blind ~9.4 mm deep hole behind it, so 12 mm clears the mount and engages about 6 mm into the insert without bottoming out.
- **Insert to the rest of the chamber:** an outer ring of 10 holes, each 10 mm across. Not recorded: what fastener goes through them.
- **Camera board to the camera extension:** 4 × {% include fastener.html size="M2" variant="socket-button" length="8" %}, self-tapping into the extension's two posts.
- **Classification dome:** no screw holes anywhere. Not recorded how it closes onto the chamber.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/insert-iso-full-e4b396fc8c88.png" alt="Angled render of the camera and LED insert's top face, showing a ring of 10 large holes around the rim and 4 smaller blind holes around a central square opening">
    <figcaption>The insert's top face: 10 holes around the rim (mounts to the chamber), 4 smaller blind ones around the central opening (matches the extension mount, M3 × 12 mm). <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/extension-iso-full-8d1f0c51606f.png" alt="Angled render of the camera extension bracket, showing two posts each with a mounting hole">
    <figcaption>The camera extension: two posts, a hole near the top and bottom of each. The top pair takes the M2 camera-board screws. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

**Not recorded:** how the extension's bottom pair of posts joins the mount ring. <span class="fastener-todo">fastener not recorded</span>

{% include step.html n="4" title="Light the chamber" %}

The chamber is lit by a 24 V white/daylight LED strip, not by the 50 mm COB plate the feeder light posts use. Even, passive light is the point: the camera has to expose every part of the disc the same way. See [electronics]({{ '/hardware/electronics/' | relative_url }}) for how it is driven and for the current-limiting resistor.
