---
layout: default
title: Preparing the LED strip
type: how-to
section: hardware
slug: helper-led-strip
kicker: Helpers — LED strip
lede: Cutting a length of 24 V strip, getting two wires onto the cut end with or without solder, and running that pair back to an LED header on basically board v1.3. Three per machine.
permalink: /hardware/helpers/led-strip/
author: brickcyclealice
contributors: [effreek, reveryx, spencer, barthel]
warning: >-
  **Not validated end to end against a built machine.** The strip end is from a real build, but
  neither way of making its joint has been photographed: the strip in the photograph came off the
  roll with its leads already fitted. The run back to the board is off the harness notes, and the
  values marked **GUESS** in the [WireViz drawing]({{ '/hardware/electronics/wireviz/' | relative_url }}),
  including the wire gauge and which board pin is +24V, are guesses. Meter the header before you
  plug anything into it.
parts_needed:
  - part: led-strip-24v
    qty: 1
  - part: led-strip-connector-8mm
    qty: 1
  - part: dupont-lead-2p-1m
    qty: 1
tools_needed: [Side cutters, Multimeter, "Only if you solder: iron, solder and heatshrink", "Only if you make your own lead: crimp tool"]
---

A prepared strip is a cut length of 24 V COB strip with a two-conductor run on the end of it: the strip at one end, a 2-pin Dupont plug onto one of the board's LED headers at the other. **A machine takes three**, and each carries about 0.5 A.

**The quantities above are for one, so a machine needs three of each**, except the strip: one 5 m roll cuts into five lengths. The Dupont leads come five to a pack. So a machine is one roll, three connectors and one pack.

<dl class="spec-list">
  <dt>Board end</dt><dd>A 2-pin 2.54 mm Dupont plug onto one of the four LED headers on basically board v1.3, <code>J8</code> to <code>J11</code>.</dd>
  <dt>In between</dt><dd><b>On a v1.3 board it is Dupont straight to the strip</b>: one continuous pair of 22 AWG, about a metre, with no connector in the middle. That is how the one Spencer photographed is built, and it is what Jon (who drew the harness) says to do.</dd>
  <dt>Optional unplug point</dt><dd>A 5.5 × 2.1 mm barrel pair partway along, so the strip end comes off without unwiring, which splits the run into about 36 in of feed and about 6 in of pigtail. The harness notes still draw it that way. Fit it if you want it; nothing needs it.</dd>
  <dt>Strip end</dt><dd>A solderless clamp-on connector, or solder, onto the two pads at the cut end.</dd>
</dl>

<div class="callout">
  <p><b>You do not need a soldering iron.</b> A clamp-on connector at the strip and a ready-made 2-pin Dupont pigtail at the board is the whole thing out of two bought parts, joined once in the middle. You do not need a crimp tool either unless you make the Dupont end yourself.</p>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Check the roll you bought is the <b>24 V</b> one. The listing in the catalog also sells a 12 V strip of the same width, and the board's LED headers feed 24 V.</p>
</div>

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>No current-limiting resistor on this run.</b> The strip has its own, and board v1.3 already carries one in series with the +24V feed to each LED header. That is only true of the strip: a 50 mm COB plate needs its own resistor, see the <a href="{{ '/hardware/electronics/' | relative_url }}">wire harness</a> page.</p>
</div>

## Choosing the parts

<dl class="spec-list">
  <dt>Which connector</dt><dd>Three variants of the same body, all SuperBrightLEDs, all <b>8 mm COB only</b>, 22 AWG, 3A. <code>SBL-RA2P-8</code> ($1.59) is the one in the list above: it bites the strip at one end and <b>your own wire</b> at the other, no wire supplied. <code>SBL-RA2P-8-1</code> ($1.69) is the same thing with 4 in of tinned lead already on it, so you splice rather than clamp. <code>SBL-RA2P-8-DC</code> ($2.79) ends in a 5.5 × 2.1 mm barrel socket, which is only useful if you fit the optional unplug point. <b>Match the width</b>: a 10 mm connector, or one for SMD strip, will not grip.</dd>
  <dt>If you own a crimp tool</dt><dd>You can make the lead yourself instead of buying it: about a metre of 22 AWG stranded per run, one red and one black, plus a 2-pin 2.54 mm Dupont female housing and two crimps. Gauge is a <b>GUESS</b> in the harness notes.</dd>
  <dt>Barrel pair, if you want the unplug point</dt><dd>5.5 × 2.1 mm, one male and one female, <b>tip positive</b>. Buy only the mating half if your strip connector already brings one. The same size as the PSU outputs, so check you are not about to plug this into a PSU jack. Not in the catalog, because a v1.3 board does not need it.</dd>
  <dt>Insulation</dt><dd>Heatshrink, or lever connectors (Wago 221) or solder-seal butt splices, only if you end up splicing something.</dd>
