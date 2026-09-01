---
layout: default
title: Software setup
type: how-to
section: hardware
slug: assembly-software-setup
kicker: Assembly — Software setup
lede: Flash and configure the machine, then continue in the Sorter section.
permalink: /hardware/assembly/software-setup/
author: spencer
---

Once the hardware is built, set up the software. This stage flashes SorterOS onto the Orange Pi 5 and the control board firmware onto the Pico controllers, turning the assembled hardware into a machine the Sorter software can actually run on.

## Flash SorterOS

Go to [Installation]({{ '/sorter/installation/' | relative_url }}) and pick SorterOS (the recommended path for the Orange Pi 5), the one-command Linux installer, or the manual by-hand sequence. This gets the Pi booted and the Sorter backend and UI running.

## Flash the control boards

With Sorter running, flash the feeder and distribution control boards from **Settings → Control board** in the Sorter UI: pick a release (or upload a `.uf2` directly) and flash it over the Pico's USB serial connection.

## Next

Continue in the [Sorter]({{ '/sorter/' | relative_url }}) section. [Your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }}) walks through picking a profile, feeding the machine, and checking a bin.
