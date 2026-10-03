---
layout: default
title: Control board housing
type: how-to
section: hardware
slug: electronics-control-board-housing
kicker: Electronics — Control board housing
lede: Closing the control board into its printed housing, with the 40 mm fan on a GPIO-controlled port and the reset plunger in its lid.
permalink: /hardware/electronics/installation/control-board-housing/
author: spencer
og_image: https://assets.basically.website/sorter-docs/assembly-control-board-housing-housing-angled-w1600-d8c3ed33682d.jpg
warning: >-
  **AI-generated first draft.** Steps 1, 2 and 5 are photographed from a build. Nobody has printed
  the cover, the plunger or the fan retainers yet, so steps 3, 4, 6 and 7 are written from the
  models, and the pictures in them are renders.
tools_needed: ["Hex keys, 2 mm and 2.5 mm", "Soldering iron or heat-set insert press"]
parts_needed:
  - part: ctrl-board-housing-base
    qty: 1
  - part: ctrl-board-housing-cover
    qty: 1
  - part: ctrl-board-housing-plunger
    qty: 1
  - part: ctrl-board-housing-plunger-retainer
    qty: 1
  - part: ctrl-board-housing-fan-retainer
    qty: 2
  - part: fan-40mm-24v
    qty: 1
  - part: hsi-m3
    qty: 8
  - part: scr-m3-6-bhcs
    qty: 4
  - part: scr-m3-12-cs
    qty: 4
  - part: scr-m3-8-cs
    qty: 6
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Prepare the control board before you start.</strong> The five stepper drivers, the Pico and the ten jumpers all go in while the board is loose. <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a> does that; step 2 here screws the finished board down.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-control-board-prep-all-jumpers-fitted-w1600-f470f24a8913.jpg" alt="Top-down view of the fully populated control board, with five TMC2209 drivers, the Raspberry Pi Pico, and ten yellow jumpers fitted across the MS1 and MS2 headers">
    <figcaption>The board as step 2 needs it. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

Eight screws go into the base: four hold the board down, four close the cover over it.

{% include step.html n="1" title="Preparation" %}

Press 8 M3 inserts into the base while it is loose: four on the inner bosses for the board, four at the corners for the cover. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}). Nothing else takes one.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Control Board Housing base:</strong> 8 × M3</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-base-inserts-w1600-b45ee1e919a8.jpg" alt="The printed housing base seen from above, showing the large honeycomb vent in its floor and eight brass M3 heat inserts, four on raised bosses inside and four at the outer corners">
    <figcaption>Four inside, four at the corners. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

{% include step.html n="2" title="Screw the board to the base" %}

Sit the board on the four inner bosses and fix it with 4 {% include fastener.html size="M3" variant="button" length="6" %} screws. No standoffs: the bosses are the standoffs.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-board-on-base-crop-full-8ca7e7615927.jpg" alt="The populated control board screwed flat onto the printed base, its two extrusion clamp bosses at the bottom edge">
    <figcaption>The board down on the four inner bosses. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Fit the fan inside the cover" %}

Turn the cover upside down. The fan sits over the honeycomb vent and two printed retainers hold it there, one at each end of the fan.

<ol class="numbered-steps">
  <li>Lay the fan over the vent, label facing into the enclosure so it blows inwards.</li>
  <li>Lay a retainer across each end of the fan, pegs down, so its two pegs drop into the fan's corner holes. Each retainer lands on two of the cover's four posts.</li>
  <li>Screw each retainer down into its two posts with 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws. Drive all four by hand and stop as soon as the retainer is flat on its posts: they cut their own thread in the plastic.</li>
  <li>Route the fan's lead to the cutout in the corner of the cover.</li>
