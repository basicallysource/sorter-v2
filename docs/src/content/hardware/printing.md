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
  **First draft.** The printer table and the lists of parts that do not fit are measured
  from the published STLs. The printing advice around them is general practice, not a
  profile anybody has validated against a full set. Correct it as you print.
tools_needed: [3D printer, Slicer]
---

Almost every structural part of the machine is printed, and printing is the longest
job in the build. Start it before the rest of the parts arrive.

Every printed part, its STL, its filament weight and its print time are on the
[parts calculator](https://parts-calculator.basically.website/). Set your layer count
there first, because that is what decides how many of each part you need.

## The printer

**The parts are designed to a 256 x 256 mm bed.** Nothing in the catalog is larger
than that, so a bigger printer buys you nothing here. A smaller one means some parts
you cannot print at all.

The machine needs **107 different printed designs**, not counting the bins, which are
optional and which you can also cut from cardboard.

| Printer | Bed (mm) | Designs that fit | Will not fit |
|---|---|---|---|
| Bambu Lab A1, P1S, X1C | 256 x 256 x 256 | 107 | 0 |
| Prusa MK4S | 250 x 210 x 220 | 97 | 10 |
| Creality Ender-3 V3 | 220 x 220 x 250 | 97 | 10 |
| Bambu Lab A1 mini | 180 x 180 x 180 | 88 | 19 |

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

**Supports are off for almost everything.** Five parts need them, and the parts
calculator badges each one **Supports**:

- Stator
- Light post
- Light post cap
- Cable clamp (inner)
- Cable clamp (outer)

Turn support on for those, `normal (auto)`, with the overhang threshold at 10
degrees. That is what the filament weights on the calculator assume.

For everything else, look at the sliced preview rather than the warning. Some parts
have small overhangs that make a slicer complain, and they print fine. If you can see
a feature that genuinely starts in mid air, switch support on for that part and
reslice.

## Check before you press print

A plate of these parts can run ten hours or more, so spend two minutes on it first.

<ol class="numbered-steps">
  <li><strong>The right printer and plate are selected</strong>, and the plate in the slicer is the one actually in the machine. Textured PEI is what the pre-arranged plates use.</li>
  <li><strong>The whole part is inside the bed, brim included.</strong> A part that sticks out is greyed out or flagged by the slicer, but a brim that hangs over the edge often is not.</li>
  <li><strong>Slice, then scrub through the preview.</strong> Look at the first layer for gaps, and run up through the part looking for anything printing on nothing.</li>
  <li><strong>Check the time and the filament.</strong> If your figure is wildly different from the calculator's, something in the profile is not what you think it is.</li>
  <li><strong>Print one before you print twelve.</strong> This matters most for the <strong>External bracket (side)</strong>, which is a tight fit around the 2020 extrusion and is badged <strong>Tight fit</strong> on the calculator. Print one, fit it on a piece of extrusion, then commit to the set.</li>
</ol>

**Change settings and slice again as often as you like.** Reslicing costs nothing.
Running a 14 hour print you were unsure about costs a day.

The calculator's figures are sliced with a 0.4 mm nozzle, 0.2 mm layers, 15% infill,
in PLA. Treat those as the baseline rather than a requirement. Your own profile for
your own printer will be better than a copied one.

There are also **[ready made build plates](https://parts-calculator.basically.website/?tab=plates)**
for some of the repeated parts, as 3MF projects you open and print. Each part row on
the calculator says which plates it appears on.

## The first layer

Stay with the printer for the first layer of every plate. Nearly everything that goes
wrong on a long print is already visible there.

**Before a big plate**, run the printer's bed levelling, and clean the plate with warm
water and dish soap, then dry it. Fingerprints and grease are the usual reason a part
lets go, and wiping with alcohol alone spreads them.

What you are looking at, and what to do:

- **Lines with gaps between them**, or the part peeling as it prints: the nozzle is
  too far from the plate. Lower the Z offset a little, in steps of 0.02 mm.
- **A rough, scratchy first layer** with plastic pushed out at the sides: the nozzle
  is too close. Raise the Z offset the same way.
- **A corner lifting.** The big flat parts are where this bites, and several of them
  are 240 to 250 mm across. Add a brim, raise the bed temperature by 5 C, and keep
  the printer out of a draught. An open printer next to an open window will lift
  corners no setting can fix.
- **The first layer is down but the edges are spread wider than the rest of the
  part** (elephant's foot). Turn on elephant foot compensation in the slicer. It
  matters where a part has to sit flat or a hole has to stay round.
- **It did not stick at all.** Stop the print. There is nothing to be gained by
  letting it run, and a ball of filament dragged around the plate can take the
  nozzle with it.

If you are printing in PETG or ASA, keep the printer somewhere still and warm.
Those materials lift more than PLA, and a five layer set has been printed in PETG
successfully.

## Planning the print

The filament and hours for a whole machine, and what the hours really mean once you
count plate changes, are on the
[Hardware overview]({{ '/hardware/' | relative_url }}). The short version: print early,
fill the plate, and print in the order you build so you can start assembling long
before the last part comes off.
