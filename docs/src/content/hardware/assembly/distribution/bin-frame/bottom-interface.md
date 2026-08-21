---
layout: default
title: Bottom interface
type: how-to
section: hardware
slug: assembly-bottom-interface
kicker: Bin frame — Bottom interface
lede: The component the chute rests on top of.
permalink: /hardware/assembly/distribution/bin-frame/bottom-interface/
author: spencer
contributors: [abrianbaker, brickcyclealice]
parts_needed:
  - part: brg-lazy-susan
    qty: 1
  - part: ls-mount-to-chute
    qty: 1
  - part: ls-bottom-static
    qty: 1
  - part: ls-washer
    qty: 1
  - part: ls-mount-to-extrusion
    qty: 3
  - part: ls-hold-in-place
    qty: 3
  - part: hsi-m4
    qty: 8
  - part: scr-m4-12-cs
    qty: 8
  - part: scr-m5-16-shcs
    qty: 3
---

The fasteners and quantities in the parts list are called out inline at each step.

{% include fastener-legend.html %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/XsVXOLvNsMA"
    title="Bottom interface assembly"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

The bottom interface stacks the chute mount, the Lazy Susan washer, the Lazy Susan bearing, and the bottom static part. Here it is exploded into its components:

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/exploded-view-cropped.1e520f8cdb04989d.jpg" alt="Exploded view of the bottom interface: chute mount on top, Lazy Susan washer, Lazy Susan bearing, and the corner mounting brackets below">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/exploded-view-detail.43115f353ffc8e8a.png" alt="Close-up exploded view of the bottom interface parts separating from the mounting brackets">
  </figure>
</div>

Once assembled, it mounts into the machine frame:

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/mounted-in-frame.476d171d148ec300.png" alt="The bottom interface assembly mounted into the aluminum extrusion machine frame">
    <figcaption>Diagram pictures courtesy of Adrianbaker in the basically Discord.</figcaption>
  </figure>
</div>

{% include step.html n="1" title="Preparation" %}

Press the heat inserts into both printed parts while they are still loose. Once the Lazy Susan is on, an iron cannot reach them. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Lazy Susan chute mount:</strong> 4 × M4, evenly spaced around the circular mounting face.</p>
  </div>
  <div class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </div>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Lazy Susan bottom static:</strong> 4 × M4, evenly spaced around the top face.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://img.basically.website/web/assembly/bottom-interface/prep-bottom-static-inserts.c343287e535671de.jpg" alt="Close-up of the black Lazy Susan bottom static ring with three of its four brass M4 heat inserts clearly visible, pressed flush into the top face">
    <figcaption>Three of the four M4 inserts in the bottom static part. The fourth sits under the chute mount coming down on the right.</figcaption>
  </figure>
</div>

Printed parts elsewhere in the machine take inserts too. Each assembly page lists its own in a **Preparation** step like this one.

{% include step.html n="2" title="Mount the Lazy Susan to the chute mount" %}

The Lazy Susan is two discs, inner and outer, that spin independently. The chute mount screws to one disc and the bottom static part to the other, so this step and the next work on opposite faces of the same bearing.

Remove the Lazy Susan's rubber tabs first (see [Preparing Lazy Susan]({{ '/hardware/helpers/lazy-susan/' | relative_url }})). Set the Lazy Susan washer on the chute mount and the [Lazy Susan]({{ '/hardware/parts/lazy-susan/' | relative_url }}) on top. Line up a hole in the disc with one of the chute mount's inserts, drive an {% include fastener.html size="M4" variant="countersunk" length="12" %} screw, and repeat around the disc.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/step2-insert-through-hole.78cbbc1254a95a1e.jpg" alt="Close-up down an aligned hole in the Lazy Susan, with the brass M4 heat insert in the chute mount visible at the bottom of it">
    <figcaption>Lined up: the brass insert sits at the bottom of the hole.</figcaption>
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/step1-drive-screw.622f05a7a4fe703e.jpg" alt="Driving a countersunk screw through the Lazy Susan into the chute mount">
  </figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The {% include fastener.html size="M4" variant="countersunk" length="12" %} screws must be very tight. A drill or electric screwdriver will not get them there, so finish them with a hex key by hand. Machine vibration works a loose one out of a spot that is a hassle to reach later.</p>
</div>

<img class="doc-figure" src="https://img.basically.website/web/assembly/bottom-interface/lazy-susan-on-chute-mount.d478621b1f81e5ae.jpg" alt="Lazy Susan bearing mounted on the chute mount with the washer between them">

{% include step.html n="3" title="Mount the Lazy Susan to the bottom static part" %}

The bearing's other disc screws down into the bottom static part. All four of those screws go in through a single pass-through hole in the chute mount, rotating the assembly between each one.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/step2-holes-aligned.ebf0c303cdb41f27.jpg" alt="Lazy Susan hole aligned with the pass-through hole, seen from the top">
    <figcaption>Seen from the top, with the bearing hole over the pass-through.</figcaption>
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/step2-pass-through.0522b2c6e67778df.jpg" alt="Pass-through hole in the chute mount with the screw reachable underneath">
    <figcaption>The pass-through hole in the chute mount.</figcaption>
  </figure>
</div>

Set the chute mount and Lazy Susan assembly onto the bottom static part, then line up the pass-through hole with the insert marked by the red square.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/step2-place-chute-adapter.5d3dfd2a5794d4ef.jpg" alt="Placing the chute mount and Lazy Susan assembly onto the bottom static part">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/step2-hole-red-square.fd314fd2c0a2a527.jpg" alt="Pass-through hole lined up over the heat insert, marked with a red square">
    <figcaption>Lined up over the marked insert.</figcaption>
  </figure>
</div>

Drive the first {% include fastener.html size="M4" variant="countersunk" length="12" %} screw through the pass-through hole.

<img class="doc-figure" src="https://img.basically.website/web/assembly/bottom-interface/step2-screwed-in.92f81fc1417a1a21.jpg" alt="First screw driven through the pass-through hole">

Rotate the chute on the Lazy Susan, the way it turns in normal operation rather than forcing the whole assembly, to bring the pass-through hole over the next insert. Repeat for all four screws.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/step2-rotate-90.7139a08a65e920ad.jpg" alt="Rotating the chute with the Lazy Susan to the next screw position">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/step2-after-rotate.cdec5eba44af1747.jpg" alt="Pass-through hole lined up over the next heat insert after rotating">
    <figcaption>Pass-through hole now over the next insert.</figcaption>
  </figure>
</div>

The bearing stack is now complete:

<img class="doc-figure" src="https://img.basically.website/web/assembly/bottom-interface/complete.8aa4adc4ac4c5ad9.jpg" alt="The completed bottom interface with chute mount, Lazy Susan bearing, and bottom static part assembled">

{% include step.html n="4" title="Mount it into the frame" %}

Three Lazy Susan extrusion mounts fix the assembly to the external extrusion of the layer frame, and a Lazy Susan hold in place bolts to each one. They go together as a pair before either touches the extrusion.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/step4-extrusion-mount.875e1c5a694ae3de.jpg" alt="A Lazy Susan extrusion mount and a Lazy Susan hold in place bolted together, forming a grey wedge with a triangular window through its web and two counterbored holes along its bottom face">
    <figcaption>The extrusion mount and the hold in place, bolted together.</figcaption>
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/bottom-interface/step4-extrusion-mount-on-2020.c91601474f43c5a1.jpg" alt="The same pair with a length of 2020 aluminum extrusion seated in the channel along its sloped edge">
    <figcaption>With a length of 2020 in its channel. Photos by BrickCycleAlice.</figcaption>
  </figure>
</div>

The screw between the two is an {% include fastener.html size="M5" variant="socket" length="16" %}: it drops through the counterbore in the hold in place, passes a 5.5 mm clearance hole, and taps itself into a 4.4 mm hole in the extrusion mount, the same tap-into-plastic join used everywhere else on the frame. **16 mm is the longest that fits.** Measured off the two STLs, the head seat is exactly 16.0 mm above the bottom of the tapped hole, so a longer screw bottoms out before it clamps.

Each mount then fixes to the frame through the two 5.5 mm M5 clearance holes along its bottom face, 30 mm apart. **These bolt into plastic, not into T-nuts.** Which screw goes in them is not recorded: <span class="fastener-todo">fastener not recorded</span>. That is 6 more screws on top of the 3 in the parts list, two per mount.

The order the three mounts go on around the ring is not recorded either.

The 2020 extrusion itself is not in the parts list above, because its length depends on your layer count. Every cut piece in the machine comes off the [framing cut list](https://parts-calculator.basically.website/framing).
