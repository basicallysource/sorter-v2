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
contributors: [abrianbaker, brickcyclealice, barthel]
warning: >-
  **Reorganized to reference [Build the hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }})
  instead of describing frame construction inline, not yet reviewed by a
  builder.** Correct it as you build.
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
  - part: hsi-m3
    qty: 2
  - part: hsi-m4
    qty: 8
  - part: scr-m4-12-cs
    qty: 8
  - part: scr-m5-16-shcs
    qty: 9
  - part: tnut-m5-2020
    qty: 6
tools_needed: [Hex key, Drill or electric screwdriver]
---

The bottom interface is the Lazy Susan bearing assembly the chute rests and spins on, sitting between the chute and the bottom two layers of the frame.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">hex frame</a> before you start.</strong> It's a required component of this page, not optional or covered here — step 4 bolts onto one, it doesn't build one.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-finished-top-down-full-c6abfb4dad6e.jpg" alt="A finished hex frame from above, the alternating grey spoke and teal crossbeam pieces forming the inner ring inside the aluminum outer hexagon">
    <figcaption>A finished hex frame. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The parts list above is only the Lazy Susan bearing stack and the extrusion mounts added in step 4; the hex frame itself is [Build the hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }})'s own parts list, built ordinary and unmodified. The fasteners and quantities below are called out inline at each step.

{% include fastener-legend.html %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/XsVXOLvNsMA"
      title="Bottom interface assembly"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: Basically's own YouTube channel. Who filmed it isn't recorded.</cite></figcaption>
</figure>

The bottom interface stacks the chute mount, the Lazy Susan washer, the Lazy Susan bearing, and the bottom static part. The Lazy Susan itself is two discs, inner and outer, that spin independently: the chute mount screws to one disc and the bottom static part to the other. Here it is exploded into its components:

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-exploded-view-cropped-full-b7caae0e6e6f.png" alt="Exploded view of the bottom interface: chute mount on top, Lazy Susan washer, Lazy Susan bearing, and the corner mounting brackets below">
    <figcaption>Exploded view. <cite>Render: Adrianbaker.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-exploded-view-detail-full-43115f353ffc.png" alt="Close-up exploded view of the bottom interface parts separating from the mounting brackets">
    <figcaption>Detail of the same exploded view. <cite>Render: Adrianbaker.</cite></figcaption>
  </figure>
</div>

Once assembled, it mounts into the machine frame:

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-mounted-in-frame-full-476d171d148e.png" alt="The bottom interface assembly mounted into the aluminum extrusion machine frame">
    <figcaption><cite>Diagram pictures courtesy of Adrianbaker in the basically Discord.</cite></figcaption>
  </figure>
</div>

{% include step.html n="1" title="Preparation" %}

Press the heat inserts into both printed parts while they are still loose. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Lazy Susan chute mount:</strong> 4 × M4, evenly spaced around the circular mounting face.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/bottom-interface-prep-chute-mount-inserts-1-full-70bcf9a84302.jpg" alt="Looking into the Lazy Susan chute mount's circular face: four brass M4 heat inserts around the rim, with the raised square socket for the chute in the middle and the pass-through hole between two of the inserts">
    <figcaption>All four M4 inserts, with the pass-through hole. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Lazy Susan chute mount:</strong> 2 × M3, one on each of the two side faces, about halfway up. These are easy to miss because they are on a different face from the four M4 above, and they are what the <a href="{{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}">layer connectors</a> screw into when the chute goes on top. The pockets are measured off the published model rather than off a built machine, so if your print has nothing there, correct this page.</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/bottom-interface-chute-mount-m3-pocket-render-full-4eb13edc375d.png" alt="Render of the Lazy Susan chute mount seen from one side, with a red circle around a small pocket on a raised tab partway up the side wall">
      <figcaption>Where it is: the pocket sits on the small raised tab on the side wall. The far side is a mirror of this one. <cite>Render: Balloon.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/bottom-interface-chute-mount-m3-pocket-photo-full-ea22d619b316.png" alt="Close photo of the same raised tab on a printed chute mount, with a red circle around the empty pocket in it">
      <figcaption>The same tab on a printed part, circled. No insert is in it here. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
  </div>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Lazy Susan bottom static:</strong> 4 × M4, evenly spaced around the top face.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/bottom-interface-prep-bottom-static-inserts-2-full-4af3b6d0eda1.jpg" alt="The flat Lazy Susan bottom static ring from above, with all four M4 heat inserts and a hole between two of them">
    <figcaption>The bottom static ring, all four inserts visible. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Printed parts elsewhere in the machine take inserts too. Each assembly page lists its own in a **Preparation** step like this one.

{% include step.html n="2" title="Mount the Lazy Susan to the chute mount" %}

This step and the next work on opposite faces of the same bearing.

Remove the Lazy Susan's rubber tabs first (see [Preparing Lazy Susan]({{ '/hardware/helpers/lazy-susan/' | relative_url }})). **The washer goes on before the bearing**: set the Lazy Susan washer on the chute mount, then the [Lazy Susan]({{ '/hardware/parts/lazy-susan/' | relative_url }}) on top of that.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/bottom-interface-step2-washer-held-in-place-full-c591bbfe8687.jpg" alt="A thumb holding the Lazy Susan washer in place on the chute mount, before the bearing goes on top">
  <figcaption>Holding the washer in place before the bearing goes on. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

Line up a hole in the disc with one of the chute mount's inserts, drive an {% include fastener.html size="M4" variant="countersunk" length="12" %} screw, and repeat around the disc.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-step2-insert-through-hole-full-a67b71f5c4a7.png" alt="Close-up down an aligned hole in the Lazy Susan, with the brass M4 heat insert in the chute mount visible at the bottom of it">
    <figcaption>Lined up: the brass insert sits at the bottom of the hole. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-step1-drive-screw-full-622f05a7a4fe.jpg" alt="Driving a countersunk screw through the Lazy Susan into the chute mount">
    <figcaption><cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The {% include fastener.html size="M4" variant="countersunk" length="12" %} screws must be very tight. A drill or electric screwdriver will not get them there, so finish them with a hex key by hand. Machine vibration works a loose one out of a spot that is a hassle to reach later.</p>
</div>

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-parts/bottom-interface-step2-lazy-susan-bolted-full-f5f13531472d.jpg" alt="The Lazy Susan bearing bolted onto the chute mount, seen from above">
    <figcaption>Bolted on. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-parts/bottom-interface-step2-washer-visible-full-8e7b77b68c48.jpg" alt="Side view of the bolted assembly with the thin white Lazy Susan washer visible sandwiched between the bearing and the chute mount">
    <figcaption>Side view, with the washer visible between bearing and mount. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Mount the Lazy Susan to the bottom static part" %}

The bearing's other disc screws down into the bottom static part. All four of those screws go in through a single pass-through hole in the chute mount, rotating the assembly between each one.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-step2-holes-aligned-full-ebf0c303cdb4.jpg" alt="Lazy Susan hole aligned with the pass-through hole, seen from the top">
    <figcaption>Seen from the top, with the bearing hole over the pass-through. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-step2-pass-through-full-0522b2c6e677.jpg" alt="Pass-through hole in the chute mount with the screw reachable underneath">
    <figcaption>The pass-through hole in the chute mount. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

Set the chute mount and Lazy Susan assembly onto the bottom static part, then line up the pass-through hole with the insert marked by the red square.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-step2-place-chute-adapter-full-5d3dfd2a5794.jpg" alt="Placing the chute mount and Lazy Susan assembly onto the bottom static part">
    <figcaption><cite>Photo: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-step2-hole-red-square-full-fd314fd2c0a2.jpg" alt="Pass-through hole lined up over the heat insert, marked with a red square">
    <figcaption>Lined up over the marked insert. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

Drive the first {% include fastener.html size="M4" variant="countersunk" length="12" %} screw through the pass-through hole. Don't tighten it fully yet, leave some play while you get the rest of the four seated.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-step2-screwed-in-full-92f81fc1417a.jpg" alt="First screw driven through the pass-through hole">
  <figcaption><cite>Photo: Spencer.</cite></figcaption>
</figure>

Rotate the chute on the Lazy Susan, the way it turns in normal operation rather than forcing the whole assembly, to bring the pass-through hole over the next insert. Repeat for all four screws, then tighten all four the rest of the way.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-step2-rotate-90-full-7139a08a65e9.jpg" alt="Rotating the chute with the Lazy Susan to the next screw position">
    <figcaption><cite>Photo: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-step2-after-rotate-full-cdec5eba44af.jpg" alt="Pass-through hole lined up over the next heat insert after rotating">
    <figcaption>Pass-through hole now over the next insert. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

The bearing stack is now complete:

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-complete-full-8aa4adc4ac4c.jpg" alt="The completed bottom interface with chute mount, Lazy Susan bearing, and bottom static part assembled">
  <figcaption><cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include step.html n="4" title="Prepare the frame" %}

