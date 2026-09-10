---
layout: default
title: Stacking the layers
type: how-to
section: hardware
slug: assembly-stacking-the-layers
kicker: Distribution — Stacking the layers
lede: Joining the finished layers and the top interface into the standing frame.
permalink: /hardware/assembly/distribution/stacking-the-layers/
author: barthel
contributors: [alex, brickcyclealice, zed0]
og_image: https://assets.basically.website/sorter-docs/assembly-stacking-upside-down-interface-first-w1600-a456339eabb6.jpg
last_verified: 2026-09-10
parts_needed:
  - part: scr-m5-16-shcs
    qty: 12
tools_needed: [Hex key]
---

Every layer of the bin frame is built flat, on its own, and none of the pages that build them says how they go together. This one does. At the end of it the frame is standing and empty, ready for the chutes to go in.

**Those screws are the only loose parts this page uses**, and the quantity above is for one joint. An N-layer machine has N joints, because the top interface's own frame lands on the stack the same way a layer does, so the whole job takes **12 × N** of them: 36 at three layers, 60 at five. Everything else is already fitted to the layers you are joining.

## Elements needed

Every one of these is built on another page. Have them all finished before you start, for an N-layer machine.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>1 × <a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-layer/' | relative_url }}">bottom layer</a></strong>, standing on its six casters. It is the base of the stack and the only layer that does not land on another one.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-layer-corner-bracket-on-d-w1600-67bd9444f306.jpg" alt="One corner of the bottom layer seen close up from above: the External bracket — bottom vertical standing on the collar with the end of piece D recessed in its square socket, the foot cover below the frame, and the caster under that">
    <figcaption>One corner of it. The socket is what the next layer lands on. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>N−1 × <a href="{{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}">regular layers</a></strong>, every bin layer above the lowest. Each one carries the vertical and the bracket that reach up to the layer above it.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-finished-square-full-779529c4b5f5.png" alt="A finished regular layer from above: the hexagon of extrusion with its spokes and crossbeams, and a vertical support capped by an External bracket — bottom vertical standing at each of the six corners">
    <figcaption>A finished regular layer. <cite>Photo: zed0.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>N × sets of <a href="{{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }}">bin retainers</a></strong>, twelve on every layer including the bottom one. Fit them while the layer is still something you can turn around, not once it is on the stack.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-bin-retainers-installed-w1600-31bf32089e71.png" alt="Bin retainers fastened to the outer faces of the hexagon frame, a pair either side of the joint between two A extrusions">
    <figcaption>One face with its pair on. <cite>Photo: zed0.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>1 × <a href="{{ '/hardware/assembly/distribution/top-interface/' | relative_url }}">top interface</a></strong>, its own hex frame included. That frame lands on the top bin layer through the same joint every other layer uses, which is why it counts as one of the N joints.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-framing-4-full-b9ae16940954.jpg" alt="The completed top interface resting on its top plate: the hex frame ring uppermost, the six interface brackets and their extrusion inside it, and the white chute mount at the centre">
    <figcaption>The finished interface, resting on its top plate the way it is built. <cite>Photo: zed0.</cite></figcaption>
  </figure>
</div>

The <a href="{{ '/hardware/assembly/distribution/chute/' | relative_url }}">chutes</a> and the <a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}">bottom interface</a> are not needed yet and must not go in while you stack.

{% include fastener-legend.html %}

{% include step.html n="1" title="Decide which way up to build" %}

There are two ways to do this and the machine comes out the same either way.

**Upside down**, which is how Alex built his: the top interface goes on the bench with its top plate down, then each layer is added onto it in turn, and the bottom layer with its casters goes on last. The whole stack is then turned over onto its wheels. His reason is worth the trouble: at every joint the 12 screws go in from **above**, straight down into a joint you can see, instead of overhead underneath a tower that is already taller than you.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-stacking-upside-down-interface-first-w1600-a456339eabb6.jpg" alt="A partly built machine standing upside down on a workbench, resting on its top plate, with the interface's vertical extrusions pointing up and a hex frame layer being added on top of them, a cordless driver on the bench beside it">
  <figcaption>The machine part way up, built upside down: the top interface is on the bench and the layers go on above it. <cite>Photo: alex.</cite></figcaption>
</figure>

