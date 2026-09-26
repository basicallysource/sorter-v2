---
layout: default
title: PSU box
type: how-to
section: hardware
slug: electronics-psu-box
kicker: Electronics — PSU box
lede: The printed housing around the Mean Well LRS-350-24, its mains inlet, and the wiring inside it.
permalink: /hardware/electronics/installation/psu-box/
author: barthel
contributors: [spencer, brickcyclealice]
og_image: https://assets.basically.website/sorter-parts/meanwell-psu-housing-v2-render-full-f4b161896ea6.png
last_verified: 2026-09-26
tools_needed: ["Hex keys, 2 mm and 2.5 mm", "Screwdriver for the supply's M3.5 terminal screws", "Multimeter, with a continuity buzzer"]
parts_needed:
  - part: psu-24v-350w
    qty: 1
  - part: psu-switch-fused
    qty: 1
  - part: mains-cord-c13
    qty: 1
  - part: meanwell-psu-housing-shell-rear
    qty: 1
  - part: meanwell-psu-housing-shell-front
    qty: 1
  - part: meanwell-psu-housing-front-panel
    qty: 1
  - part: meanwell-psu-housing-lid-rear
    qty: 1
  - part: meanwell-psu-housing-lid-front
    qty: 1
  - part: scr-m4-12-cs
    qty: 4
  - part: scr-m3-12-cs
    qty: 8
  - part: scr-m3-8-cs
    qty: 2
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Make three <a href="{{ '/hardware/helpers/psu-pigtail/' | relative_url }}">PSU output pigtails</a> before you start.</strong> Each is a panel-mount barrel jack with a fork terminal crimped onto each of its two leads, and they are commonly sold with the leads already on. That page builds them; step 1 here fits and wires them.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-built-w1600-59554dc6b189.jpg" alt="An assembled PSU output pigtail: a panel-mount barrel jack with red and black 18 AWG leads, each ending in an insulated fork terminal">
    <figcaption>One finished pigtail: the jack, its red and black leads, and a fork terminal on each. <cite>Photo: Jon.</cite></figcaption>
  </figure>
</div>

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Until this box is finished it has exposed mains wiring.</b> Observe basic electrical safety precautions: do not plug a cable into the IEC inlet until the assembly is complete, the wiring is verified and both lids are on.</p>
</div>

## The five printed parts

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/psu-box-exploded-full-097445070d4d.png" alt="Exploded render of the five printed parts of the PSU housing in build order: the blue front panel at the front left, the light grey shell front module behind it, the grey shell rear tray with its honeycomb floor and vented walls, and above them the plain front lid and the vented rear lid">
  <figcaption>The five parts, in the order they go together. The blue front panel carries the mains inlet and the three jacks. The two lids screw down onto the two shells. <cite>Rendered from the parts' own STLs.</cite></figcaption>
</figure>

**Build the front panel in your hand first.** Both wiring steps are easier with it loose, and it is the last thing that goes on.

{% include step.html n="1" title="Fit and wire the three jacks" %}

Push each jack through a round hole from behind and do its nut up on the outside, finger tight. Any of the three round holes will do, and the panel itself goes in either way up.

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/psu-box-front-panel-v3-full-2fea8da2bd43.png" alt="Dimensioned drawing of the PSU housing front panel seen from outside: a landscape panel 131 by 50 mm, with three 12 mm round jack holes in a row on the left at 20 mm pitch, and on the right a 47.5 by 28 mm rectangular mains inlet cutout with a 2.8 mm screw pilot hole above it and another below it, 40 mm apart on its centreline">
  <figcaption>The front panel from outside: inlet on the right, jacks on the left. The two small holes are 2.8 mm pilots, so the inlet's screws cut their own thread in them. <cite>Drawn from the part's STL, not from a build.</cite></figcaption>
</figure>

Set the panel down beside the supply for now. The leads land on the terminal block in step 4, once the supply is in the tray.

