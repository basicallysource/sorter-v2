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

From here the order is:

<ol class="numbered-steps">
  <li><strong><a href="{{ '/sorter/first-setup/' | relative_url }}">First setup in the UI</a></strong>. The setup wizard: name the machine, find the boards, check motion and endstops, assign the servos and the cameras.</li>
  <li><strong><a href="{{ '/sorter/camera-calibration/' | relative_url }}">Camera calibration</a></strong>. Focus each camera against a printed chart.</li>
  <li><strong><a href="{{ '/sorter/chute-calibration/' | relative_url }}">Chute calibration</a></strong>. Teach the chute where your bins are.</li>
  <li><strong><a href="{{ '/sorter/before-first-sort-run/' | relative_url }}">Before your first sort run</a></strong>. The last five settings to check.</li>
  <li><strong><a href="{{ '/sorter/preparing-lego/' | relative_url }}">Preparing LEGO for a sort run</a></strong>. What to take out of a tub of bulk LEGO before it goes in.</li>
  <li><strong><a href="{{ '/sorter/tutorials/first-sort-run/' | relative_url }}">Your first sort run</a></strong>. Pick a profile, feed a handful of parts, watch them land.</li>
</ol>

## The finished result

The software installed, the board flashed, and the machine set up and sorting.

<div class="img-placeholder">Photo of the finished machine running, with the Sorter UI open on a phone or a laptop beside it.</div>
