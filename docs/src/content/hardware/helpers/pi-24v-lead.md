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
  The finished length has never been measured on a mounted machine, and the 22 AWG (0.33 mm²) is a **GUESS**
  in the [wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) notes, marked
  as one on the drawing.
parts_needed:
  - part: buck-24v-5v-usbc
    qty: 1
  - part: dc-plug-5521-male
    qty: 1
  - part: wire-22awg-2c
    qty: 1
  - part: butt-connector-red-22-16
    qty: 2
og_image: https://assets.basically.website/sorter-docs/harness-pi-24v-lead-built-w1600-d117f59e66d7.jpg
tools_needed: ["A ruler or tape measure, to measure the converter's input wires", "Side cutters, only if you have to extend the wires", "Wire strippers, for 22 AWG (0.33 mm²) wire, only for a moulded plug or extended wires", "Insulated-terminal crimping pliers with a jaw for 22 to 16 AWG (0.33 to 1.3 mm²) wire, for the butt connectors on a moulded plug or extended wires", "A small screwdriver, only for a screw-terminal plug", "Multimeter, to find the tip and to check the finished lead", "Only if you solder the joints instead of crimping them: a soldering iron, solder and adhesive-lined heat shrink (see Getting started)"]
---

This is `W3` on the [harness drawings]({{ '/hardware/parts/harness-order/#power' | relative_url }}). It runs from one of the three jacks on the [PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }}) to the buck converter, and the converter's own USB-C lead is the rest of the run to the Pi. **One per machine.**

<div class="callout">
  <p><b>This is the shortest of the three 24 V leads and the only one with no connector at its far end.</b> The converter arrives with bare input wires, so the whole job is putting a barrel plug on them, and usually without adding any wire. The <a href="{{ '/hardware/helpers/board-24v-lead/' | relative_url }}">lead to the board</a> is the other one you make; the one to the USB hub is bought ready made with a plug at each end.</p>
</div>

## The two ends

<dl class="spec-list">
  <dt>PSU end</dt><dd>Male DC barrel plug, <b>5.5 mm outside and 2.1 mm inside</b>, centre-positive. A 2.5 mm plug looks identical and does not mate.</dd>
  <dt>Converter end</dt><dd>No connector. The converter's own two input wires, red positive and black negative, printed on its case.</dd>
  <dt>Wire</dt><dd>None, usually. The harness gives this lead as 150 mm (6 in) of 22 AWG (0.33 mm²), and the converter arrives with most of that already: the one measured is about 120 mm. <b>Under 100 mm is where you add wire</b>, and that is the only reason this lead ever gets spliced.</dd>
</dl>

The converter takes 8 to 32 V in and gives 5 V out at up to 5 A. It is potted, so there is nothing to open and nothing to adjust, and its output is a captive USB-C lead.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/w3-24v-lead-diagram-full-22caf5109dd5.png" alt="Diagram of the finished lead with a moulded plug, left to right: a barrel plug with two short leads, red and black, each joined to one of the converter's red and black input wires by a butt connector, the two connectors staggered; the converter's input wires, 100 mm or more; the buck converter; and its own USB-C lead going to the Pi's PWR IN socket.">
  <figcaption>The finished lead with a moulded plug. With a screw-terminal plug there are no butt connectors: the converter's wires go straight under the plug's screws.</figcaption>
</figure>

