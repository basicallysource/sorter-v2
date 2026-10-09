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
tools_needed: [3D printer, Slicer]
---

Almost every structural part of the machine is printed, and printing is the longest
job in the build. Start it before the rest of the parts arrive.

Every printed part, its STL, its filament weight and its print time are on the
[parts calculator](https://parts-calculator.basically.website/). Set your layer count
there first, because that is what decides how many of each part you need.

## Filament

**Print the parts in PETG or ASA rather than PLA if the machine will stand anywhere
in warm or hot environments (in- and/or outdoors).** PLA softens from around 55 C,
and the printed gears the steppers drive through go first. The temperatures both
materials hold are on the
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

## Check how each part sits on the plate

**Not every STL is oriented for printing yet (as of 9 October 2026).** Many are
exported the way they were designed, not the way they print. This is a known
problem and the fix is tracked in
[issue #855](https://github.com/basicallysource/sorter-v2/issues/855). Until it is
fixed, check each part before you slice it.

<ol class="numbered-steps">
  <li><strong>Drop the part on the plate and look at what touches it.</strong> If it rests on a flat face, print it as it is.</li>
  <li><strong>If it balances on an edge or a corner, turn it.</strong> Use <strong>Place on face</strong> in Bambu Studio or Orca and pick the largest flat face. The bins are the clearest case. The ready made <a href="https://parts-calculator.basically.website/?tab=plates">bins plate</a> has them turned already.</li>
  <li><strong>If the part's card on the parts calculator has a Print orientation line, follow it.</strong> That line wins over everything above.</li>
  <li><strong>Not sure which face goes down?</strong> Ask on <a href="https://discord.gg/6PZtqkwtaS">Discord</a> with the part name.</li>
</ol>

<ul class="bulleted-list">
  <li><strong>Do not use auto orient.</strong> "Optimize orientation" and "auto rotate" in Bambu Studio, Orca and PrusaSlicer pick their own face. That can put a gear tooth or a bracket arm across the layer lines, where it snaps in use. Choose the face yourself with Place on face.</li>
  <li><strong>Moving a part is always fine.</strong> Slide it around the plate, or spin it flat (around Z). That does not change which face is down.</li>
  <li><strong>Parts import off centre, and some import below or above the plate.</strong> They are exported where they sit in the machine. Move the part onto the plate and carry on. That is normal and it is not a broken file.</li>
  <li><strong>The NEMA bracket needs a spin.</strong> It is 255.9 mm across as it comes and an A1 bed is 256 mm, so it slices with no room for a brim. Rotate it about 25 degrees flat on the plate and it clears with about 28 mm to spare.</li>
  <li><strong>Auto arrange is fine</strong> for packing several parts onto one plate. Check the plate afterwards and make sure nothing has been turned onto a different face.</li>
</ul>

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

**Print settings**, at the top of the
[parts calculator](https://parts-calculator.basically.website/), is the profile those
figures are sliced with: printer and nozzle, layer height, infill, supports, skirt
and filament.

There are also **[ready made build plates](https://parts-calculator.basically.website/?tab=plates)**
for some of the repeated parts, as 3MF projects you open and print. They print on
textured PEI, and each part row on the calculator says which plates it appears on.

## Planning the print

The filament and hours for a whole machine, and what the hours really mean once you
count plate changes, are on the
[Hardware overview]({{ '/hardware/' | relative_url }}). The short version: print early,
fill the plate, and print in the order you build so you can start assembling long
before the last part comes off.
