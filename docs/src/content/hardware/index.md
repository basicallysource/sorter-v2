---
layout: default
title: Hardware
type: landing
section: hardware
slug: hardware
kicker: The Physical Machine
lede: The size of the build, what it costs in parts and printing time, and where the assembly instructions are.
permalink: /hardware/
author: spencer
---

The machine is still in active development. Pages under Assembly and
Electronics range from steps verified on a built machine to unverified first
drafts; each page states its own status.

## Before you order anything

You can build this on a bench in a garage. It does not need a workshop, and
nothing in it is hard on its own.

It is a long build. The parts count runs into the thousands and the printing
runs into months, so read this page before you buy filament. The point is not
to put you off. It is so you plan for the right size of job.

## You choose how tall the machine is

The machine is a stack of layers. **Each layer holds 18 sorting bins**, or 12
larger ones if you pick the wider bin size. More layers means more bins, so more
different parts the machine can sort in one pass, a taller tower, and more of
everything to build.

Everything above and below the stack is the same whatever height you pick: one
feeder, one top interface, one chute, one set of electronics. That is why the
first layer costs far more work than the fifth.

Three and five layers are the two common choices.

**A 5 layer machine stands 1270 mm (4 ft 2 in) from the floor to the top
plate**, and 1772 mm (5 ft 10 in) to the top of the bulk bucket sitting above
it. Each layer you add or leave off moves both figures by 160 mm (6.3 in), so a
3 layer machine is 950 mm (3 ft 1 in) to the top plate and 1452 mm (4 ft 9 in)
overall. Check the space before you choose a height: the bulk bucket is the
highest point of the machine and it is where you pour the LEGO in, so you have
to be able to reach into it.

## What each size costs you

The table below uses 18 bins per layer.

| | **3 layers** | **5 layers** |
|---|---|---|
| Sorting bins | {{ site.data.build_scale.small.bins }} | {{ site.data.build_scale.large.bins }} |
| 3D printed parts | {{ site.data.build_scale.small.printed }} | {{ site.data.build_scale.large.printed }} |
| Different printed designs | {{ site.data.build_scale.small.designs }} | {{ site.data.build_scale.large.designs }} |
| Filament | {{ site.data.build_scale.small.printed_kg }} kg | {{ site.data.build_scale.large.printed_kg }} kg |
| Printing, one printer | {{ site.data.build_scale.small.printed_hours }} h | {{ site.data.build_scale.large.printed_hours }} h |
| Screws | {{ site.data.build_scale.small.screws }} | {{ site.data.build_scale.large.screws }} |
| Heat inserts | {{ site.data.build_scale.small.heat_inserts }} | {{ site.data.build_scale.large.heat_inserts }} |
| T-nuts | {{ site.data.build_scale.small.tnuts }} | {{ site.data.build_scale.large.tnuts }} |
| Other hardware | {{ site.data.build_scale.small.other }} | {{ site.data.build_scale.large.other }} |
| Electrical parts | {{ site.data.build_scale.small.electrical }} | {{ site.data.build_scale.large.electrical }} |
| Aluminium pieces | {{ site.data.build_scale.small.extrusion }} | {{ site.data.build_scale.large.extrusion }} |
| Laser cut parts | {{ site.data.build_scale.small.lasercut }} | {{ site.data.build_scale.large.lasercut }} |
| **Parts in total** | **{{ site.data.build_scale.small.total }}** | **{{ site.data.build_scale.large.total }}** |

Bins are not in those totals. They are optional and you print them last: a
3 layer tower takes {{ site.data.build_scale.small.bins }} printed bins
({{ site.data.build_scale.small.bins_kg }} kg,
{{ site.data.build_scale.small.bins_hours }} h) and a 5 layer tower takes
{{ site.data.build_scale.large.bins }}
({{ site.data.build_scale.large.bins_kg }} kg,
{{ site.data.build_scale.large.bins_hours }} h). You can also cut them from
cardboard, or use boxes you already own. See
[Install the bins]({{ '/hardware/assembly/install-bins/' | relative_url }}).

Two layers cost you about 130 more printed parts and 200 more screws. Compare
that with a 1 layer machine, which already needs most of the build. **The tower
is the cheap part. The machine around it is the work.**

