---
layout: default
title: Channel core
type: how-to
section: hardware
slug: assembly-channel-core
kicker: Feeder — Channel core
lede: The drive under every C-channel, from the stator down to the stepper.
permalink: /hardware/assembly/feeder/c-channels/channel-core/
author: spencer
contributors: [barthel, brickcyclealice, christoph, danny]
og_image: https://assets.basically.website/sorter-docs/assembly-channel-core-single-top-full-6dbc4b7bb3a0.jpg
warning: >-
  **This page comes from a build**, the order of operations and the photographs are
  BrickCycleAlice's, apart from step 2's, which are Danny's. What goes on top of the core
  differs by channel and is on the four channel pages.
parts_needed:
  - part: stator
    qty: 1
  - part: nema-bracket
    qty: 1
  - part: idler-gear
    qty: 1
  - part: input-gear
    qty: 1
  - part: motor-nema17
    qty: 1
  - part: brg-608-2rs
    qty: 1
  - part: scr-m3-16-cs
    qty: 5
  - part: scr-m3-12-cs
    qty: 2
  - part: scr-m3-8-cs
    qty: 1
---

The channel core is a C-channel with nothing on top of it: the stator, the NEMA bracket underneath it, and the gear train the stepper drives. It is what a rotor turns in.

**The parts list above is one core's worth. Build four**, three for the feeder and one for the classification channel. Nothing on this page changes between them, so build all four at once and finish each one on its own page afterwards.

{% include fastener-legend.html %}

- **The charcoal parts are the gear train and one bracket.** The idler and input gears follow the feeder colour, which is charcoal by default and yours to change on the [parts calculator](https://parts-calculator.basically.website/assembly?focus=c-channel). Of the four NEMA brackets, C1's is charcoal and C2 to C4's are ash grey. The stator prints ash grey on all four.
- The rotor, the 130T output gear and the 6806 bearing are **not** on this page. They are one sub-assembly per channel, and which rotor you use is what makes a channel C1, C2, C3 or the classification channel.

{% include step.html n="1" title="Preparation" %}

**No heat inserts on this assembly.** Every screw threads straight into printed plastic, except the three that go into the stepper's own tapped holes. This was confirmed on a built channel and matches the part STLs: the stator's holes are Ø2.4 and Ø2.8 mm, all thread-forming, while the NEMA bracket is Ø3.4 mm clearance throughout, with nothing threaded in it. Because you're cutting your own threads in plastic, stop as soon as the screw seats, don't keep tightening.

Press the bearing into the idler gear first, while the part is loose and you can support it on the bench. It is a press fit: no screws, no adhesive, no heat.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Idler gear (24T):</strong> one 608-2RS bearing.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-idler-gear-bearing-pressed-w1600-77f822b4b777.jpg" alt="The 24-tooth idler gear with a black-sealed 608 bearing pressed into its centre, seen from above">
    <figcaption>The idler gear with its 608 in. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="2" title="Fit the input gear to the motor shaft" %}

The Input gear (12T, screw) takes its {% include fastener.html size="M3" variant="countersunk" length="8" %} clamping screw **parallel to the shaft, alongside the bore**, not radially into the side of the boss. The hole runs the full length of the gear, 3.6 mm off the axis, and breaks into the Ø4.9 mm bore along the way, so the screw ends up bearing on the flat of the NEMA 17's shaft.

The bore is plain and round, so there is nothing to key it: turn the gear until that hole lines up with the flat on the shaft, push the gear all the way on, then tighten the screw down onto the flat. The head drops into a counterbore in the toothed end face. Tighten until the head is seated and the gear does not turn on the shaft, and no further, it is threading into plastic.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-input-gear-clamp-screw-driving-w1600-dfa74d5a362c.jpg" alt="The charcoal 12-tooth input gear pushed onto the shaft of a NEMA 17, seen from above. A driver bit is turning the clamping screw, which stands in a hole in the end face beside the bore with its thread still showing. The flat on the motor shaft is visible through the bore next to it">
    <figcaption>The screw goes in beside the bore, parallel to the shaft, not into the side of the gear. The bright shape next to it is the flat on the shaft. <cite>Photo: Danny.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-input-gear-clamp-screw-seated-w1600-39abf5a9ff47.jpg" alt="The same gear and motor with the clamping screw driven fully home, its head sitting down in the round counterbore in the toothed end face, and the gear seated against the front face of the motor">
    <figcaption>Tightened. The head sits down in the counterbore and the gear is pushed all the way onto the shaft. <cite>Photo: Danny.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Fit the idler gear and the stepper to the NEMA bracket" %}

Drop the Idler gear (24T) onto its post on the NEMA bracket **with the bearing facing up**.

Then fasten the NEMA 17 to the bracket with 3 {% include fastener.html size="M3" variant="countersunk" length="16" %} screws. Three, not four: one corner of the motor face is left free. The input gear meshes with the idler as the motor goes down.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-idler-gear-and-motor-on-nema-bracket-w1600-dfefb06e2166.jpg" alt="The three-armed grey NEMA bracket seen from above, with the 24-tooth idler gear sitting on its post with the 608 bearing uppermost, the stepper motor bolted to the outer end of the bracket, and the raised hub at the centre of the bracket">
  <figcaption>Idler on its post, bearing up, with the stepper bolted on beside it. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-step4-mounting-face-w1600-5f972ded599d.jpg" alt="Close view of the grey NEMA bracket, two countersunk screws driven near the edge with further mounting holes beside them">
  <figcaption>Closer on the NEMA bracket, two screws home. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="4" title="Mount the bracket under the stator" %}

Fasten the NEMA bracket to the underside of the stator with 4 screws, in two lengths. The two at the tips of the narrow arms take an {% include fastener.html size="M3" variant="countersunk" length="12" %} screw. The two on the wide plate the stepper sits on take an {% include fastener.html size="M3" variant="countersunk" length="16" %} instead, because the bracket is thicker at those two and a 12 mm barely bites.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-bracket-under-stator-w1600-c45a38f08e69.jpg" alt="The stator ring seen from underneath with the three-armed NEMA bracket fastened across it, each arm reaching the rim">
  <figcaption>The bracket on the underside of the stator, arms out to the rim. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

Turn the idler by hand. It should spin freely on its post and drive the input gear without a tight spot.

## The finished result

A stator with the bracket, gear train and stepper under it, and an empty hub in the middle waiting for a rotor. Build four.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-channel-core-single-top-full-6dbc4b7bb3a0.jpg" alt="A single C-channel core seen from above: the stator ring with its exit opening, the three-armed NEMA bracket fastened across it, the raised hub at its centre and the stepper motor on the far side, with no rotor fitted">
  <figcaption>One finished core from the top, no rotor in it. The opening in the stator wall is the channel's exit. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

## Next steps

Finish each core as the channel it is going to be:

- **[Bulk channel (C1)]({{ '/hardware/assembly/feeder/c-channels/bulk-channel/' | relative_url }})**, the faceted rotor and the Bulk cap.
- **[Feeder channels (C2 and C3)]({{ '/hardware/assembly/feeder/c-channels/feeder-channels/' | relative_url }})**, the faceted rotor, an output guide and a camera lamp.
- **[Classification channel (C4)]({{ '/hardware/assembly/feeder/c-channels/classification-channel/' | relative_url }})**, the finned rotor, its cap and a camera lamp with the 4K module.
