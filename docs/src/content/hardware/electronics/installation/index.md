---
layout: default
title: Installing the electronics
type: landing
section: hardware
slug: electronics-installation
kicker: Electronics — Installation
lede: Where the PSU, the control board and the Orange Pi mount on the machine. Build in this order.
permalink: /hardware/electronics/installation/
author: barthel
contributors: [spencer]
warning: >-
  **AI-generated first drafts.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly), not from an actual build.
  These four pages exist so the gap is visible and fillable, not because the steps are written.
  The parts on each come from the calculator, which records what every mount is made of; the
  assembly order, the orientation and most of the screw sizes are recorded nowhere, so each gap
  is marked in place rather than guessed at. Correct them as you build.
---

The [wire harness]({{ '/hardware/electronics/' | relative_url }}) pages cover what connects to what. These cover the other half: where the hardware physically sits and what holds it there.

The PSU, the control board and the Orange Pi each live in their own mount, and all three bolt to the machine's 2020 frame with 2 <span class="fastener-todo">M5, length not recorded</span> screws each, six in total.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/electronics/component-layout-topdown.2d38b86c4b2e4d05.jpg" alt="Top-down physical component layout on the machine, with the PSU, Pi, basically board, USB hub, Pico, chute stepper and ribbon run called out">
  <figcaption>Where everything sits, top-down. This photo is currently the only record of the placement.</figcaption>
</figure>

1. **[Pico headers]({{ '/hardware/electronics/installation/pico-headers/' | relative_url }})**: soldering the header pins so the Pico can seat in the control board. First, while the board is still loose.
2. **[PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }})**: the printed enclosure around the Mean Well LRS-350-24.
3. **[Control board mount]({{ '/hardware/electronics/installation/control-board-mount/' | relative_url }})**: basically Embedded Control Board v1.3 on standoffs.
4. **[Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }})**: Orange Pi 5 on standoffs.

Wiring follows on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page, then [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).

## What is not recorded yet

Collected here rather than left on the individual pages, because these are the things that block finishing them.

- **The printed brackets for the control board and the Orange Pi are not in the parts registry.** The calculator lists the board, the standoffs, the inserts and the screws, but not the part each one stands off. No STL, no render, no print settings.
- **Screw lengths.** The six M5s that hold the mounts to the frame and the eight M3s in the two board mounts are placeholders. Measure one on a built machine.
- **Where on the frame each mount goes.** The photo above is the whole record. Which extrusion, which face, and which way round are not written down.
- **Cooling.** The Pi and the board end up in enclosures with no airflow other than a fan, and how the fans are powered is still open (open item 1 on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page).
- **Whether the two housings and the two mounts are the same thing.** The calculator carries an Orange Pi 5 Housing and an Embedded Control Board Housing as separate, empty assemblies alongside the two mounts. Somebody who knows the CAD needs to say whether those are the missing brackets or a different design.