Every number above is read from the [parts
catalog](https://parts-calculator.basically.website/) when this page is built,
so it follows the catalog as parts change. For your own layer count, set it
there and the catalog lists exactly what to buy and print.

## What the print figures mean

The filament and time figures come from the catalog, sliced on
**{{ site.data.build_scale.printer }}**, profile
**{{ site.data.build_scale.process }}**, in
**{{ site.data.build_scale.filament }}** at
{{ site.data.build_scale.infill }} infill. Your own printer and profile will
differ.

**Treat the hours as a floor, not a plan.** They assume each part printed on
its own plate, back to back, with nobody waiting. A real build runs about twice
as long, and the extra is not the printer. It is the hours the printer stands
finished because nobody is there to change the plate.

A 5 layer set of parts has been printed on one Bambu A1 in **about three
months**, running five days a week including overnight, in PETG. Almost all the
lost time was waiting for a plate change.

So, if you are planning:

- **Start printing early.** Print while you are still sourcing the rest.
- **Fill the plate.** Printing several small parts together is what turns the
  theoretical hours into real ones.
- **Print in the order you build.** The
  [Assembly]({{ '/hardware/assembly/' | relative_url }}) sections are in build
  order, so you can start assembling long before the last part is printed.

**Which printer you need, how to place a part on the plate and what to check before
a long print** are on [Printing the parts]({{ '/hardware/printing/' | relative_url }}).
The parts are designed to a 256 x 256 mm bed, and a smaller one cannot print all of
them.

## Intended operating conditions

Indoors, out of direct sun, in a room you would be comfortable working in.
Nobody has tested a limit, so the two cases worth planning for are these.

**Too hot** (a shed, a garage, any room without air conditioning):

- **Print the parts in PETG or ASA, not PLA.** PLA softens from around 55 C
  (131 F), and the printed gears the steppers drive through go first. PETG
  holds to around 80 C (176 F), and a full 5 layer set has already been
  printed in it.
- **Cool the Orange Pi.** It shuts down at about 105 C (221 F). See
  [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}).
- Working figure: up to about 40 C (104 F) in PLA, and 45 to 50 C (113 to
  122 F) in PETG.

**Damp mornings** (a humid climate, or a space that cools down overnight):

- **Do not switch the machine on while any part of it feels cold to the touch
  or looks wet.** Let it reach room temperature first. The power supply is
  rated for 20 to 90% humidity, provided no water forms on it.

## Two things you may not be able to make yourself

- **Aluminium extrusion.** A 5 layer machine needs
  {{ site.data.build_scale.large.extrusion_m }} m of 2020 extrusion, cut into
  {{ site.data.build_scale.large.extrusion }} pieces in
  {{ site.data.build_scale.large.extrusion_lengths }} different lengths. If you
  have no saw, order it cut to length: many extrusion suppliers cut to order for
  a small fee per cut. The [framing cut
  list](https://parts-calculator.basically.website/framing) has every length and
  a plan for packing them into standard bars.
- **The laser cut parts.** The top plate and the two cable cage plates are cut
  from flat sheet. A local maker space or an online cutting service will cut
  them from the files. The cardboard bins, if you choose those, need a laser too.

## Keep track of what you have

Parts arrive over several weeks, in the thousands. It is easy to lose track of
what you already have. Label the screw sizes as they arrive, and keep the
printed parts sorted by the assembly they belong to. Every assembly page lists
the exact parts and fasteners for that step, so sorting them that way pays for
itself.

## Where to go next

- **[Printing the parts]({{ '/hardware/printing/' | relative_url }})**: what printer the parts need, orientation, supports, and the slicer checks worth doing before a long print.
- **[Assembly]({{ '/hardware/assembly/' | relative_url }})**: the build order, structured like a set of instructions. Electronics is part of this same build order (see its order of operations), not a separate track.
- **[Electronics]({{ '/hardware/electronics/' | relative_url }})**: the [wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) and the stepper pinout, [installing the electronics]({{ '/hardware/electronics/installation/' | relative_url }}), and [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).
- **[Software setup]({{ '/hardware/software-setup/' | relative_url }})**: the last step of the build, where the finished machine hands off to installing the software and the [Sorter]({{ '/sorter/' | relative_url }}) section.
- **[Parts]({{ '/hardware/parts/' | relative_url }})**: reference pages for individual parts, like the Lazy Susan bearing, and [ordering the wire harness]({{ '/hardware/parts/harness-order/' | relative_url }}).
- **[Bill of materials](https://parts-calculator.basically.website/hardware)**: every part, with sources and part numbers.
