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
contributors: [barthel]
parts_needed:
  - part: stator
    qty: 1
  - part: nema-bracket
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
    qty: 4
  - part: scr-m3-16-shcs
    qty: 3
  - part: scr-m3-8-cs
    qty: 5
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>AI-generated first draft.</strong> Written from the machine assembly tree in the <a href="https://parts-calculator.basically.website/assembly?focus=c-channel">parts calculator</a>, not from an actual build. No step here has been checked against a machine. Correct it as you build.</p>
</div>

A C-channel is one drive unit: a stator, the NEMA bracket bolted under it, a gear train, and a NEMA 17 stepper.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **Build 4 per machine**, three in the feeder and one for the classification channel.
- The rotor is **not** part of this unit, because it differs by where the C-channel goes: the three feeder channels take the faceted rotor, the classification channel takes the finned one. Colour differs too, the feeder parts are charcoal and the classification-channel parts are ash grey.
- No heat inserts on this assembly. The screws thread into the printed parts and into the stepper's own tapped holes.
- Two of the four channels also carry a light post, whose screws belong to the light post rather than to the list above.

{% include step.html n="1" title="Press the gear bearings" %}

Press a 6806-2RS bearing into the Output gear (130T) and a 608-2RS bearing into the Idler gear (24T). Both are press fits, no screws and no adhesive.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Bolt the NEMA bracket to the stator" %}

Fasten the NEMA bracket to the underside of the stator with 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws.

{% include step.html n="3" title="Mount the stepper" %}

Fasten the NEMA 17 to the NEMA bracket with 3 {% include fastener.html size="M3" variant="socket" length="16" %} screws. Three, not four: one corner of the motor face is left free.

Fit the Input gear (12T, screw) onto the motor shaft. It has a vertical screw hole for the grub screw that clamps it to the flat of the shaft.

{% include step.html n="4" title="Fit the gear train and the output gear" %}

Set the Idler gear (24T) between the input gear and the output gear, then attach the Output gear (130T) to the rotor with 5 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws.

Turn the stage by hand before wiring it. The train should run without a tight spot anywhere in a full revolution.

{% include step.html n="5" title="Fit the light post, on the channels that take one" %}

Two of the C-channels carry a light post, which bolts to this unit's NEMA bracket with 2 {% include fastener.html size="M3" variant="countersunk" length="20" %} screws that thread straight into the printed post.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The C-channel COB light boards need a current-limiting resistor.</b> <b>220&#8486;, 1/4 W, in series, one per board.</b> Wired straight to 24V a 50 mm COB plate pulls about 0.5A and melts its printed mount. A board fed from a basically board v1.3 LED header already has one on the board. Full detail: <a href="{{ '/hardware/electronics/#43--leds-from-basically-board-v13' | relative_url }}">LEDs, on the wire harness page</a>.</p>
</div>

Once all four are built, see [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for how they sit together.
