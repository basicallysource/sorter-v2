---
layout: default
title: Make the Orange Pi's 24 V lead
type: how-to
section: hardware
slug: helper-pi-24v-lead
kicker: Helpers — Orange Pi 24 V lead
lede: A barrel plug onto the buck converter's own input wires, so the Pi runs off the same 24 V supply as everything else. One per machine.
permalink: /hardware/helpers/pi-24v-lead/
author: effreek
contributors: [brickcyclealice]
warning: >-
  **The photographs are from a real build; the numbers are not all settled.** One builder has made
  this lead, and the 100 mm below is her converter's own lead length rather than a specification.
  The finished length has never been measured on a mounted machine, and the 22 AWG is a **GUESS**
  in the [wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) notes, marked
  as one on the drawing.
parts_needed:
  - part: buck-24v-5v-usbc
    qty: 1
  - part: dc-plug-5521-male
    qty: 1
  - part: wire-22awg-2c
    qty: 1
og_image: https://assets.basically.website/sorter-docs/harness-pi-24v-lead-built-w1600-d117f59e66d7.jpg
tools_needed: [Multimeter, "A small screwdriver, for a screw-terminal plug", "Only if you splice: side cutters, wire strippers, soldering iron and adhesive-lined heat shrink"]
---

This is `W3` on the [harness drawings]({{ '/hardware/parts/harness-order/#power' | relative_url }}). It runs from one of the three jacks on the [PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }}) to the buck converter, and the converter's own USB-C lead is the rest of the run to the Pi. **One per machine.**

<div class="callout">
  <p><b>This is the shortest of the three 24 V leads and the only one with no connector at its far end.</b> The converter arrives with bare input wires, so the whole job is putting a barrel plug on them, and usually without adding any wire. The <a href="{{ '/hardware/helpers/board-24v-lead/' | relative_url }}">lead to the board</a> is the other one you make; the one to the USB hub is bought ready made with a plug at each end.</p>
</div>

## The two ends

<dl class="spec-list">
  <dt>PSU end</dt><dd>Male DC barrel plug, <b>5.5 mm outside and 2.1 mm inside</b>, centre-positive. A 2.5 mm plug looks identical and does not mate.</dd>
  <dt>Converter end</dt><dd>No connector. The converter's own two input wires, red positive and black negative, printed on its case.</dd>
  <dt>Wire</dt><dd>None, usually. The harness gives this lead as 150 mm (6 in) of 22 AWG, and the converter arrives with most of that already: the one measured is about 120 mm. <b>Under 100 mm is where you add wire</b>, and that is the only reason this lead ever gets spliced.</dd>
</dl>

The converter takes 8 to 32 V in and gives 5 V out at up to 5 A. It is potted, so there is nothing to open and nothing to adjust, and its output is a captive USB-C lead.

## Build it

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-pi-24v-lead-parts-w1600-e990b550277e.jpg" alt="The buck converter as it arrives: a small black potted block with a long captive USB-C lead out of one side, two short red and black input wires out of the other with a warning label on them, and a separate screw-terminal DC barrel plug lying beside it">
  <figcaption>What you start with. The converter's input wires are the short pair; the plug is the only thing you add. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<ol class="numbered-steps">
  <li>Measure the converter's own input wires. <b>100 mm or more and nothing gets spliced</b>: they go straight into the plug, and the converter ends up hanging at the PSU box, which is where the long USB-C lead expects it to be. Shorter than 100 mm, do step 2 first; otherwise skip it.</li>
  <li><b>Only if they are short.</b> Splice a length of 22 AWG red and black on to make the lead up to about 150 mm (6 in): solder each joint, cover each one with adhesive-lined heat shrink, then sleeve the pair together. Red to red, black to black.</li>
  <li>Work out which terminal of the plug is the tip. A screw-terminal plug is usually marked <code>+</code> and <code>-</code>; a moulded one is two wires. Either way, set the multimeter to continuity and hold one probe on the centre pin inside the plug: the terminal or wire that beeps is <b>+24 V</b>. This is the step where you find out rather than assume.</li>
  <li>Fit the plug, <b>the converter's red wire to the tip and its black wire to the sleeve</b>. On a screw-terminal plug, get the bare strands fully under the screws, tighten firmly and pull on each wire; on a moulded one, solder and heat shrink each joint as in step 2.</li>
</ol>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Check the output before it goes anywhere near the Pi.</b> Plug the finished lead into a PSU box jack with nothing on the USB-C end, and meter the USB-C lead: it reads about 5 V. A converter wired backwards can pass the input straight through, and 24 V into the Pi ends the Pi.</p>
</div>

## The finished result

The converter with a barrel plug on its input wires and its USB-C lead free. One per machine, and that is the whole lead.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-pi-24v-lead-built-w1600-d117f59e66d7.jpg" alt="The finished lead: the buck converter with a screw-terminal DC barrel plug fitted to its red and black input wires, and its captive USB-C lead curving away from the other side">
  <figcaption>The plug fitted straight to the converter's own wires, no splice. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

The plug goes into any of the three jacks on the PSU box, all three the same 24 V. The USB-C end goes into the socket the Pi prints `PWR IN`, at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 6.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The Pi has two USB-C sockets that look the same</b> and only the one marked <code>PWR IN</code> is a power input. The other is USB 3.1 and DisplayPort, with no power function.</p>
</div>

## Reference

The drawing for this lead, its bill of materials and its downloads are on the [WireViz drawings]({{ '/hardware/parts/harness-order/#power' | relative_url }}) page.