**The right way up** starts from the bottom layer on its casters and works upward, capping the stack with the top interface. It matches the order the pages are written in and needs no flip at the end, but every joint is driven overhead and the tower gets tall quickly.

Whichever you pick, the joint itself is identical. **The whole frame goes together before any chute does**, which is why the chutes are not on this page.

{% include step.html n="2" title="Join one layer to the next" %}

<figure class="figure-float-right">
  <a href="https://assets.basically.website/sorter-docs/assembly-regular-layers-layer-joint-section-full-71e3c366f4e7.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-layer-joint-section-w1600-b40f8b102c10.jpg" alt="Vertical cross-section through one corner of two stacked layers, with the lower layer's extrusion and bottom-vertical tube in blue, the upper layer's bracket in purple, the two screw pairs dashed in red, and six numbered callouts">
  </a>
  <figcaption>One corner where any two layers meet, cut through the centre of the profile. Blue is the lower layer, purple the layer above. The numbers match the list below. Click to enlarge. <cite>Drawn from the part geometry rather than from a build, by Balloon.</cite></figcaption>
</figure>

A finished layer already carries everything that spans up to the next one: its vertical extrusion standing out of the External bracket — side, and the External bracket — bottom vertical capping that extrusion. Joining two layers is therefore only the flange joint at each of the six corners.

Set the next layer down so that each External bracket — bottom vertical's flange face meets the underside of that layer's External bracket — side, and drive 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws up through each flange into the bracket above. **That pair is the whole layer-to-layer fastening, 12 screws per joint.**

The numbers on the drawing:

<ol class="keyed-list">
  <li><strong>External bracket — side and cover</strong>, the 60.5 mm collar at each frame.</li>
  <li><strong>Piece C</strong>, 154 mm cut. It starts 3 mm above its own collar's underside and ends 3 mm below the flange face of the collar above, so it spans the whole 160 mm between one frame and the next. At the bottom joint this is piece D instead, which is the same span plus the leg.</li>
  <li><strong>External bracket — bottom vertical</strong>, 119.6 mm of tube. It sleeves the upper part of the extrusion, so it is not visible on an assembled machine, and its foot seats on the rim of its own layer's collar. That seat is what sets the 160 mm spacing between frames.</li>
  <li class="key-screw"><strong>The two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws that join the layers</strong>, up through the flange into the bracket above. The flange has a 5.6 mm clearance hole through 8 mm of plastic and the bracket above a 4.4 mm self-tapping hole 10 mm deep, so the screw is 8 mm of clearance and 8 mm of thread, and a longer one bottoms out before it clamps.</li>
  <li class="key-screw"><strong>The two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws that clamp the bracket onto the extrusion</strong>, self-tapping through the bracket wall. The extrusion is held only here, in its own layer's bracket, and nothing screws into it from the layer above.</li>
  <li class="key-note"><strong>Where two extrusions meet</strong>: they stop about 3 mm short of each other at the flange face and never touch.</li>
</ol>

<div class="clear-float"></div>

<div class="callout">
  <p>The joint is the same at every level, including where the first regular layer lands on the bottom layer, and where the top interface's own hex frame lands on the topmost bin layer. There is no special case anywhere in the stack.</p>
</div>

{% include step.html n="3" title="Work through the whole stack" %}

Repeat step 2 until every layer is on and the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) is at the top of the tower. Building upside down that means starting with the interface and finishing with the bottom layer; the right way up it means the reverse.

Nothing else is fastened between layers. The layers do not interlock with each other through the extrusion: the 12 screws at each joint are the only thing holding one layer to the next, which is worth knowing before you go looking for a fixing you have missed.

## The finished result

Every layer on, twelve screws at each joint, the top interface at the top of the tower and nothing inside it.

<div class="img-placeholder">Photo of the finished frame standing on its casters: the bottom layer, the regular layers and the top interface joined into one tower, with no chutes in it yet.</div>

The frame is now standing and empty. The [chutes]({{ '/hardware/assembly/distribution/chute/' | relative_url }}) go in next, one at a time and without their funnels, and the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) goes on after them, because it screws onto the chute stack rather than onto the frame. Both are on the [Chute]({{ '/hardware/assembly/distribution/chute/' | relative_url }}) page.