## Build it

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-pi-24v-lead-parts-w1600-e990b550277e.jpg" alt="The buck converter as it arrives: a small black potted block with a long captive USB-C lead out of one side, two short red and black input wires out of the other with a warning label on them, and a separate screw-terminal DC barrel plug lying beside it">
  <figcaption>What you start with. The converter's input wires are the short pair; the plug is the only thing you add. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<ol class="numbered-steps">
  <li>Measure the converter's own input wires with a ruler, from the case to the cut end. <b>100 mm or more and nothing needs extending</b>: they go straight to the plug. Shorter than 100 mm, do step 2 first; otherwise skip it.</li>
  <li><b>Only if they are short.</b> Cut a red and black pair of 22 AWG (0.33 mm²) wire with side cutters, long enough to make the lead up to about 150 mm (6 in). Join each wire of it to the converter wire of the same colour with a butt connector, red to red and black to black. How is under <b>Joining two wires with a butt connector</b>, below.</li>
  <li>Work out which terminal of the plug is the tip. A screw-terminal plug is usually marked <code>+</code> and <code>-</code>; a moulded one is two wires. Either way, set the <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#continuity-for-tracing-a-cable">multimeter to continuity</a> and hold one probe on the centre pin inside the plug: the terminal or wire that beeps is <b>+24 V</b>. This is the step where you find out rather than assume. On a moulded plug, put a turn of tape on the tip wire so you can tell it from the other.</li>
  <li>Fit the plug, <b>the converter's red wire to the tip and its black wire to the sleeve</b>. On a <b>screw-terminal plug</b>, get the bare strands fully under the screws, tighten firmly and pull on each wire. On a <b>moulded plug</b>, join the converter's red wire to the plug's tip wire and the converter's black wire to the plug's other wire, one butt connector each, as in step 2. Stagger the two connectors by a few millimetres along the lead so they cannot touch.</li>
  <li>Check the output, as under <b>Check the lead</b>, below.</li>
</ol>

### Joining two wires with a butt connector

Used in step 2 and, on a moulded plug, in step 4. A butt connector is a vinyl-insulated barrel that takes one wire in each end, rated for 22 to 16 AWG (0.33 to 1.3 mm²) wire. Make one joint at a time so the two never touch.

The listing for the converter does not give the gauge of its input wires. Before you crimp, strip one wire and push it into the connector: the strands should fill the barrel. If they sit loose with room to spare, the wire is too thin for this connector, so solder it and cover the joint with heat shrink instead.

<ol class="numbered-steps">
  <li>Strip 7 mm off each of the two wires, and twist the strands of each tight.</li>
  <li>Push one wire into each end of the butt connector, until the insulation of each wire meets the end of the barrel.</li>
  <li>Close each end of the barrel in the jaw of the insulated-terminal crimping pliers marked for 22 to 16 AWG (0.33 to 1.3 mm²), so each wire is crimped separately. Squeeze until the tool releases. Pull on each wire to check it holds.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/butt-crimp-steps-marked-full-bc997851a06a.png" alt="Three stages: a wire with 7 mm of bare strands; a wire pushed into each end of an insulated butt connector; the connector held between the jaws of a crimping tool, the jaw marked for 22 to 16 AWG, 0.33 to 1.3 mm².">
  <figcaption>Strip, push in, crimp each end in the marked jaw.</figcaption>
</figure>

Choose the jaw by the size marked on it, not by its colour. To solder instead of crimping, solder the two wires together and cover each joint with a 25 mm piece of 3 mm adhesive-lined heat shrink (see Getting started).

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Use insulated-terminal crimping pliers.</b> A crimp tool for open-barrel contacts has the wrong die and will not close a butt connector properly.</p>
</div>

### Check the lead

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Check the output before it goes anywhere near the Pi.</b> A converter wired backwards can pass the input straight through, and 24 V into the Pi ends the Pi.</p>
</div>

<ol class="numbered-steps">
  <li>Plug the finished lead into a PSU box jack, with nothing on the USB-C end.</li>
  <li>Set the multimeter to DC volts and meter the USB-C plug. Each row of its contacts has 12 in a line: the contact at the very end of a row is ground and the fourth contact in from either end of the same row is +5 V. Touch the black probe to the end contact and the red probe to the fourth one. It reads about 5 V.</li>
  <li>If it reads 0 V, or anything near 24 V, unplug the lead from the jack at once and check which wire went to the tip.</li>
</ol>

## The finished result

The converter with a barrel plug on its input wires and its USB-C lead free. One per machine, and that is the whole lead.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-pi-24v-lead-built-w1600-d117f59e66d7.jpg" alt="The finished lead: the buck converter with a screw-terminal DC barrel plug fitted to its red and black input wires, and its captive USB-C lead curving away from the other side">
  <figcaption>The plug fitted straight to the converter's own wires, no splice. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

The plug goes into any of the three jacks on the PSU box, all three the same 24 V. Where the USB-C end goes is at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 6.

## Reference

The drawing for this lead, its bill of materials and its downloads are on the [WireViz drawings]({{ '/hardware/parts/harness-order/#power' | relative_url }}) page.
