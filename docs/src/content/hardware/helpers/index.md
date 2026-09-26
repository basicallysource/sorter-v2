---
layout: default
title: Helpers
type: landing
section: hardware
slug: helpers
kicker: Hardware — Helpers
lede: One-time prep for parts used in multiple places on the machine. The assembly steps link here instead of repeating the procedure.
permalink: /hardware/helpers/
author: spencer
contributors: [barthel]
---

Nothing here is a stage of the build. Each page is one job you do once, on a part
that several later steps need, and the step that needs it links straight to it.
So read these when a page sends you, not in order.

## Using a tool

- **[Using a multimeter]({{ '/hardware/helpers/multimeter/' | relative_url }})**. Continuity, resistance and DC volts, the three checks the pages below ask for. Each one links straight to the check it needs.

## Preparing a bought part

- **[Installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }})**. Pressing brass threads into printed parts, with a soldering iron or an insert press. The most-used page here: eight assembly steps call for it.
- **[Fitting T-nuts]({{ '/hardware/helpers/t-nuts/' | relative_url }})**. How the M5 T-nuts go into the aluminum extrusion, and what changes if you bought the cheaper style.
- **[Preparing the Lazy Susan]({{ '/hardware/helpers/lazy-susan/' | relative_url }})**. Pulling the rubber feet off the bearing, if yours came with them.
- **[Preparing the 20-tooth timing pulley]({{ '/hardware/helpers/pulley-gear-mod/' | relative_url }})**. Removing the top flange so the pulley fits the interface gear.
- **[Soldering Pico headers]({{ '/hardware/helpers/pico-headers/' | relative_url }})**. **Optional.** The parts list buys a Pico with its pins already on, so a standard build skips this page.

## Making a cable

Seven of the machine's cables are made by hand, one page each. The eighth, the
USB hub's 24 V lead, is bought ready made with a plug at both ends.

- **[Preparing the LED strip]({{ '/hardware/helpers/led-strip/' | relative_url }})**. Cutting a lamp's length of strip and getting its cable on the end, clamped or soldered. Three per machine.
- **[Make your own PSU output pigtail]({{ '/hardware/helpers/psu-pigtail/' | relative_url }})**. The barrel jack and its two fork terminals, for each of the PSU box's three outputs. Three per machine.
- **[Make the control board's 24 V lead]({{ '/hardware/helpers/board-24v-lead/' | relative_url }})**. Barrel plug at the PSU, JST-VH at the board. The one lead no supplier sells.
- **[Make the Orange Pi's 24 V lead]({{ '/hardware/helpers/pi-24v-lead/' | relative_url }})**. A barrel plug onto the buck converter's own input wires. The shortest of the three.
- **[Make the channel stepper leads]({{ '/hardware/helpers/channel-stepper-lead/' | relative_url }})**. The four c-channel motor leads. The lead in the motor's box cannot be used as it comes. Four per machine.
- **[Make the chute stepper lead]({{ '/hardware/helpers/chute-stepper-lead/' | relative_url }})**. The chute motor has bare flying leads, so this one gets a tail and a housing.
- **[Make the chute limit switch lead]({{ '/hardware/helpers/limit-switch-lead/' | relative_url }})**. Push-on tabs at the switch, a keyed 3-pin housing at the board. Nothing soldered.

Every socket these leads plug into is on [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), and the drawings and lengths are on [ordering the wire harness]({{ '/hardware/parts/harness-order/' | relative_url }}).
