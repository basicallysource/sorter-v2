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
og_image: https://assets.basically.website/sorter-docs/assembly-channel-core-cutout-full-538336057944.jpg
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

The channel core is a C-channel with no rotor in it: the stator, the NEMA bracket under it, and the gear train the stepper drives.

**The parts list above is one core's worth. Build four**, three for the feeder and one for the classification channel. All four are the same. Which rotor goes in, and what hangs off it, is on the four channel pages.

{% include fastener-legend.html %}

- **Colours.** The stator is ash grey. The idler and input gears follow the feeder colour, charcoal by default. The NEMA bracket is charcoal on C1 and ash grey on the other three.

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Idler gear (24T):</strong> press the 608-2RS bearing into it. No screw, no glue, no heat.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-idler-gear-bearing-pressed-w1600-77f822b4b777.jpg" alt="The 24-tooth idler gear with a black-sealed 608 bearing pressed into its centre, seen from above">
    <figcaption>The idler gear with its 608 in. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="2" title="Fit the input gear to the motor shaft" %}

The Input gear (12T, screw) is clamped by one {% include fastener.html size="M3" variant="countersunk" length="8" %} screw that runs **parallel to the shaft, beside the bore**, not into the side of the gear.

<ol class="numbered-steps">
  <li>Turn the gear until the screw hole lines up with the flat on the motor shaft.</li>
  <li>Push the gear all the way onto the shaft.</li>
  <li>Tighten the screw down onto the flat. Its head drops into the counterbore in the toothed face.</li>
</ol>

Stop when the head is seated and the gear no longer turns on the shaft.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-input-gear-clamp-screw-driving-w1600-dfa74d5a362c.jpg" alt="The charcoal 12-tooth input gear pushed onto the shaft of a NEMA 17, seen from above. A driver bit is turning the clamping screw, which stands in a hole in the end face beside the bore with its thread still showing. The flat on the motor shaft is visible through the bore next to it">
    <figcaption>The screw goes in beside the bore, parallel to the shaft. The bright shape next to it is the flat on the shaft. <cite>Photo: Danny.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-input-gear-clamp-screw-seated-w1600-39abf5a9ff47.jpg" alt="The same gear and motor with the clamping screw driven fully home, its head sitting down in the round counterbore in the toothed end face, and the gear seated against the front face of the motor">
    <figcaption>Tightened, head down in the counterbore, gear all the way on. <cite>Photo: Danny.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Fit the idler gear and the stepper to the NEMA bracket" %}

Drop the Idler gear (24T) onto its post on the bracket, **bearing facing up**.

Fasten the NEMA 17 to the bracket with 3 {% include fastener.html size="M3" variant="countersunk" length="16" %} screws. Three, not four: one corner of the motor face is left empty. The input gear meshes with the idler as the motor goes down.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-idler-gear-and-motor-on-nema-bracket-w1600-dfefb06e2166.jpg" alt="The three-armed grey NEMA bracket seen from above, with the 24-tooth idler gear sitting on its post with the 608 bearing uppermost, the stepper motor bolted to the outer end of the bracket, and the raised hub at the centre of the bracket">
  <figcaption>Idler on its post, bearing up, stepper bolted on beside it. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-step4-mounting-face-w1600-5f972ded599d.jpg" alt="Close view of the grey NEMA bracket, two countersunk screws driven near the edge with further mounting holes beside them">
  <figcaption>Closer on the bracket, two screws home. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="4" title="Mount the bracket under the stator" %}

Fasten the bracket to the underside of the stator with 4 screws, two of each length:

- **The two narrow arm tips:** {% include fastener.html size="M3" variant="countersunk" length="12" %}.
- **The two on the wide plate under the stepper:** {% include fastener.html size="M3" variant="countersunk" length="16" %}. The bracket is thicker there and a 12 mm barely bites.

Turn the idler by hand. It should spin freely and drive the input gear with no tight spot.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-bracket-under-stator-w1600-c45a38f08e69.jpg" alt="The stator ring seen from underneath with the three-armed NEMA bracket fastened across it, each arm reaching the rim">
  <figcaption>The bracket on the underside of the stator, arms out to the rim. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

## The finished result

A stator with the bracket, gear train and stepper under it, and an empty hub in the middle waiting for a rotor. Build four.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-channel-core-cutout-full-538336057944.jpg" alt="A single C-channel core seen from above on a plain background: the stator ring with its exit opening, the three-armed NEMA bracket fastened across it, the raised hub at its centre and the stepper motor on the far side, with no rotor fitted">
  <figcaption>One finished core from the top, no rotor in it. The opening in the stator wall is the channel's exit. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

## Next steps

Finish each core as the channel it is going to be:

- **[Bulk channel (C1)]({{ '/hardware/assembly/feeder/c-channels/bulk-channel/' | relative_url }})**, the faceted rotor and the Bulk cap.
- **[Feeder channels (C2 and C3)]({{ '/hardware/assembly/feeder/c-channels/feeder-channels/' | relative_url }})**, the faceted rotor, an output guide and a camera lamp.
- **[Classification channel (C4)]({{ '/hardware/assembly/feeder/c-channels/classification-channel/' | relative_url }})**, the finned rotor, its cap and a camera lamp with the 4K module.
