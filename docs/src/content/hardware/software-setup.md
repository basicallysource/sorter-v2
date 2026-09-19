---
layout: default
title: Software setup
type: how-to
section: hardware
slug: hardware-software-setup
kicker: Hardware — Software setup
lede: The physical build is finished. Install the software, then carry on in the Sorter section.
permalink: /hardware/software-setup/
author: spencer
---

The machine is built. Everything is printed, bolted, wired and plugged in, and nothing more is added to it by hand. What is left is software, and all of it lives in the [Sorter]({{ '/sorter/' | relative_url }}) section.

## 1. Install Sorter on the Pi

[Installation]({{ '/sorter/installation/' | relative_url }}) has three routes: **SorterOS**, the pre-built image and the recommended one for the Orange Pi 5; the **one-command installer** for generic Linux; and the **by-hand** sequence for anything else. Each ends the same way, with the Sorter UI open in a browser and the first-boot setup wizard waiting.

## 2. Flash the control board before the wizard

The board needs its firmware before the wizard can see it. Controller Discovery only lists boards that already answer on USB serial, so a board with nothing on it is invisible there and the step reports `No MCU buses found`.

With Sorter running, flash it from **Settings** &rarr; **Control board**: pick a release (or upload a `.uf2` directly) and flash it over the Pico's USB serial connection. A board that has never been flashed is a special case, because it enumerates as an `RPI-RP2` drive rather than a serial port and needs the **Recovery flash** option instead. [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}) has those steps.

## 3. Carry on in Sorter

From here the order is the setup wizard in the UI, then [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}), then [chute calibration]({{ '/sorter/chute-calibration/' | relative_url }}), then [before your first sort run]({{ '/sorter/before-first-sort-run/' | relative_url }}) and [your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }}).
