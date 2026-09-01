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
  **Mixed.** The two control board pages come from a real build. The PSU box and Orange Pi mount
  pages are AI-generated first drafts written from the [parts
  calculator](https://parts-calculator.basically.website/assembly), not from a build: the parts
  are real, the steps are not checked. Gaps are marked in place. Correct them as you build.

  One of these steps (PSU box) involves wiring mains voltage. Read it fully before starting, and
  keep the unit unplugged while you work on it.
---

The [wire harness]({{ '/hardware/electronics/' | relative_url }}) pages cover what connects to what. These cover the other half: where the hardware physically sits and what holds it there. "The control board" here means basically board v1.3, the basically Embedded Control Board; the three sections below call their own printed enclosure a housing, a box, and a mount, but they're the same kind of part, one per component, bolted to the frame.

Each of the three printed enclosures bolts to the 2020 frame with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws (6 total). They are self-tapping: there are no {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %} at any of these six points.

All three go on the same plane: the [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}) that belongs to the top interface, the one lowered onto the interface assembly at [step 13]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-13) of the top interface build. The render below is that frame seen from above, and the chute stepper is the landmark to place the three enclosures against.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/electronics-component-layout-topdown-full-2d38b86c4b2e.jpg" alt="Top-down physical component layout on the machine, with the PSU, Pi, basically board, USB hub, Pico, chute stepper and ribbon run called out">
  <figcaption>Where everything sits, top-down. This render is the record of the placement; the chute stepper is drawn slightly further out than it really sits, to keep the callouts readable. <cite>Render: Spencer.</cite></figcaption>
</figure>

Solder the [Pico headers]({{ '/hardware/helpers/pico-headers/' | relative_url }}) first, a one-time prep step under [Helpers]({{ '/hardware/helpers/' | relative_url }}); the Pico won't seat in the control board without it. Then:

1. **[PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }})**: the printed enclosure around the Mean Well LRS-350-24.
2. **[Preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }})**: the five stepper drivers, the Pico, and the jumpers that address the drivers.
3. **[Control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }})**: the printed housing the board closes into, with its fan.
4. **[Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }})**: Orange Pi 5 on standoffs.

Wiring follows on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page, then [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).

## What is not recorded yet

Collected here rather than left on the individual pages, because these are the things that block finishing them.

- **Cooling the Orange Pi.** The control board's fan is answered: it sits in the housing cover and runs off a GPIO-switched 24 V port on the board itself. How the Pi's fan is powered is still open (open item 1 on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page).