The bottom interface's frame is an ordinary [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}), built exactly as that page describes, with one addition: that page's step 3 has a note on getting this page's 6 T-nuts into 3 of its spokes while they're still open. Once it's built, a Lazy Susan extrusion mount pair bolts directly onto those 3 spokes, alternating around the ring, on top of the spoke's existing Frame 90° bracket and crossbeam rather than replacing anything.

Three Lazy Susan extrusion mounts carry the bearing assembly's weight; a hold in place bolts to each one first, as a pair, before either touches the extrusion. **They don't fix the chute itself**, that's attached up at the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}).

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-interface-step4-extrusion-mount-w1600-06391df95795.jpg" alt="A Lazy Susan extrusion mount and a Lazy Susan hold in place bolted together, forming a grey wedge with a triangular window through its web and two counterbored holes along its bottom face">
  <figcaption>Mount and hold in place, bolted together. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

The screw between the extrusion mount and the hold in place is an {% include fastener.html size="M5" variant="socket-button" length="16" %}.

Each mount then bolts directly onto the B/H spoke (158mm) already in place in the hex frame, through two more 5.5 mm M5 clearance holes, 30 mm apart, into a T-nut in the extrusion.

That's two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws per mount, 6 more on top of the 3 between mount and hold in place.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-parts/bottom-interface-step4-hex-frame-overview-full-bab24577ff64.jpg" alt="Top-down view of the assembled hexagonal layer frame with three Lazy Susan extrusion mounts fitted at alternating spokes">
    <figcaption>All three mounts, fitted around the ring. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-parts/bottom-interface-step4-hex-frame-corner-full-1a86a71db08d.jpg" alt="Closer view of one Lazy Susan extrusion mount fitted at a corner of the hexagonal layer frame">
    <figcaption>One mount, closer in. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

You end this step with two pieces: the bearing stack from steps 1-3, and the hex frame with its three Lazy Susan extrusion mounts now bolted onto alternating spokes. The frame goes on in [bottom two layers]({{ '/hardware/assembly/distribution/bin-frame/bottom-two-layers/' | relative_url }}); the bearing stack takes the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}).