{% include step.html n="2" title="Fit the mains inlet" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>No mains cable in the inlet.</b> Not for this step, not for any of the ones after it, and not until the box is closed and the wiring checked.</p>
</div>

The **IEC C14 inlet, switch + 10 A fuse** is the machine's mains entry and its on/off switch. Its three leads come already attached, so there is no AC cable to make.

**The cable from the wall is an ordinary IEC C13 mains lead**, the cord a desktop PC or a monitor comes with, with the plug your country uses. It is in the parts above. Three core, because the machine earths through it and out to the supply's earth screw, and 10 A or better, which matches the module's own fuse and is far more than the machine draws. It is the one part of this build most people already own, so check a drawer before buying one.

Push it into the rectangular cutout from the outside, so its flange sits flat on the outer face of the panel and its two holes line up with the panel's two small holes.

Run an {% include fastener.html size="M3" variant="countersunk" length="8" %} into each of the two holes. They are 2.8 mm pilots through the full thickness of the panel, so each screw cuts its own thread as it goes in and there is nothing to hold behind it.

Stop as soon as the flange is tight. The panel bows outward before the screw gives, so the screw will not tell you when to stop.

**If your front panel was printed before its v2**, those two holes are 3.2 mm clearance instead and a screw will turn in them without pulling the flange down. That panel takes an {% include fastener.html size="M3" variant="countersunk" length="12" %} with an {% include fastener.html size="M3" variant="nut" %} behind each, fitted while the panel is still loose, because the nuts go on the back.

{% include step.html n="3" title="Bolt the supply into the rear tray" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Set the supply's input voltage selector before it goes in the tray.</b> The LRS-350-24 is not universal input: a small slide switch on the side of its case, marked <code>115V</code> and <code>230V</code>, sets which mains voltage it runs on, and it has to match the socket the machine will be plugged into. Check which way it is set now, while the supply is loose and nothing is plugged in, and slide it across if it is wrong. Once it is bolted into the tray with both lids over it you cannot reach it. Left on 115 V and plugged into 230 V mains, the supply is destroyed the moment the rocker goes on.</p>
</div>

The supply's case has four threaded holes in its back face, and the tray's floor has four plain round holes that line up with them. Sit the supply in the tray and run 4 {% include fastener.html size="M4" variant="countersunk" length="12" %} screws up through the floor into the case.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Nothing longer than {% include fastener.html size="M4" variant="countersunk" length="12" %} here.</b> The supply's circuit board is right behind that face. If a screw stops before it pulls the supply down, back it out rather than force it.</p>
</div>

**Put the terminal-block end at the open end of the tray**, the end the front module butts up to. The other end is where the supply's own fan is, and that is the end the vented rear lid covers.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/psu-box-case-screws-v2-full-ac920db03995.png" alt="Photograph of the Mean Well LRS-350-24 seen from its back, with its four plain M4 threaded holes ringed, two at each end of the case, and the finned terminal-block end labelled">
    <figcaption>The four threaded holes on the back of the supply, and which end the terminal block is on. The hex-stamped holes beside them are the case's own screws, not these. <cite>Manufacturer photo, marked up.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/psu-box-tray-m4-full-09ec55ebc573.png" alt="Render of the shell rear tray seen from above and to one side, its honeycomb floor and vented walls visible, with the four round clearance holes the M4 screws pass through ringed">
    <figcaption>The same four, in the tray's floor. The screws go in from underneath. <cite>Rendered from the part's own STL.</cite></figcaption>
  </figure>
</div>

{% include step.html n="4" title="Land every lead on the terminal block" %}

The block is nine screws and the numbers are Mean Well's own, printed on the supply beside it.

Hold the front panel up to the open end of the tray, close enough that its leads reach, and land them all:

<ol class="numbered-steps">
  <li><b>The three pigtails</b>, one per <b>+V/-V</b> pair: <b>7 with 4, 8 with 5, 9 with 6</b>, the red terminal on the +V screw and the black on the -V screw of the same pair. Each pigtail must keep to one pair.</li>
  <li><b>The inlet's three leads</b>: <b>live on 1</b> (AC/L), <b>neutral on 2</b> (AC/N), <b>earth on 3</b>. The earth lead is the green-yellow one.</li>
</ol>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Find out which of the other two is live. Do not go by colour.</b> These modules are sold with red and blue leads and <b>both orders have been found in the post</b>, so the colour tells you nothing about which one the fuse and the switch are in. Land them the wrong way round and the machine is fused and switched in its neutral: the supply stays live with the rocker off.</p>
</div>

**The test**, with nothing plugged in: take the fuse out of its drawer, [set the meter to continuity]({{ '/hardware/helpers/multimeter/' | relative_url }}#continuity-for-tracing-a-cable), and probe from each coloured lead to each of the two flat pins inside the C14. The pair that still beeps with the fuse out is **neutral**. The one that beeps only with the fuse back in and the rocker on is **live**, because the fuse and the switch sit in the live side. That lead goes on screw 1.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/psu-box-inlet-leads-tested-w1600-152d058c81fe.jpg" alt="The Mean Well LRS-350-24 on a bench with the fused IEC inlet module beside it, its three factory leads running to the bottom three screws of the terminal block: the blue lead on the screw marked L, the red lead on N and the yellow lead on the earth symbol">
  <figcaption>One module wired after testing it: on this one the live lead turned out to be the <b>blue</b> one, so blue is on <code>L</code> and red on <code>N</code>. Another unit of the same part can be the other way round, which is the whole reason for the test. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

For each one: back the screw off a few turns, slide the fork terminal in under it, and tighten it down. Mean Well's figure for these M3.5 screws is 8 to 10 kgf&middot;cm, about 0.8 to 1.0 N&middot;m, which is firm rather than hard. Tug-test each terminal once it is down.

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/psu-box-terminal-map-full-81629ce6a8e1.png" alt="Diagram of the Mean Well LRS-350-24 seen from above, its nine-way terminal block down the left edge numbered 1 at the bottom to 9 at the top, the numbers being Mean Well's own and printed on the supply. Red leads run from screws 9, 8 and 7 and black leads from 6, 5 and 4, pairing 9 with 6, 8 with 5 and 7 with 4 into three barrel jacks labelled PJ3 to the Orange Pi buck, PJ2 to the powered USB hub, and PJ1 to the basically board. Below them the IEC C14 inlet switch module is drawn upright with its illuminated rocker, fuse drawer and C14 socket, and its three factory leads run to screws 1, 2 and 3, labelled AC/L, AC/N and earth: red to screw 1 as the live, blue to screw 2 as the neutral, and yellow to screw 3 as the earth. A warning band says not to plug a cable into the IEC inlet until the assembly is complete, the wiring is verified and the cap is on.">
  <figcaption>Every lead that lands on the block, and the screw it lands on. The red and blue drawn at the bottom are one module's: check which of yours is live rather than copying the colours. <cite>Drawn from the Mean Well LRS-350 spec sheet, the inlet's catalog entry and the harness drawings.</cite></figcaption>
</figure>

{% include step.html n="5" title="Close the box" %}

Slot the front panel down into the front module, then bring the front module up against the tray so the two shells meet. Lay the leads so none of them rests against the mains screws.

Then the two lids, 8 {% include fastener.html size="M3" variant="countersunk" length="12" %}. They cut their own thread in the shell parts, so run each one in until the lid is tight and stop.

<ol class="numbered-steps">
  <li><b>Rear lid</b>, the vented one, over the supply's fan end.</li>
  <li><b>Front lid</b>, over the other end. It traps the front panel, so check the panel is fully seated before it goes on.</li>
</ol>

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/psu-box-lids-full-bd00f0272ce4.png" alt="Render of the PSU housing with both lids lifted off and set down beside it, the plain front lid and the vented rear lid side by side, and all eight self-tapping bosses in the two shell parts ringed on the open box">
  <figcaption>Both lids lifted off, with all eight screw holes ringed. <cite>Rendered from the parts' own STLs.</cite></figcaption>
</figure>

The box is closed before the machine sees mains.

## The finished result

The supply inside the closed housing, both lids down, the mains inlet and the three jacks in the front panel, and the two clamp bosses ready for the frame.

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-parts/meanwell-psu-housing-v2-render-full-f4b161896ea6.png" alt="Render of the closed PSU box bolted onto a 2020 extrusion by the clamp bosses at each end, its vented rear lid on top and its front panel carrying the mains inlet and the three output jacks">
  <figcaption>The box closed and on its extrusion. <cite>Render from the models, not from a build.</cite></figcaption>
</figure>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Once it is in service, pull the cord out of the wall before you open this box.</b> The rocker is not an isolator you can rely on: a plug that goes in either way round means the switch may be breaking the neutral rather than the live, so treat everything inside as live whenever the cord is in.</p>
</div>

**Bolting it to the frame is on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }})**, once all three enclosures are built.

Next: [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}).
