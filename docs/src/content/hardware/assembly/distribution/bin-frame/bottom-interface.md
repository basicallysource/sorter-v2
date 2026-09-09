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
contributors: [abrianbaker, brickcyclealice, barthel, daddyosbricksbill, danny]
warning: >-
  **Steps 1-3 have not been checked against a machine.** Steps 4 to 8, where
  this assembly mounts, were corrected from builds by Daddy-O's Bricks - Bill
  and Danny. Correct the rest as you go.
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

The bottom interface is the Lazy Susan bearing assembly the chute rests and spins on, slung underneath the bottom layer's frame.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>This assembly has no frame of its own.</strong> It hangs under the <strong>bottom layer's</strong> <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">hex frame</a>, built on <a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-two-layers/' | relative_url }}">bottom two layers</a>, so you don't need an extra one. Steps 4 to 8 bolt onto that frame's spokes from underneath.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-hex-frame-finished-top-down-w1600-a62a42d595ca.jpg" alt="A finished hex frame from above: six B spokes and their printed crossbeams forming the inner ring inside the aluminum outer hexagon, with a printed corner bracket at each of the six vertices">
    <figcaption>A finished hex frame. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The parts list above is only the Lazy Susan bearing stack and the extrusion mounts added in steps 4 to 8. The fasteners and quantities below are called out inline at each step.

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
    <figcaption>Look at the middle of this one, not the corners. <cite>Diagram pictures courtesy of Adrianbaker in the basically Discord.</cite></figcaption>
  </figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>The corners in that render are out of date.</strong> It shows an ordinary bottom vertical and cover at floor level with the caster under it. On a build, each bottom corner takes the <strong>External bracket — foot cover</strong>, and the extrusion is piece D, running down through the corner to the foot connector the caster screws into. See <a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-two-layers/' | relative_url }}#step-2">bottom two layers, steps 2 to 4</a>. The Lazy Susan mounting in the middle of the render is right.</p>
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
    <p><strong>Lazy Susan chute mount:</strong> 2 × M3 for the <a href="{{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}">layer connectors</a>, one on each side face, on the small raised tab about halfway up.</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/bottom-interface-chute-mount-m3-pocket-render4-full-1fb455668c8e.png" alt="Render of the Lazy Susan chute mount's side face, with a red circle around the small pocket on the raised tab partway up the wall">
      <figcaption>The pocket on the near side face. The far side is a mirror of it. <cite>Render: Balloon.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/bottom-interface-chute-mount-m3-pocket-photo-full-ea22d619b316.png" alt="Close photo of the same raised tab on a printed chute mount, with a red circle around the empty pocket in it">
      <figcaption>The same pocket on a printed part, empty. <cite>Photo: BrickCycleAlice.</cite></figcaption>
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

{% include step.html n="4" title="Bolt a hold in place to each mount" %}

Three Lazy Susan extrusion mounts carry the bearing, bolted under alternating **B spokes of the bottom layer's frame**. Nothing already on a spoke moves. They don't hold the chute; that's the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}).

Bolt a hold in place onto each mount with one {% include fastener.html size="M5" variant="socket-button" length="16" %}, before either part touches the extrusion.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/bottom-interface-hold-in-place-bolted-to-mount-w1600-ccd8efee1343.jpg" alt="A Lazy Susan extrusion mount lying on a bench with the hold in place standing on top of it and a stainless M5 button head part way into the hole through both">
    <figcaption>Driving the screw through the hold in place into the mount. <cite>Photo: Danny.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-lazy-susan-extrusion-mount-three-views-w1600-581de80090b8.jpg" alt="Three views of the same printed part on a white background: the Lazy Susan extrusion mount with its hold in place bolted under it, a grey wedge with a triangular window through its web and counterbored slots along its bottom face">
    <figcaption>The bolted pair, from three angles. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="5" title="Prestart the T-nuts" %}

Drop an {% include fastener.html size="M5" variant="socket-button" length="16" %} through each of the mount's two counterbored holes and start a {% include fastener.html size="M5" variant="t-nut" %} on the end, two or three turns. Leave them loose enough to swing.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/bottom-interface-tnuts-prestarted-underside-w1600-3f02a78de0bc.jpg" alt="The mounting face of the extrusion mount, with two roll-in T-nuts started on screws and standing proud of the surface">
    <figcaption>Both nuts started, still loose. <cite>Photo: Danny.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/bottom-interface-tnut-screws-in-pass-throughs-w1600-22ff4fa4ee3e.jpg" alt="Looking down the mount's two counterbored holes at the button heads of the screws sitting in them">
    <figcaption>The same two screws from the other side. <cite>Photo: Danny.</cite></figcaption>
  </figure>
</div>

Roll-in nuts enter the slot anywhere along it. Slide-in nuts don't, and have to go into the spoke before the frame is built: see [Fitting T-nuts]({{ '/hardware/helpers/t-nuts/' | relative_url }}).

{% include step.html n="6" title="Slide the mount onto the spoke" %}

Slide the mount onto a B spoke (158 mm) already in the frame, T-nuts into the extrusion slot. Push up on each nut with a screwdriver as it goes, so it seats square.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/bottom-interface-tnuts-entering-extrusion-slot-w1600-1291f08f0d51.jpg" alt="Close view of the two prestarted T-nuts lined up with the open end of the 2020 extrusion slot on the spoke">
    <figcaption>Nuts lined up with the slot. <cite>Photo: Danny.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/bottom-interface-mount-positioned-on-spoke-w1600-f744454219c5.jpg" alt="The extrusion mount sitting in position along a spoke of the hexagonal frame, with both T-nut screws still standing proud">
    <figcaption>In position, screws not yet tightened. <cite>Photo: Danny.</cite></figcaption>
  </figure>
</div>

{% include step.html n="7" title="Tighten" %}

Tighten both {% include fastener.html size="M5" variant="socket-button" length="16" %} screws into the T-nuts.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/bottom-interface-driving-mount-screw-w1600-f78a12439427.jpg" alt="An electric screwdriver driving one of the two screws in the top face of the extrusion mount while it sits on the frame">
    <figcaption><cite>Photo: Danny.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/bottom-interface-mount-seated-on-spoke-w1600-55004a93fb80.jpg" alt="The mount and its hold in place seated down onto the spoke's extrusion, seen from the outside of the frame">
    <figcaption>Seated down onto the extrusion. <cite>Photo: Danny.</cite></figcaption>
  </figure>
</div>

{% include step.html n="8" title="Repeat for the other two mounts" %}

Nine {% include fastener.html size="M5" variant="socket-button" length="16" %} and six {% include fastener.html size="M5" variant="t-nut" %} across all three.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-parts/bottom-interface-step4-hex-frame-overview-full-bab24577ff64.jpg" alt="Top-down view of the assembled hexagonal layer frame with three Lazy Susan extrusion mounts fitted at alternating spokes">
    <figcaption>All three mounts, fitted around the ring. The frame is off the machine here, not in its built orientation. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-parts/bottom-interface-step4-hex-frame-corner-full-1a86a71db08d.jpg" alt="Closer view of one Lazy Susan extrusion mount fitted at a corner of the hexagonal layer frame">
    <figcaption>One mount, closer in. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The bearing stack from steps 1-3 now sits on the three mounts, ready for the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}). With a funnel fitted, it lands level with the bin entrances.
