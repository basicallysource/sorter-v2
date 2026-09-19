---
layout: default
title: Make the Orange Pi's 24 V lead
type: how-to
section: hardware
slug: helper-pi-24v-lead
kicker: Helpers — Orange Pi 24 V lead
lede: A barrel plug onto the buck converter's input wires, so the Pi runs off the same 24 V supply as everything else. One per machine.
permalink: /hardware/helpers/pi-24v-lead/
author: effreek
contributors: [brickcyclealice]
warning: >-
  **AI-generated first draft.** Written from the [wire harness]({{ '/hardware/electronics/' |
  relative_url }}) schedule and the converter's own specification, not from an actual build.
  Nobody has made this lead from these steps yet. The 22 AWG is a **GUESS** in the harness notes,
  marked as one on the drawing.
parts_needed:
  - part: buck-24v-5v-usbc
    qty: 1
  - part: dc-plug-5521-male
    qty: 1
  - part: wire-22awg-2c
    qty: 1
tools_needed: [Side cutters, Wire strippers, "Soldering iron and adhesive-lined heat shrink", Multimeter]
---

This is `W3` on the [harness drawings]({{ '/hardware/parts/harness-order/#power' | relative_url }}). It runs from one of the three jacks on the [PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }}) to the buck converter, and the converter's own USB-C lead is the rest of the run to the Pi. **One per machine.**

<div class="callout">
  <p><b>This is the shortest of the three 24 V leads and the only one with no connector at its far end.</b> The converter arrives with bare input wires, so the job is putting a barrel plug on them. The lead to the board is <a href="{{ '/hardware/helpers/board-24v-lead/' | relative_url }}">made the same way</a>; the one to the USB hub is bought ready made with a plug at each end.</p>
</div>

## The two ends

<dl class="spec-list">
  <dt>PSU end</dt><dd>Male DC barrel plug, <b>5.5 mm outside and 2.1 mm inside</b>, centre-positive. A 2.5 mm plug looks identical and does not mate.</dd>
  <dt>Converter end</dt><dd>No connector. The converter's two input wires, spliced.</dd>
  <dt>Wire</dt><dd>22 AWG, two conductor, red and black, about 150 mm (6 in) finished. The converter's own leads may be most of that already.</dd>
</dl>

The converter takes 8 to 32 V in and gives 5 V out at up to 5 A. It is potted, so there is nothing to open and nothing to adjust, and its output is a captive USB-C lead.

## Build it

<ol class="numbered-steps">
  <li>Start from a moulded barrel plug on a short lead. Hold the converter where it will sit and see how much wire the run actually wants; 150 mm (6 in) end to end is the figure in the harness notes, and shorter is fine.</li>
  <li>Find which conductor of the plug is the tip. Set the multimeter to continuity, hold one probe on the centre pin inside the plug, and the conductor that beeps is <b>+24 V</b>. It is the red one on most moulded plugs, and this is the step where you find out rather than assume.</li>
  <li>Splice it to the converter's input wires, <b>tip to the converter's positive wire and sleeve to its negative</b>. Solder each joint, cover each one with adhesive-lined heat shrink, then sleeve the pair together.</li>
</ol>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Check the output before it goes anywhere near the Pi.</b> Plug the finished lead into a PSU box jack with nothing on the USB-C end, and meter the USB-C lead: it reads about 5 V. A converter wired backwards can pass the input straight through, and 24 V into the Pi ends the Pi.</p>
</div>

## Where it goes

The plug goes into any of the three jacks on the PSU box, all three the same 24 V. The USB-C end goes into the socket the Pi prints `PWR IN`, at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 6.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The Pi has two USB-C sockets that look the same</b> and only the one marked <code>PWR IN</code> is a power input. The other is USB 3.1 and DisplayPort, with no power function.</p>
</div>

## Reference

The drawing for this lead, its bill of materials and its downloads are on the [WireViz drawings]({{ '/hardware/parts/harness-order/#power' | relative_url }}) page.
