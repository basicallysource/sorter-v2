---
layout: default
title: Preparing the LED strip
type: how-to
section: hardware
slug: helper-led-strip
kicker: Helpers — LED strip
lede: Cutting a length of 24 V strip and getting its cable onto the cut end, with a clamp-on connector or with solder. Three per machine.
permalink: /hardware/helpers/led-strip/
author: brickcyclealice
contributors: [effreek, reveryx, spencer, barthel]
og_image: https://assets.basically.website/sorter-parts/led-strip-connector-8mm-full-915e0ed03fdc.jpg
warning: >-
  **Neither way of making the joint is photographed on a build.** The length and where to cut come
  from real builds; the two ways of getting wire onto the pads are the manufacturers' own pictures.
  The cable's 22 AWG is a **GUESS** in the harness notes, marked as one in the
  [WireViz drawing]({{ '/hardware/electronics/wireviz/' | relative_url }}).
parts_needed:
  - part: led-strip-24v
    qty: 1
  - part: led-strip-connector-8mm
    qty: 1
  - part: dupont-lead-2p-1m
    qty: 1
tools_needed: [Side cutters, "Only if you solder: iron, solder and heatshrink", "Only if you make your own lead: crimp tool"]
---

A prepared strip is a cut length of 24 V COB strip with its cable on the end of it: about a metre of 22 AWG red and black, ending in a 2-pin 2.54 mm Dupont plug. **A machine takes three**, and each carries about 0.5 A.

**The quantities above are for one, so a machine needs three of each**, except the strip: one 5 m roll cuts into five lengths. The Dupont leads come five to a pack. So a machine is one roll, three connectors and one pack.

<dl class="spec-list">
  <dt>The cable</dt><dd>One continuous pair of 22 AWG, about a metre, with no connector in the middle. That is how the one Spencer photographed is built, and it is what Jon (who drew the harness) says to do.</dd>
  <dt>Strip end</dt><dd>A solderless clamp-on connector, or solder, onto the two pads at the cut end.</dd>
  <dt>The other end</dt><dd>The Dupont plug, which goes onto an LED port when the machine is wired up: step 5 of <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">connecting the components</a>.</dd>
</dl>

<div class="callout">
  <p><b>You do not need a soldering iron.</b> A clamp-on connector at the strip and a ready-made 2-pin Dupont pigtail at the board is the whole thing out of two bought parts, joined once in the middle. You do not need a crimp tool either unless you make the Dupont end yourself.</p>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Check the roll you bought is the <b>24 V</b> one. The listing in the catalog also sells a 12 V strip of the same width, and the board's LED headers feed 24 V.</p>
</div>

{% include step.html n="1" title="Cut the strip to length, on a mark" %}

**950 mm per [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }})**, which is the only length this machine cuts, and one 5 m roll gives five of them.

**Cut only on the printed marks**, never between them: the solder pads are at the marks, so a cut anywhere else leaves nothing to connect to. Take the nearest mark to the length you want rather than the exact measurement.

Leave the blue protective film on until the strip is going where it lives. It is the only thing keeping grease off the adhesive.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/led-strip-cut-marks-plain-full-3351d6e9340e.png" alt="Diagram of a COB LED strip seen from above with a scissors symbol over each of two cut points, and the copper pads at each cut point labelled +24V on the top row and minus on the bottom">
  <figcaption>The cut points, with the pads that sit either side of them. Each cut leaves you half of a pad, printed <code>+24V</code> on one side. <cite>Manufacturer diagram (VOEWT).</cite></figcaption>
</figure>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Cut one plug off the lead first.</b> The bought lead has a plug on both ends: the <b>male</b> one has two pins sticking out of it, the <b>female</b> one has two holes. <b>Cut the male plug off</b> and use that cut end at the strip, whichever way you make the joint. The female end stays on: that is what pushes onto the board later. If you are soldering rather than clamping, strip 3 mm of each wire at that cut end as well.</p>
</div>

{% include step.html n="2a" title="Either: clamp a connector onto the pads" %}

