---
layout: default
title: Install the bins
type: how-to
section: hardware
slug: assembly-install-bins
kicker: Assembly — Install the bins
lede: The bins that catch what the chutes drop, and the two ways to get them.
permalink: /hardware/assembly/install-bins/
og_image: https://assets.basically.website/sorter-docs/install-bins-printed-bins-from-above-w1600-3edc30bd133f.jpg
author: spencer
contributors: [brickcyclealice, daddyosbricksbill]
tools_needed: ["Hot glue gun, for cardboard bins", "Laser cutter, or a cutting service, for cardboard bins"]
warning: >-
  **AI-generated first draft.** Written from the parts catalog, the bin generator and
  what builders have posted, not from an actual build. No step here has been checked
  against a machine. Correct it as you build.
parts_needed:
  - part: bin-half-left
    qty: 6
  - part: bin-half-right
    qty: 6
  - part: bin-third-left
    qty: 6
  - part: bin-third-center
    qty: 6
  - part: bin-third-rightback
    qty: 6
---

Bins go in last, after the electronics, so the chutes can be connected and their movement tested with the bays still empty. Nothing here is fastened: each bin drops into its bay and is held by the [bin retainers]({{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }}) that are already bolted to the frame.

The list above is per layer, and a layer takes **one** of the two sets, not both. Which set depends on the size of that layer's funnel, which is step 1.

{% include step.html n="1" title="Check which set each layer takes" %}

Each layer takes the set that matches the funnel already fitted to it.

- **A half-size layer** takes **12 bins**: 6 Bin (half, left) and 6 Bin (half, right).
- **A third-size layer** takes **18 bins**: 6 each of Bin (third, left), Bin (third, center) and Bin (third, right-back).

One set per bay, six bays around the hexagon. A machine can mix the two sizes, in any order up the stack.

Changing a layer to the other size at this point means printing a new funnel as well as new bins. [Funnel brackets]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}) is where that choice is made.

{% include step.html n="2" title="Get the bins: print them or cut them" %}

Both are real options and the machine holds them identically.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/install-bins-printed-bins-loaded-stack-w1600-bf2746b86680.jpg" alt="A five layer distribution stack on casters, every bay filled with blue 3D printed bins: three across on the top two layers, two across on the bottom three">
    <figcaption>Printed bins. This machine mixes the sizes: third size on the top two layers, half size on the bottom three. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/install-bins-cardboard-bins-tower-full-97d68e720775.jpg" alt="A bin tower on castors under its plywood deck, five layers of folded cardboard bins with sorted LEGO in them">
    <figcaption>Laser cut cardboard bins, on the same frame. <cite>Photo: Basically.</cite></figcaption>
  </figure>
</div>

**Printed.** The five parts above, on the [parts calculator](https://parts-calculator.basically.website/), STLs and all, printed the same way as everything else ([Printing the parts]({{ '/hardware/printing/' | relative_url }})). Budget for them: a half set is about 2.1 kg of filament and 55 hours of printing per layer, a third set about 2.1 kg and 60 hours, so a five layer machine is roughly 10 kg of filament and about 300 hours of printing in bins alone. That is the single biggest print on the machine.

**Laser cut cardboard.** The bins were designed to be cut flat and folded, for cost and because pre-made boxes in the sizes needed ship mostly air. Cut them with the [laser cut bin generator](https://bin-gen.basically.website/), which turns a bin into a foldable flat pattern:

- It ships **built-in bins**, so you do not need a CAD file to use it. Drag in your own `.step` only if you have modified a bin.
- Set **thickness** to your stock. 1/8 inch cardboard is 3.175 mm, which is the default.
- Leave **kerf compensation** on, so the finger joints come out the size they were drawn.
- Export **SVG or DXF** to hand to somebody else's laser, or the LightBurn file if you are driving your own.
- The pattern comes out in three line colours, and the order you cut them in matters: **green first, then blue, then red**. Green is the fold score and only goes through the first outside wall of the corrugation, so it has to be cut while the sheet is still whole, and the green side has to be face up. Blue perforations and red outlines are both full through cuts.

**No laser of your own.** A makerspace or an online laser cutting service will cut the sheets from the exported file. Each bin is one connected piece and cannot be split across two smaller sheets, so give them the size up front: on the default 3.175 mm stock a half-size bin's flat pattern is about 410 x 390 mm, and the largest of the three third-size ones about 345 x 300 mm.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Glue the corners of a cardboard bin. The folded finger joints on their own do not hold in corrugated stock: most of the volume is air, so a finger usually lands on two paper walls with nothing between them. Hot glue is what the bins at Basically are held together with.</p>
</div>

{% include step.html n="3" title="Drop them in" %}

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/install-bins-cardboard-bins-in-frame-w1600-e85d2a93cc70.jpg" alt="A layer seen from floor level, filled with folded cardboard bins radiating out from the chute in the middle">
  <figcaption>A finished layer, seen from below. Photographed on an early build, so the frame around the bins is an older revision. <cite>Photo: Spencer.</cite></figcaption>
</figure>

Work around one layer at a time. Each bin sits in its bay with the wide open mouth facing outward and the narrow end toward the middle of the machine, resting on the frame, with its front edge behind the Bin retainer (left) and Bin retainer (right) on the front face of that bay's A extrusion. The retainers bolt to the frame and not to the bin, which is why cardboard and printed bins are held the same way and why swapping one for the other later costs nothing.

**A printed bin does not just sit behind the rail, it keys into it.** The inner face of a retainer carries seven teeth just below its top edge, and the lower front edge of a printed bin is castellated to match, so a bin dropped into its bay lands with its notches over those teeth and is located along the rail rather than free to slide.

Push each bin fully back until it seats. If a printed bin stands proud, it is sitting on a tooth rather than over one: lift it and drop it again.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/install-bins-bin-retainer-teeth-w1600-0ee7c319295d.jpg" alt="Close-up of two bin retainer rails: the upper bin is seated with its castellated front edge meshed into the rail, the lower bin is lifted clear so the rail's own teeth are visible">
  <figcaption>The joint, seen at one corner. The upper bin is seated and its castellations are over the rail's teeth; the lower bin is lifted clear so the teeth show. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
</figure>

If the retainers are not on the frame yet, they go on first: 6 of each per layer, 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} each, into T-nuts fitted at that step. That step is on [Bin retainers]({{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }}).

{% include step.html n="4" title="Check the funnel clears every bin" %}

The funnel lands right at the bin entrances by design, so there is very little gap for a piece to escape through, and very little room for a bin that is sitting proud of its bay. Before running the machine, turn the chute stack by hand to each of its limits in turn and watch that nothing touches. You will feel the chute stepper resisting; it should still turn smoothly against that. If a bin touches, push it fully back into its bay and turn again.

## The finished result

Every bay on every layer loaded, and the chute turning clear of all of them.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/install-bins-printed-bins-from-above-w1600-3edc30bd133f.jpg" alt="A loaded distribution stack seen from above and to one side, five layers of blue printed bins radiating out around the corner column, casters on the floor below">
  <figcaption>Every bay on every layer loaded. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
</figure>

With the bins in, the hardware is finished. Continue to [Software setup]({{ '/hardware/software-setup/' | relative_url }}), which is where the machine is told how many bins each layer has and where they are.