</dl>

{% include step.html n="1" title="Cut the strip to length, on a mark" %}

**950 mm per [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }})**, which is the only length this machine cuts, and one 5 m roll gives five of them.

**Cut only on the printed marks**, never between them: the solder pads are at the marks, so a cut anywhere else leaves nothing to connect to. Take the nearest mark to the length you want rather than the exact measurement.

Leave the blue protective film on until the strip is going where it lives. It is the only thing keeping grease off the adhesive.

{% include step.html n="2" title="Either: clamp a connector onto the pads" %}

The solderless connector is a hinged body with sprung contacts at each end: the strip goes in one end, the wire in the other, and nothing is stripped or tinned.

<ol class="numbered-steps">
  <li>Lift the lid at the strip end, slide the cut end in until the two copper pads sit under the contacts, and press it shut. The pad printed <code>+24V</code> takes the red side.</li>
  <li>Clamp the wire into the other end, red to the <code>+24V</code> side. It bites through the insulation, so the wire does not need stripping either.</li>
</ol>

**Match the width.** These are 8 mm COB connectors and nothing else will grip: a 10 mm body, or one meant for SMD strip, will not hold the pads against the contacts.

The wire is the pair that runs back to the board, a metre of 22 AWG red and black.

{% include step.html n="3" title="Or: solder the wires to the pads" %}

Perfectly good, and what the strip is designed for. It needs no connector at all.

<ol class="numbered-steps">
  <li>Clear any coating off the two pads and melt a little solder onto each until it wets the copper.</li>
  <li>Tin 3 mm of bared wire the same way.</li>
  <li>Hold the wire on the pad and touch the iron to both for a second or two. Red to <code>+24V</code>, black to <code>-</code>.</li>
  <li>Insulate each joint, with heatshrink over the wire or a piece over the whole end, so the two cannot touch.</li>
</ol>

Keep the iron on the pad briefly. The strip's backing and the LED next to the pad do not like being cooked.

{% include step.html n="4" title="The first length off the roll is already done" %}

A roll arrives with bare leads soldered to one end at the factory. Cut your first length so that end is on your piece and it needs neither a connector nor an iron: trim the leads and join them to the run back to the board. The other two take plain cut lengths from the middle of the roll, and those are the ones that need step 2 or step 3.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-strip-second-turn-w1600-e7a417c98b26.jpg" alt="Two turns of LED strip fitted inside a white printed housing, one above the other, the protective film gone, with the red and black leads leaving it at one side">
  <figcaption>The roll's own lead end, red and black, on a fitted length. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="5" title="Plug the other end into the board" %}

**Push the 2-pin Dupont housing onto an LED header**, <code>J8</code> to <code>J11</code>. Red to +24V, and check which pin that is with a meter first. If you are using the pre-crimped lead, cut its male plug off and the female end is already the plug you need; otherwise crimp a housing on yourself.

Cable-tie the pair along whatever it runs down, so it is not hanging loose.

{% include step.html n="6" title="Optional: an unplug point partway along" %}

Cut the run where you want it to come apart and put the barrel pair in, red to the tip. The strip end then comes off without unwiring anything. Nothing needs this on a v1.3 board.

{% include step.html n="7" title="Set the output in software" %}

Settings, then the channel, then the LED button: pick which of the board's LED outputs this one is on, and set the brightness with the slider. **Nothing lights until an output is assigned.**

Repeat for all three.

## Reference

The two segments are <code>L1</code>/<code>L1p</code> to <code>L3</code>/<code>L3p</code> in the wire schedule on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page, and the drawings are on [WireViz drawings]({{ '/hardware/electronics/wireviz/' | relative_url }}). Both still split every run at a barrel jack, because <code>leds.yml</code> has not been redrawn since the straight run became the recommendation.