</ol>

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-fan-retainers-render-full-0d2aaecf74c2.png" alt="Render of the inside of the cover with both fan retainers in colour, each lying across the honeycomb vent on two posts with a countersunk screw hole at either end">
    <figcaption>Both retainers on their posts, one at each end of the fan. The fan goes between them and the lid and is not drawn. <cite>Rendered from the parts' own geometry in assembly position, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="4" title="Fit the plunger and its retainer" %}

The plunger lands on the board's reset button, so the button can be pressed with the housing shut. Drop it through the slot from the outside of the cover, then hold it in with the retainer on 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} self-tapping screws. It should slide freely and fall back on its own.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-plunger-retainer-render-full-8bfb22be786a.png" alt="Render of the inside of the cover with the plunger in colour standing up through its slot and the retainer in a second colour screwed down over it on two countersunk screws">
    <figcaption>The plunger (orange) through the slot, the retainer (blue) holding it in. <cite>Rendered from the parts' own geometry in assembly position, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="5" title="Plug the fan into a GPIO-controlled port" %}

The fan runs off one of the board's four LED ports. The red wire goes to `+V`.

<dl class="spec-list">
  <dt>LED_0_1, LED_0_2</dt><dd>GPIO1 (output channel 0)</dd>
  <dt>LED_1_1, LED_1_2</dt><dd>GPIO6 (output channel 1)</dd>
</dl>

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-fan-into-led-port-w1600-cfd2665dc48e.jpg" alt="Looking down through the cover's corner cutout at the board below, where the fan's red and black lead is plugged into the two-pin connector silkscreened LED_1_2, with Controlled by GPIO6 printed beside it">
    <figcaption>Into LED_1_2, driven by GPIO6. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Double check the port's bypass jumper is bridged.</b> Each port feeds +V through a 180 Ω resistor meant for a COB LED board, and with it still in circuit the fan will barely turn, if it turns at all, because most of the 24 V drops across the resistor instead of reaching the fan. All four are bridged in <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">preparing the control board</a>, step 4; look for solder across the two pads marked <b>Bypass R21</b>, <b>R22</b>, <b>R27</b> or <b>R28</b> beside the port you used, and do it now if it is missing, before the board goes in.</p>
</div>

{% include step.html n="6" title="Close the housing" %}

Lower the cover on, keeping the fan lead clear of the board, and fix it with 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws into the corner inserts. The stepper connectors stay reachable through the bays in the wall.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-cover-exploded-render-full-5d0521ea9e1e.png" alt="Render of the cover lifted off the base, showing which way round it goes on: the honeycomb vent and logo on the lid, the four corner screw holes over the base's four corner inserts, and the stepper bays over the connector edge">
    <figcaption>Which way round the cover goes on. Its four corner holes land on the base's four corner inserts. <cite>Rendered from the parts' own geometry in assembly position, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="7" title="Check the reset plunger" %}

Press the plunger on the lid. Its head sits just below the surface, so it takes a fingertip pressed into the recess. You should hear the button click.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-plunger-section-render-full-f69f823f6898.png" alt="Section through the closed housing at the plunger: the plunger passes down through the lid with its head ending below the lid's outer surface, and the retainer holds it in its slot">
    <figcaption>The closed housing cut through the plunger: the head (orange) ends just below the lid's surface, the retainer (blue) holds it in its slot, and its foot reaches down to where the board's reset button sits. The board is not drawn. <cite>Rendered from the parts' own geometry in assembly position, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

## The finished result

The housing closed, with the fan and the reset plunger in the cover and the stepper connectors still reachable through the bays in the wall.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-housing-angled-w1600-d8c3ed33682d.jpg" alt="The finished housing at an angle, showing the honeycomb vent and basically logo on the lid, the square plunger head in the lid surface, and the bays along the right edge that expose the stepper connectors">
  <figcaption>The closed housing, from above and to one side. <cite>Photo: Spencer.</cite></figcaption>
</figure>

**Bolting it to the frame is on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }})**, once all three enclosures are built.

Next: [preparing the Orange Pi]({{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}).