The solderless connector is a hinged body with sprung contacts at each end: the strip goes in one end, the wire in the other, and nothing is stripped or tinned.

<ol class="numbered-steps">
  <li>Lift the lid at the strip end, slide the cut end in until the two copper pads sit under the contacts, and press it shut. The pad printed <code>+24V</code> takes the red side.</li>
  <li>Clamp the wire into the other end, red to the <code>+24V</code> side. It bites through the insulation, so the wire does not need stripping either.</li>
</ol>

**Match the width.** These are 8 mm COB connectors and nothing else will grip: a 10 mm body, or one meant for SMD strip, will not hold the pads against the contacts.

The wire is the pair that runs back to the board, a metre of 22 AWG red and black.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/led-strip-clamp-sequence-black-full-3e4b2ec3e816.png" alt="Two stages of clamping: above, the cut end of a COB strip lined up with the open connector, an arrow showing it going in, with red and black wire already in the far end; below, the connector pressed shut on the strip with the pair leaving it">
  <figcaption>The strip into the open connector, then the connector pressed shut on it. <cite>Manufacturer photos (LED strip connector product listing; seller not recorded).</cite></figcaption>
</figure>

{% include step.html n="2b" title="Or: solder the wires to the pads" %}

Perfectly good, and what the strip is designed for. It needs no connector at all.

<ol class="numbered-steps">
  <li>Clear any coating off the two pads and melt a little solder onto each until it wets the copper.</li>
  <li>Tin 3 mm of bared wire the same way.</li>
  <li>Hold the wire on the pad and touch the iron to both for a second or two. Red to <code>+24V</code>, black to <code>-</code>.</li>
  <li>Insulate each joint, with heatshrink over the wire or a piece over the whole end, so the two cannot touch.</li>
</ol>

Keep the iron on the pad briefly. The strip's backing and the LED next to the pad do not like being cooked.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/led-strip-soldered-joint-clean-full-bdad7637dc9c.png" alt="The cut end of a COB LED strip with a red and a black wire soldered to its two pads, a piece of clear heatshrink over the joint, and the pair running away from the strip">
  <figcaption>A soldered end, insulated with clear heatshrink over the joint. <cite>Manufacturer photo (LED strip product listing; seller not recorded).</cite></figcaption>
</figure>

## Choosing the parts

<dl class="spec-list">
  <dt>Which connector</dt><dd>Three variants of the same body, all SuperBrightLEDs, all <b>8 mm COB only</b>, 22 AWG, 3A. <code>SBL-RA2P-8</code> ($1.59) is the one in the list above: it bites the strip at one end and <b>your own wire</b> at the other, no wire supplied. <code>SBL-RA2P-8-1</code> ($1.69) is the same thing with 4 in of tinned lead already on it, so you splice rather than clamp. <code>SBL-RA2P-8-DC</code> ($2.79) ends in a 5.5 × 2.1 mm barrel socket, which is only useful if you want the lamp to unplug partway along. <b>Match the width</b>: a 10 mm connector, or one for SMD strip, will not grip.</dd>
  <dt>If you own a crimp tool</dt><dd>You can make the lead yourself instead of buying it: about a metre of 22 AWG stranded per run, one red and one black, plus a 2-pin 2.54 mm Dupont female housing and two crimps. Gauge is a <b>GUESS</b> in the harness notes.</dd>
  <dt>Insulation</dt><dd>Heatshrink, or lever connectors (Wago 221) or solder-seal butt splices, only if you end up splicing something.</dd>
</dl>

## The finished result

A 950 mm length of strip with a red and a black wire on one end and a dead end at the other, three of them for a machine. Nothing is joined end to end, so the far end of the strip stays dead.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/led-strip-connector-8mm-full-915e0ed03fdc.jpg" alt="A length of 8 mm COB LED strip with a clear clamp-on connector on its cut end, a red and a black wire leaving the other side of the connector in a white sheath">
  <figcaption>A prepared strip: the cut end, the joint, and the cable that leaves it. <cite>Manufacturer photo (SuperBrightLEDs).</cite></figcaption>
</figure>

The Dupont end goes onto an LED port at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 5.
