---
layout: default
title: Soldering Pico headers
type: how-to
section: hardware
slug: helper-pico-headers
kicker: Helpers — Soldering Pico headers
lede: Soldering 2.54 mm header pins to the Raspberry Pi Pico so it can seat in the control board.
permalink: /hardware/helpers/pico-headers/
author: barthel
contributors: [spencer]
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=pico-headers), not from
  an actual build. The parts and quantities are real. The procedure is not recorded anywhere and
  no step here has been checked against a build, so the steps below are placeholders with the
  gaps marked.
parts_needed:
  - part: mcu-rpi-pico
    qty: 1
  - part: header-pins-254
    qty: 40
---

The Pico ships bare. The [basically Embedded Control Board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}) expects it on 2.54 mm headers, so the pins are a separate purchase and a soldering job before the board goes on its mount.

One Pico per machine, needing 40 header pins total: break a breakaway strip into two rows of 20. It is the only assembly in the parts tree recorded as soldered: every pin goes into the Pico's through-holes, nothing here presses or clips together.

{% include step.html n="1" title="Preparation" %}

Break the header strip into two rows of 20. Nothing here takes a heat insert.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Solder the headers to the Pico" %}

Solder the headers so the Pico's USB port ends up facing the edge of the control board once seated (see [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }})). Dry-fit the bare Pico against the board's sockets first to confirm which face the pins go on — it's very difficult to desolder and redo.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Seat it in the board" %}

Push the Pico into its socket on the basically Embedded Control Board, then carry on with the [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}).

The Pico is now ready. Flashing its firmware is covered in [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).
