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
  **Mixed.** The two control board pages come from a real build. The PSU box, Orange Pi mount
  and Soldering Pico headers pages are AI-generated first drafts written from the [parts
  calculator](https://parts-calculator.basically.website/assembly), not from a build: the parts
  are real, the steps are not checked. Gaps are marked in place. Correct them as you build.
---

The [wire harness]({{ '/hardware/electronics/' | relative_url }}) pages cover what connects to what. These cover the other half: where the hardware physically sits and what holds it there.

The PSU, the control board and the Orange Pi each live in their own mount, and all three bolt to the machine's 2020 frame with 2 M5 screws each, six in total: {% include fastener.html size="M5" variant="socket-button" length="12" %} for the PSU box and the Orange Pi mount, {% include fastener.html size="M5" variant="socket-button" length="16" %} for the control board housing.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/electronics-component-layout-topdown-full-2d38b86c4b2e.jpg" alt="Top-down physical component layout on the machine, with the PSU, Pi, basically board, USB hub, Pico, chute stepper and ribbon run called out">
  <figcaption>Where everything sits, top-down. This render is currently the only record of the placement. Render: Spencer.</figcaption>
</figure>

1. **[Soldering Pico headers]({{ '/hardware/electronics/installation/pico-headers/' | relative_url }})**: soldering the header pins so the Pico can seat in the control board. First, while the board is still loose.
2. **[PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }})**: the printed enclosure around the Mean Well LRS-350-24.
3. **[Preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }})**: the five stepper drivers, the Pico, and the jumpers that address the drivers.
4. **[Control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }})**: the printed housing the board closes into, with its fan.
5. **[Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }})**: Orange Pi 5 on standoffs.

Wiring follows on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page, then [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).

## What is not recorded yet

Collected here rather than left on the individual pages, because these are the things that block finishing them.

- **The Orange Pi's printed bracket is not in the parts registry.** No STL, no render, no print settings. The control board's housing is, as of v2.
- **Where on the frame each mount goes.** The photo above is the whole record. Which extrusion, which face, and which way round are not written down.
- **Cooling the Orange Pi.** The control board's fan is answered: it sits in the housing cover and runs off a GPIO-switched 24 V port on the board itself. How the Pi's fan is powered is still open (open item 1 on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page).
