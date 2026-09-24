---
layout: default
title: Printing the parts
type: how-to
section: hardware
slug: printing
kicker: Hardware — Printing
lede: What printer the parts need, how to place them on the plate, when supports go on, and what to check before you start a print that runs overnight.
permalink: /hardware/printing/
author: brickcyclealice
warning: >-
  **AI-generated first draft.** Written from the published STLs and the parts catalog,
  not from a printed set.
tools_needed: [3D printer, Slicer]
---

Almost every structural part of the machine is printed, and printing is the longest
job in the build. Start it before the rest of the parts arrive.

Every printed part, its STL, its filament weight and its print time are on the
[parts calculator](https://parts-calculator.basically.website/). Set your layer count
there first, because that is what decides how many of each part you need.

## Filament

**Print the parts in PETG or ASA rather than PLA if the machine will stand anywhere
warm**, meaning a shed, a garage, or any room without air conditioning. PLA softens
from around 55 C, and the printed gears the steppers drive through go first. The
temperatures both materials hold are on the
[Hardware overview]({{ '/hardware/' | relative_url }}#intended-operating-conditions).

## The printer

**The parts are designed to a 256 x 256 mm bed.** Nothing in the catalog is larger
than that, so a bigger printer buys you nothing here. A smaller one means some parts
you cannot print at all.

The machine needs **107 different printed designs**, not counting the bins, which are
optional and which you can also cut from cardboard.

- **Bambu Lab A1, P1S, X1C**, 256 x 256 x 256 mm: all 107.
- **Prusa MK4S**, 250 x 210 x 220 mm: 97.
- **Creality Ender-3 V3**, 220 x 220 x 250 mm: 97.
- **Bambu Lab A1 mini**, 180 x 180 x 180 mm: 88.

A smaller bed loses the largest parts: the feeder's stators and rotors, the interface
plates, the Lazy Susan base. Several of those are needed four times over, so it is
not one awkward part.

If your printer cannot do the whole set, print what it can and have the rest printed
by somebody else or by a print service. The parts calculator has the STL for every
one of them.

## Calibrate the printer first

Some parts fit against something else with almost no room. The external brackets
clamp around the 2020 extrusion, bearings press into printed seats, and heat inserts
go into holes sized for them. A printer that is slightly out prints those too tight
or too loose while every other part on the plate still looks fine.

Run the printer's own calibration before the first plate, and run it again when you
change filament or nozzle. Bed levelling, flow ratio and pressure advance are the
settings that move a printed dimension, and both Bambu Studio and Orca can test flow
and pressure advance for one filament in a few minutes. Dialling those in once is
worth more than any profile you copy from somebody else.

## Print each part the way the file comes

**Every STL is already sitting the way it should print.** Drop it on the plate as it
is and slice it.

- **Do not use auto orient.** "Optimize orientation", "auto rotate" and the orient
  tools in Bambu Studio, Orca and PrusaSlicer will lay parts down on a different
  face. The face a part prints on is a design decision that is already made, and
  changing it is how a gear tooth or a bracket arm ends up printing across the layer
  lines and snapping in use.
- **Moving a part is fine. Turning it over is not.** Sliding it around the plate,
  dropping it onto the plate and spinning it flat (around Z) all leave the printing
  face alone. Anything that tips it onto another face does not.
- **Parts import off centre, and some import below or above the plate.** They are
  exported in the coordinates they occupy in the machine, so the slicer puts them
  where the assembly puts them. Move it onto the plate and carry on. That is normal
  and it is not a broken file.
- **The NEMA bracket needs a spin.** It is 255.9 mm across as it comes and an A1 bed
  is 256 mm, so it slices with no room for a brim. Rotate it about 25 degrees flat on
  the plate and it clears with about 28 mm to spare.
- **Auto arrange is fine** for packing several parts onto one plate, as long as it
  only slides and spins them. Check the plate afterwards and make sure nothing has
  been turned over.

If a part looks like it wants turning, do not turn it. Ask on
[Discord](https://discord.gg/6PZtqkwtaS) first, because a part sitting wrong in the
file is a fault worth fixing for everybody.

## Supports

**Supports are off for almost everything.** A handful of parts need them, and the
[parts calculator](https://parts-calculator.basically.website/) badges each one
**Supports**. Check the part there before you slice it.

Turn support on for those, `normal (auto)`, with the overhang threshold at 10
degrees. That is what the filament weights on the calculator assume.

For everything else, look at the sliced preview rather than the warning. Some parts
have small overhangs that make a slicer complain, and they print fine. If you can see
a feature that genuinely starts in mid air, switch support on for that part and
reslice.

## Check before you press print

A plate of these parts can run ten hours or more, so two things before you start it.

<ol class="numbered-steps">
  <li><strong>Check the slicer's time and filament against the calculator.</strong> If your figure is wildly different, something in the profile is not what you think it is.</li>
  <li><strong>Print one before you print twelve.</strong> This matters most for the <strong>External bracket (side)</strong>, which is a tight fit around the 2020 extrusion and is badged <strong>Tight fit</strong> on the calculator. Print one, fit it on a piece of extrusion, then commit to the set.</li>
</ol>

The calculator's figures are sliced with a 0.4 mm nozzle, 0.2 mm layers, 15% infill,
in PLA.

There are also **[ready made build plates](https://parts-calculator.basically.website/?tab=plates)**
for some of the repeated parts, as 3MF projects you open and print. They print on
textured PEI, and each part row on the calculator says which plates it appears on.

## Planning the print

The filament and hours for a whole machine, and what the hours really mean once you
count plate changes, are on the
[Hardware overview]({{ '/hardware/' | relative_url }}). The short version: print early,
fill the plate, and print in the order you build so you can start assembling long
before the last part comes off.
