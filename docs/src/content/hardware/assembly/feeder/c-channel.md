---
layout: default
title: C-Channel
type: how-to
section: hardware
slug: assembly-c-channel
kicker: Feeder — C-Channel
lede: The C-channel stage itself.
permalink: /hardware/assembly/feeder/c-channel/
author: spencer
contributors: [barthel, brickcyclealice, christoph]
warning: >-
  **Steps 1 to 5 come from a build**, the order of operations and the photographs are
  BrickCycleAlice's. Step 6, the light post, is still an AI-generated first draft written
  from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=c-channel) and has
  not been checked against a machine. Correct it as you build.
parts_needed:
  - part: stator
    qty: 1
  - part: nema-bracket
    qty: 1
  - part: rotor-faceted
    qty: 1
  - part: rotor-finned
    qty: 1
  - part: output-gear
    qty: 1
  - part: idler-gear
    qty: 1
  - part: input-gear
    qty: 1
  - part: motor-nema17
    qty: 1
  - part: brg-6806-2rs
    qty: 1
  - part: brg-608-2rs
    qty: 1
  - part: scr-m3-12-cs
    qty: 10
  - part: scr-m3-16-shcs
    qty: 3
  - part: scr-m3-8-shcs
    qty: 1
---

A C-channel is one drive unit: a rotor turning inside a stator, driven through a gear train by a NEMA 17 stepper on a bracket underneath.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **Build 4 per machine**, three in the feeder and one for the classification channel. It is the same build four times over, and the rotor is the only thing that changes. **The parts list above is one unit's worth**, so multiply it by four for a whole machine, or read the machine totals off the [parts calculator](https://parts-calculator.basically.website/assembly?focus=c-channel).
- **One rotor per unit, and only one of the two.** The three feeder channels take the Rotor (faceted); the classification channel takes the Rotor (finned), the one with the fins in the photographs below. Both are listed above because either can be the one you need; across a machine it is three faceted and one finned. Colour changes with the rotor too: the feeder parts are charcoal, the classification-channel ones ash grey.
- Two of the four channels also carry a light post, whose screws belong to the light post rather than to the list above.

{% include step.html n="1" title="Preparation" %}

**No heat inserts on this assembly.** Every screw here threads straight into a printed part, except the three that go into the stepper's own tapped holes. That is how one was built, and the part STLs agree: the rotor's six holes are Ø2.8 mm and the stator's are Ø2.4 and Ø2.8 mm, all thread-forming, while the NEMA bracket and the output gear are Ø3.4 mm clearance throughout with nothing threaded in them.

**Press both bearings into their gears first**, while the parts are loose and you can support them on the bench.

- **Output gear (130T):** one 6806-2RS, 30 mm bore.
- **Idler gear (24T):** one 608-2RS.

Both are press fits. No screws, no adhesive, no heat.

{% include step.html n="2" title="Bolt the output gear to the rotor" %}

Bolt the Output gear onto the underside of the rotor with 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, one at the outer end of each spoke, seated flush in the countersinks. The six holes are 60° apart on a 90 mm bolt circle, so the gear only goes on one way up.

**Use the 12 mm, not the 8 mm.** The gear is 8 mm thick at the bolt circle, and a countersunk screw's length is measured over its head, so an M3 × 8 seated flush in the countersink finishes level with the top of the gear and never enters the rotor at all. The 12 mm leaves 4 mm of thread in the rotor's 5 mm flange and stops short of breaking through the far side.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bolted-to-rotor-w1600-7ca0b30ba41a.jpg" alt="The grey 130-tooth output gear with a black-sealed 6806 bearing pressed into its centre, bolted onto a white rotor behind it, with a countersunk screw at the outer end of each of the six spokes">
  <figcaption>Output gear, bearing pressed in, bolted to a rotor. Six screws, one per spoke.</figcaption>
</figure>

{% include step.html n="3" title="Fit the input gear to the motor shaft" %}

The Input gear (12T, screw) has a hole through its boss, parallel to the shaft, for the {% include fastener.html size="M3" variant="socket-button" length="8" %} screw that clamps it on. The bore is plain and round, so there is nothing to key it: turn the gear until that screw lines up with the flat on the NEMA 17's shaft, push the gear all the way on, then tighten the screw down onto the flat.

The head drops into a counterbore in the boss. Tighten until the head is seated and the gear does not turn on the shaft, and no further, it is threading into plastic.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-input-gear-on-motor-shaft-w1600-be00a0374988.jpg" alt="A black NEMA 17 stepper motor lying on its side with the small grey 12-tooth input gear pushed fully onto its shaft, the clamping screw visible in the side of the gear boss">
  <figcaption>Pushed fully onto the shaft, clamp screw bearing on the flat.</figcaption>
</figure>

{% include step.html n="4" title="Fit the idler gear and the stepper to the NEMA bracket" %}

Drop the Idler gear (24T) onto its post on the NEMA bracket **with the bearing facing up**.

Then fasten the NEMA 17 to the bracket with 3 {% include fastener.html size="M3" variant="socket-button" length="16" %} screws. Three, not four: one corner of the motor face is left free. The input gear meshes with the idler as the motor goes down.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-idler-gear-and-motor-on-nema-bracket-w1600-dfefb06e2166.jpg" alt="The three-armed grey NEMA bracket seen from above, with the 24-tooth idler gear sitting on its post with the 608 bearing uppermost, the stepper motor bolted to the outer end of the bracket, and the raised hub at the centre of the bracket">
  <figcaption>Idler on its post, bearing up, with the stepper bolted on beside it.</figcaption>
</figure>

{% include step.html n="5" title="Mount the stator, then drop in the rotor" %}

Fasten the NEMA bracket to the underside of the stator with 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws.

Then lower the rotor, output gear and all, onto the raised hub in the middle of the bracket, so the 130T comes down into mesh with the idler.

Turn the stage by hand before wiring it. The train should run without a tight spot anywhere in a full revolution.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
  <figcaption>The finished stage, here the classification one with the finned rotor.</figcaption>
</figure>

{% include step.html n="6" title="Fit the light post, on the channels that take one" %}

Two of the C-channels carry a light post, which bolts to this unit's NEMA bracket with 2 {% include fastener.html size="M3" variant="countersunk" length="20" %} screws that thread straight into the printed post.

The post, its cap, the cap adapter and the COB plate have their own page: [light post]({{ '/hardware/assembly/feeder/light-post/' | relative_url }}).

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The C-channel COB light boards need a current-limiting resistor.</b> <b>220&#8486;, 1/4 W, in series, one per board.</b> Wired straight to 24V a 50 mm COB plate pulls about 0.5A and melts its printed mount. A board fed from a basically board v1.3 LED header already has one on the board. Full detail: <a href="{{ '/hardware/electronics/#43--leds-from-basically-board-v13' | relative_url }}">LEDs, on the wire harness page</a>.</p>
</div>

Once all four are built, see [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for how they sit together.
