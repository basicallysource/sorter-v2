---
layout: default
title: Labelling the cables
type: how-to
section: hardware
slug: helper-cable-labels
kicker: Helpers — Labelling the cables
lede: A label with its ID on both ends of every cable, so you can tell the cables apart once they are routed. Printable sheets for A4 and US Letter, and flag files for a Brother label printer.
permalink: /hardware/helpers/cable-labels/
author: barthel
og_image: https://assets.basically.website/sorter-docs/cable-label-strip-folded-full-7090ded43303.png
tools_needed: ["A printer, or a Brother label printer that takes 12 mm tape", "Clear tape such as Scotch tape, for the paper labels", "Scissors"]
---

Put a label with the cable's ID (`STP1`, `PWR2`, `RIB1` and so on) on **both ends** of every cable, close to the connector, before you route it. Print and cut all the labels before you start, then put each pair on as you plug that cable in, while both ends are still in reach. The one exception is the chute stepper (`CHU1`): its cable is fixed to the motor, so only its board end needs a label. Once a cable is behind a housing or strapped along the frame you cannot trace it by eye, and the four channel stepper leads (`STP1` to `STP4`) look identical.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/cable-label-strip-folded-full-7090ded43303.png" alt="Three drawings of one cable label, here with the ID PSU1. 1: the flat strip, a rectangle with the ID at each end, a blank section between them and a dashed fold line in the middle. 2: the strip folded round a cable seen end on, the two IDs together and sticking out. 3: the same label seen from the side on a cable, with the ID reading from either side.">
  <figcaption>One cable label, flat and folded round a cable. Every ID on the sheet looks like this. <cite>Drawn from the label sheet, not from a build, by Balloon.</cite></figcaption>
</figure>

The numbers follow the channels. The steppers are `STP1` to `STP4` for C1 to C4, and the camera lamps and cameras are `LED2` to `LED4` and `USB2` to `USB4` for C2 to C4. C1 has no lamp and no camera, so there is no `LED1` and no `USB1`.

## On paper

Download the labels for [A4](https://assets.basically.website/sorter-parts/sorter-v2-cable-labels-a4-6548b9ec1064.pdf) or for [US Letter](https://assets.basically.website/sorter-parts/sorter-v2-cable-labels-letter-7a4cf79aa057.pdf). The sheet has one section for each kind of cable: the wire pairs, the stepper leads, and the USB cables and ribbons. Each ID has two strips, one for each end, except `CHU1`, which has one. Use the strips for your cable's ID.

### Before you start

<ol class="numbered-steps">
  <li>Print the sheet at <strong>100% or Actual size</strong>, never Fit to Page. Measure the bar at the top to check: it is 100 mm (3.9 in) long, with a second mark at 3 in.</li>
  <li>Cover the printed side of the sheet with clear tape, such as Scotch tape. Overlap the pieces of tape by a few millimetres. Do this <strong>before you cut</strong>: plain paper does not last long on a cable, and tape makes the label like the laminated labels of a label printer. Let inkjet ink dry fully first, because it can smear under tape.</li>
  <li>Cut along the solid lines. Cut the sheet into rows first, then cut each row into strips.</li>
</ol>

### On each cable, as you plug it in

<ol class="numbered-steps">
  <li>Lay the cable across the dashed line in the middle of a strip, close to the connector.</li>
  <li>Fold the strip round the cable until the two IDs meet. They stick out like a flag, so the ID reads from either side.</li>
  <li>Press the two IDs together and hold them with a small piece of tape.</li>
</ol>

## With a Brother label printer

For the PT-P710BT, or another model that takes 12 mm tape, print the flags before you start. [Download the cable flags](https://assets.basically.website/sorter-parts/sorter-v2-cable-flags-brother-742f1dfce9c6.zip). The zip has nine P-touch Editor (`.lbx`) files. Each is short enough for the printer's 500 mm limit: the wire pairs in four files (`PSU1` to `PWR1`, `PWR2` to `LED2a`, `LED3a` to `LED2`, and `LED3` to `LIM1`), the stepper leads in two (`STP1` to `STP3`, and `STP4` to `CHU1`), the USB cables in two (`USB2` to `USB5`, and `USB6`), and the ribbons. Every file already has a flag for each end of each cable, and `CHU1` has one flag. Open the file for your cable, turn on Auto Cut in the print dialog and print it once. Fold each flag round the cable as in the three steps above, with the dashed line as the fold. If a flag is too tight or too loose, move the second ID along the flag in P-touch Editor.

## Another make of label printer

With a label printer of another make, or self-laminating wrap-around cable labels, use those instead and print the same IDs.

## Where it goes

Each lead page ends with this one in its own labelling step, and [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}) has you put the labels on as you plug each cable in. [Ordering the wire harness]({{ '/hardware/parts/harness-order/' | relative_url }}) has the ID of every cable.
