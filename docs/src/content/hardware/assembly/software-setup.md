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

Do this before you open the setup wizard. The wizard's Controller Discovery step only lists boards that already answer on USB serial, so a board with no firmware on it is invisible there and the step reports `No MCU buses found`.

With Sorter running, flash the feeder and distribution control boards from **Settings → Control board** in the Sorter UI: pick a release (or upload a `.uf2` directly) and flash it over the Pico's USB serial connection.

### A board that has never been flashed

A Pico with empty flash boots straight into its USB bootloader and appears as an `RPI-RP2` drive rather than a serial port, so there is nothing for the normal flash path to talk to. Use a recovery flash instead:

1. Plug **one** blank Pico into the Orange Pi. If it has been flashed before but is not responding, hold **BOOTSEL** while plugging it in.
2. In **Settings → Control board**, tick the **Recovery flash** checkbox (labelled "board is already in bootloader (RPI-RP2), or blank").
3. Pick the release asset for that board (feeder or distribution, matching your board revision) and flash.
4. Repeat for the second board.

The flash job finds the `RPI-RP2` drive and mounts it itself, so you do not need to mount anything by hand. One board at a time: a recovery flash writes to whichever board is in the bootloader, and it cannot tell two of them apart.

Once both boards are flashed and back on serial, run the setup wizard.

## Next

Continue in the [Sorter]({{ '/sorter/' | relative_url }}) section. [Your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }}) walks through picking a profile, feeding the machine, and checking a bin.
