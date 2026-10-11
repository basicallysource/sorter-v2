---
layout: default
title: Design intentions for the printed parts
type: explanation
section: lab
slug: lab-printed-parts
kicker: Design and research — Printed parts
lede: What the printed parts are designed around, how they attach to the extrusion and to each other, and how the design repeats as you add layers.
permalink: /lab/printed-parts/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-10
---

Almost every structural part of the machine is printed, and the frame they hang on is standard 2020 aluminium extrusion. The design asks three things of a printer: a 256 x 256 mm bed, a filament that survives a warm room, and a printer set up accurately enough to hold a few tenths of a millimetre. Most of the other design choices follow from these three and from the wish to need as few screws and nuts as possible.

This page explains why the parts are designed this way. How to print and assemble them is on <a href="{{ '/hardware/printing/' | relative_url }}">Printing the parts</a> and on the assembly pages it links to.

## What a printed part is designed around

<ul class="bulleted-list">
  <li><strong>The bed.</strong> The parts are designed for a 256 x 256 mm print bed, and no part in the parts catalog is larger.</li>
  <li><strong>The filament.</strong> PETG or ASA, because PLA softens from around 55 C, and the printed gears that the stepper motors turn would soften first.</li>
  <li><strong>The clearances.</strong> In the distribution parts, the parts that slide, snap or press together leave 0.21 to 0.24 mm of clearance. The print profile in the parts catalog uses 0.2 mm layers and a 0.4 mm nozzle. The published settings for the distribution parts are valid up to a 0.28 mm layer height.</li>
  <li><strong>Tight fits are flagged.</strong> The External bracket (side) clamps around the 2020 extrusion with very little room. The parts calculator marks it <strong>Tight fit</strong> and asks you to print one test part before you print the full set.</li>
  <li><strong>Orientation and supports are per part.</strong> Not every STL file is saved in the orientation you print it in, and supports are off for almost every part. The part's card in the parts calculator states any exception.</li>
</ul>

<ul class="bulleted-list">
  <li>Printer, filament, orientation and supports: <a href="{{ '/hardware/printing/' | relative_url }}">Printing the parts</a></li>
  <li>Operating conditions the filament choice rests on: <a href="{{ '/hardware/' | relative_url }}#intended-operating-conditions">Hardware overview</a></li>
  <li>The flags and notes on each part: <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts-calculator/catalog/parts.json</code></a></li>
</ul>

## How parts attach to the 2020 extrusion

