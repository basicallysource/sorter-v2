---
layout: default
title: Install the bins
type: how-to
section: hardware
slug: assembly-install-bins
kicker: Assembly — Install the bins
lede: The bins that catch what the chutes drop, and the two ways to get them.
permalink: /hardware/assembly/install-bins/
author: spencer
contributors: [brickcyclealice]
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

Bins go in last, once the tower is standing, the chutes are in and the feeder is on. Nothing here is fastened: each bin drops into its bay and is held by the [bin retainers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) that are already bolted to the frame.

The list above is per layer, and a layer takes **one** of the two sets, not both. Which one is decided by that layer's funnel, in step 1.

<div class="img-placeholder">A finished machine with all bins installed.</div>

{% include step.html n="1" title="Match the bin size to the layer's funnel" %}

The funnel and the bin set are a matched pair, chosen per layer rather than once for the whole machine, so a five layer machine can mix them. See [Funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}), which is where the choice is made before printing.

- **Funnel (half size)** → **12 bins** on that layer: 6 Bin (half, left) and 6 Bin (half, right).
- **Funnel (third size)** → **18 bins** on that layer: 6 each of Bin (third, left), Bin (third, center) and Bin (third, right-back).

Either way it is one set per bay, six bays around the hexagon. A layer built with third bins gives you more, smaller destinations; the tradeoff is that the funnel opening is smaller too, which limits the size of piece that layer can take.

{% include step.html n="2" title="Get the bins: print them or cut them" %}

Both are real options and the machine holds them identically. Printed bins are in the parts catalog and need nothing but a printer and time; cut bins are cardboard, need a laser, and are what the machine was designed around.

**Printed.** The five parts above, on the [parts calculator](https://parts-calculator.basically.website/), STLs and all. Budget for them: a half set is about 2.1 kg of filament and 55 hours of printing per layer, a third set about 2.1 kg and 60 hours, so a five layer machine is roughly 10 kg and ten days of printer time in bins alone. That is the single biggest print on the machine.

**Laser cut cardboard.** The bins were designed to be cut flat and folded, for cost and because pre-made boxes in the sizes needed ship mostly air. Cut them with the [laser cut bin generator](https://bin-gen.basically.website/), which turns a bin into a foldable flat pattern for LightBurn:

- It ships **built-in bins**, so you do not need a CAD file to use it. Drag in your own `.step` only if you have modified a bin.
- Set **thickness** to your stock. 1/8 inch cardboard is 3.175 mm, which is the default.
- Leave **kerf compensation** on, so the finger joints come out the size they were drawn.
- The pattern comes out in three line colours, and the order you cut them in matters: **green first, then blue, then red**. Green is the fold score and only goes through the first outside wall of the corrugation, so it has to be cut while the sheet is still whole, and the green side has to be face up. Blue perforations and red outlines are both full through cuts.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Glue the corners of a cardboard bin. The folded finger joints on their own do not hold in corrugated stock: most of the volume is air, so a finger usually lands on two paper walls with nothing between them. Hot glue is what the bins at Basically are held together with.</p>
</div>

{% include step.html n="3" title="Drop them in" %}

Work around one layer at a time. Each bin sits in its bay with the wide open mouth facing outward and the narrow end toward the middle of the machine, resting on the frame, with its front edge behind the Bin retainer (left) and Bin retainer (right) on the front face of that bay's A/G extrusion. The retainers bolt to the frame and not to the bin, which is why cardboard and printed bins are held the same way and why swapping one for the other later costs nothing.

If the retainers are not on the frame yet, they go on first: 6 of each per layer, 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} each, into T-nuts the hex frame already carries. That step is on [Regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}).

{% include step.html n="4" title="Check the funnel clears every bin" %}

The funnel lands right at the bin entrances by design, so there is very little gap for a piece to escape through, and very little room for a bin that is sitting proud of its bay. Before running the machine, turn the chute stack by hand through a full revolution and watch that nothing touches. A bin that is not pushed fully back is the one the funnel will hit.

With the bins in, the hardware is finished. Continue to [Software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}), which is where the machine is told how many bins each layer has and where they are.
