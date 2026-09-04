---
layout: default
title: C-channel
type: how-to
section: hardware
slug: assembly-c-channel
kicker: Feeder — C-channel
lede: The C-channel stage itself.
permalink: /hardware/assembly/feeder/c-channel/
author: spencer
contributors: [barthel, brickcyclealice, christoph]
warning: >-
  **Steps 1 to 5 come from a build**, the order of operations and the photographs are
  BrickCycleAlice's. Step 6, the camera lamp, is still an AI-generated first draft written
  from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=c-channel) and has
  not been checked against a machine. Correct it as you build.
parts_needed:
  - part: stator
    qty: 4
  - part: nema-bracket
    qty: 4
  - part: rotor-faceted
    qty: 3
  - part: rotor-finned
    qty: 1
  - part: output-gear
    qty: 4
  - part: idler-gear
    qty: 4
  - part: input-gear
    qty: 4
  - part: motor-nema17
    qty: 4
  - part: brg-6806-2rs
    qty: 4
  - part: brg-608-2rs
    qty: 4
  - part: scr-m3-12-cs
    qty: 40
  - part: scr-m3-16-cs
    qty: 12
  - part: scr-m3-8-cs
    qty: 4
---

A C-channel is one drive unit: a rotor turning inside a stator, driven through a gear train by a NEMA 17 stepper on a bracket underneath.

The parts list above is **all four channels' worth** — the count is fixed for every machine, so there's nothing to multiply yourself. The steps below build one channel at a time; repeat each step four times, using the per-step counts as what one repetition uses.

{% include fastener-legend.html %}

- **Build 4 per machine**, three in the feeder and one for the classification channel. It is the same build four times over, and the rotor is the only thing that changes.
- **One rotor per unit, and only one of the two.** The three feeder channels take the Rotor (faceted); the classification channel takes the Rotor (finned), the one with the fins in the photographs below. The list above already splits them the way a real machine needs them: three faceted, one finned. Colour does not change with the rotor: both print ash grey, as do the stator and the output guide, on all four channels.
- Every channel also carries a [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}), whose parts and screws belong to that page rather than to the list above.
- **The charcoal parts are the gear train and one bracket.** The output, idler and input gears follow the feeder colour, which is charcoal by default and yours to change on the [parts calculator](https://parts-calculator.basically.website/assembly?focus=c-channel). Of the four NEMA brackets, C1's is charcoal and C2 to C4's are ash grey.

{% include step.html n="1" title="Preparation" %}

**No heat inserts on this assembly.** Every screw threads straight into printed plastic, except the three that go into the stepper's own tapped holes. This was confirmed on a built channel and matches the part STLs: the rotor's six holes are Ø2.8 mm and the stator's are Ø2.4 and Ø2.8 mm, all thread-forming, while the NEMA bracket and the output gear are Ø3.4 mm clearance throughout, with nothing threaded in them. Because you're cutting your own threads in plastic, stop as soon as the screw seats — don't keep tightening.

Press both bearings into their gears first, while the parts are loose and you can support them on the bench. Both are press fits: no screws, no adhesive, no heat.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Output gear (130T):</strong> one 6806-2RS bearing, 30 mm bore.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Idler gear (24T):</strong> one 608-2RS bearing.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

{% include step.html n="2" title="Bolt the output gear to the rotor" %}

Bolt the Output gear onto the underside of the rotor with 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, one at the outer end of each spoke, seated flush in the countersinks. The six holes are 60° apart on a 90 mm bolt circle. The pattern is symmetric, so any of the six rotations works, but the gear can only be fitted right-side up.

**Use the 12 mm, not the 8 mm.** The gear is 8 mm thick at the bolt circle, and a countersunk screw's length is measured over its head, so an M3 × 8 seated flush in the countersink finishes level with the top of the gear and never enters the rotor at all. The 12 mm leaves 4 mm of thread in the rotor's 5 mm flange and stops short of breaking through the far side.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bolted-to-rotor-w1600-7ca0b30ba41a.jpg" alt="The grey 130-tooth output gear with a black-sealed 6806 bearing pressed into its centre, bolted onto a white rotor behind it, with a countersunk screw at the outer end of each of the six spokes">
  <figcaption>Output gear, bearing pressed in, bolted to a rotor. Six screws, one per spoke. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Fit the input gear to the motor shaft" %}

The Input gear (12T, screw) has a hole through its boss, parallel to the shaft, for the {% include fastener.html size="M3" variant="countersunk" length="8" %} screw that clamps it on. The bore is plain and round, so there is nothing to key it: turn the gear until that screw lines up with the flat on the NEMA 17's shaft, push the gear all the way on, then tighten the screw down onto the flat.

The head drops into a counterbore in the boss. Tighten until the head is seated and the gear does not turn on the shaft, and no further, it is threading into plastic.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-input-gear-on-motor-shaft-w1600-be00a0374988.jpg" alt="A black NEMA 17 stepper motor lying on its side with the small grey 12-tooth input gear pushed fully onto its shaft, the clamping screw visible in the side of the gear boss">
  <figcaption>Pushed fully onto the shaft, clamp screw bearing on the flat. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="4" title="Fit the idler gear and the stepper to the NEMA bracket" %}

Drop the Idler gear (24T) onto its post on the NEMA bracket **with the bearing facing up**.

Then fasten the NEMA 17 to the bracket with 3 {% include fastener.html size="M3" variant="countersunk" length="16" %} screws. Three, not four: one corner of the motor face is left free. The input gear meshes with the idler as the motor goes down.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-idler-gear-and-motor-on-nema-bracket-w1600-dfefb06e2166.jpg" alt="The three-armed grey NEMA bracket seen from above, with the 24-tooth idler gear sitting on its post with the 608 bearing uppermost, the stepper motor bolted to the outer end of the bracket, and the raised hub at the centre of the bracket">
  <figcaption>Idler on its post, bearing up, with the stepper bolted on beside it. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="5" title="Mount the stator, then drop in the rotor" %}

Fasten the NEMA bracket to the underside of the stator with 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws.

Then lower the rotor, output gear and all, onto the raised hub in the middle of the bracket, so the 130T comes down into mesh with the idler.

Turn the stage by hand before wiring it. The train should run without a tight spot anywhere in a full revolution.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
  <figcaption>The finished stage, here the classification one with the finned rotor. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="6" title="Hang the camera lamp over the channel" %}

Every channel carries a camera lamp: an arm mounted to the channel, a shaded lamp on the end of it and a camera looking down through the middle. It has its own page, [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}), and none of its screws are in the list above.

The light post and the overhead camera mount that used to do this job were retired on 2026-09-02. Their pages are still up for machines already built that way.

Once all four are built, see [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for how they sit together.