The frame is 2020 extrusion because it is a standard size everywhere in the world, which makes the design and the shopping easier. The first frames were plywood, which was dropped because plywood varies and is hard to source, it is weaker, it needs a big CNC machine to make and it can warp (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1444456887054761989">the message that proposed the change</a>).

Printed brackets join the extrusion at every corner, and there are two ways to hold a bracket on:

<ul class="bulleted-list">
  <li><strong>Standard:</strong> an M5 x 16 screw cuts its own thread through the bracket wall and presses its tip against the extrusion.</li>
  <li><strong>Option:</strong> a roll-in T-nut in the slot, with the larger hole of the pair. It costs 12 more T-nuts per hex frame.</li>
</ul>

Inside the ring, the hex frame is designed to need no hardware. The Frame 90° brackets and the Frame crossbeams hold the six spokes by fit alone, and the aim was to avoid more nuts and screws. In the parts catalog, the brackets, covers and extrusion pieces of the frame are tagged as golden. This means that future versions of these parts must stay compatible with the ones you print now.

<ul class="bulleted-list">
  <li>The ring, the standard screw and the T-nut option: <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">Hex frame</a></li>
  <li>Fitting a roll-in T-nut: <a href="{{ '/hardware/helpers/t-nuts/' | relative_url }}">T-nuts</a></li>
  <li>Stability tags (<code>hex-frame-v2</code> and the parts tagged with it): the <code>tags</code> list in <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts.json</code></a></li>
</ul>

## How printed parts meet each other

A joint uses the lightest thing that will hold it. In rough order from lightest to heaviest:

<ul class="bulleted-list">
  <li><strong>Gravity and friction.</strong> The C-channel stands are designed to be screwless: every joint is gravity or friction, and pinning a stand is optional. The camera lamp covers and hooks are friction fits with no screw hole anywhere.</li>
  <li><strong>Snaps.</strong> A funnel takes no fasteners. It snaps into its two brackets.</li>
  <li><strong>Screws that cut their own thread.</strong> Some small housings and clamps take M3 screws straight into the plastic.</li>
  <li><strong>Heat-set inserts.</strong> Brass inserts carry the thread in several parts. The funnel brackets screw into the chute core's inserts, so there is nothing to tap, and the core alone takes 18 M3 inserts. The Lazy Susan bearing bolts into inserts in the printed parts on both sides.</li>
  <li><strong>Press fits.</strong> Bearings press into printed seats, which is why the printer needs calibrating before those parts.</li>
</ul>

<ul class="bulleted-list">
  <li>Screwless stands: <a href="{{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}">Arranging C-channels</a></li>
  <li>Snap fit: <a href="{{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}">Funnel brackets</a></li>
  <li>Inserts: <a href="{{ '/hardware/helpers/heat-inserts/' | relative_url }}">Heat inserts</a> and <a href="{{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}">Chute core</a></li>
  <li>The bearing the chute turns on: <a href="{{ '/hardware/parts/lazy-susan/' | relative_url }}">Lazy Susan</a></li>
</ul>

## Screws and other hardware

The intention is to use as few different types of screws and similar hardware as possible. The machine mostly uses M3 and M5 screws, with a few M4. The M5 x 16 socket/button head screw is the one used most for brackets, and the M3 x 8 and M3 x 12 countersunk screws wherever a flush head is wanted. Parts that need a thread in plastic take heat-set inserts, and the 2020 frame takes roll-in T-nuts. This is the direction the design is heading in, not a promise about every part. The exact types and quantities change, so the bill of materials is the only list to trust.

<ul class="bulleted-list">
  <li>Every screw, nut, washer and insert, with where to buy it and how many a machine needs: <a href="https://parts-calculator.basically.website/hardware">Bill of materials</a></li>
  <li>Fitting inserts and T-nuts: <a href="{{ '/hardware/helpers/heat-inserts/' | relative_url }}">Heat inserts</a> and <a href="{{ '/hardware/helpers/t-nuts/' | relative_url }}">T-nuts</a></li>
</ul>

## Shapes that do a job

<ul class="bulleted-list">
  <li><strong>The faceted rotor.</strong> A round rotor touches a long piece at only one point, while the stator wall touches it at two points, so larger pieces do not move along. The facets turn that single point into a line of contact, so large pieces do move along. Three of the four channels use it.</li>
  <li><strong>The finned rotor.</strong> The classification channel, the last of the four, uses fins instead of facets to keep pieces moving on that stage.</li>
  <li><strong>The two funnel sizes.</strong> A layer has either a third-size funnel or a half-size funnel, named after the size of the bins under them. The third-size funnel is designed to pass a piece at least 48 mm (6 studs) wide, and the half-size funnel one at least 64 mm (8 studs) wide, with some room to spare. The size you choose for a layer sets that layer's set of bins.</li>
</ul>

<ul class="bulleted-list">
  <li>The four channels and what differs between them: <a href="{{ '/hardware/assembly/feeder/c-channels/' | relative_url }}">C-channels</a></li>
  <li>The classification rotor: <a href="{{ '/hardware/assembly/feeder/c-channels/classification-channel/' | relative_url }}">Classification channel</a></li>
  <li>Choosing a funnel per layer: <a href="{{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}">Funnel brackets</a></li>
</ul>

## How the design repeats

<ul class="bulleted-list">
  <li><strong>Layers.</strong> Every layer is the same set of parts, 160 mm apart. The counts for an N-layer machine are on the stacking page.</li>
  <li><strong>Bins are optional.</strong> They are left out of the printed totals. Each drops into its bay and is held by the bin retainers, so cardboard or boxes you already own work as well as printed ones.</li>
</ul>

The parts calculator turns your layer count and funnel choices into a part list, which is why quantities on the assembly pages are written per layer.

<ul class="bulleted-list">
  <li>Layer joint and screw count: <a href="{{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}">Stacking the layers</a></li>
  <li>Connector pairs: <a href="{{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}">Layer connectors</a></li>
  <li>The shared channel core: <a href="{{ '/hardware/assembly/feeder/c-channels/channel-core/' | relative_url }}">Channel core</a></li>
  <li>Printed or cardboard bins: <a href="{{ '/hardware/assembly/install-bins/' | relative_url }}">Install the bins</a></li>
</ul>
