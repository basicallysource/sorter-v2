---
layout: default
title: What is connected to the Orange Pi
type: explanation
section: lab
slug: lab-orange-pi
kicker: Design and research — Electronics
lede: Everything the Orange Pi 5 talks to, what each connection is for, and which part of the software handles it.
permalink: /lab/orange-pi/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
warning: >-
  **AI-generated first draft.** Written from the Pico firmware, the control program and the board's
  KiCad files, not from an actual build. The part names, pins and numbers are read from those files and
  have not been checked against a built machine.
---

The Orange Pi 5 is the machine's computer. It runs the machine's software: the control program (the backend), the web page you use to operate the machine, the camera processing, and the AI models that find and identify pieces. It has no screen or keyboard in the machine: you reach it from a browser on another device. Almost everything it talks to arrives over one USB cable, because the cameras and the Pico all sit behind a powered USB hub.

This page is the list of what connects to the Orange Pi and why. Power and USB each have their own page, linked below. Which socket each cable goes into is on [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

## The big picture

<ul class="bulleted-list">
  <li><strong>Power in:</strong> 5 V into the board's power USB-C socket, from a buck converter on the machine's 24 V supply. Details: <a href="{{ '/lab/power/' | relative_url }}">Power distribution</a>.</li>
  <li><strong>USB:</strong> one cable to a powered 4-port hub, with the Pico control board (see <a href="{{ '/lab/pico/' | relative_url }}">What is connected to the Pico</a>) and three cameras on it. Details: <a href="{{ '/lab/usb/' | relative_url }}">The USB connections and the hub</a>.</li>
  <li><strong>Network:</strong> Ethernet, or WiFi from an M.2 module or a USB adapter. This is how you reach the UI.</li>
  <li><strong>Storage:</strong> a microSD card that holds SorterOS and everything the machine saves.</li>
  <li><strong>Cooling:</strong> the board needs a fan on its processor (its main chip).</li>
  <li><strong>Not used:</strong> the video outputs, the camera ribbon connectors and the 26-pin header. The cameras are USB and the Pico is on USB, so nothing in the machine needs them.</li>
</ul>

## Network

The Orange Pi has a fast (gigabit) Ethernet port and no WiFi of its own. The machine works with a network cable alone. For WiFi you fit the optional M.2 WiFi module, or plug in a Linux-compatible USB WiFi adapter.

**The machine needs an internet connection to sort.** A cropped photo of each piece is sent to an online service, Brickognize, which identifies the part and its colour, and there is currently no way to sort without it. The photo is sent with no account and no machine identifier. The machine also sends a small status report to Basically once an hour. Every connection the machine can make, what each one carries and which ones can be turned off is listed on [What leaves the machine]({{ '/sorter/what-leaves-the-machine/' | relative_url }}).

The network is how you use the machine at all. On first boot SorterOS opens a setup network called `SorterOS-Setup` plus six characters, you join it from a phone and pick your WiFi, and from then on the UI is at `sorter.local` on that network. SorterOS keeps a small file that describes the current network state. The control program reads it, so that the machine's page on Hive (the online service the machines can connect to) can link to the machine wherever it is on the network now.

<ul class="bulleted-list">
  <li>WiFi options and the two kinds of M.2 slot: <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a></li>
  <li>First boot and joining WiFi: <a href="{{ '/sorter/installation/sorter-os/' | relative_url }}">Install the SorterOS image</a></li>
  <li>Reading the network state: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/machine_network.py"><code>machine_network.py</code></a></li>
</ul>

## Storage

Storage is the microSD card. SorterOS is written to it (this is called flashing), and the machine runs from it. The card should be 32 GB or larger and high-endurance, because the software writes to it all day.

The board has one M.2 socket, a slot for small add-on cards. It takes either an NVMe drive (a fast storage card) or the WiFi module, not both. The machine's documentation covers only the microSD card.

<ul class="bulleted-list">
  <li>Card requirements: <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a></li>
  <li>Flashing and first boot: <a href="{{ '/sorter/installation/sorter-os/' | relative_url }}">Install the SorterOS image</a></li>
  <li>Shutting down without damaging the card: <a href="{{ '/sorter/safe-shutdown/' | relative_url }}">Shutting down the machine</a></li>
</ul>

## Display, keyboard and debugging

None is needed. The machine is headless: you set it up and run it from a browser on another device, and you can log in over SSH (a secure remote text login) if you need a command line. The board has an HDMI socket for a screen and a 3-pin header for debugging, but nothing in the machine's design uses them.

<ul class="bulleted-list">
  <li>Setting up from a browser: <a href="{{ '/sorter/first-setup/' | relative_url }}">First setup</a></li>
  <li>When something does not appear: <a href="{{ '/sorter/troubleshooting/' | relative_url }}">Troubleshooting</a></li>
  <li>The housing: <a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi housing</a></li>
</ul>

## The NPU

The AI models that find pieces run on a part of the processor built for that job, the neural processing unit (NPU). This is the reason the Orange Pi 5 is the specified board. The NPU has three cores (three parts that work at the same time). The software that analyses the pictures gives each of the three camera channels its own core, always in the same order, so a channel uses the same core after every restart. The control program can also report which AI runtimes (the software that runs a model) the computer offers. The Orange Pi uses one called RKNN.

The same file can also check for a Hailo accelerator, an add-on AI chip that some other computers carry. No Hailo accelerator is part of the Orange Pi build.

<ul class="bulleted-list">
  <li>Channels and cores: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/perception/service.py"><code>perception/service.py</code></a></li>
  <li>Which runtimes are available: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/server/routers/runtimes.py"><code>server/routers/runtimes.py</code></a></li>
  <li>The detection models: <a href="{{ '/lab/object-detection/' | relative_url }}">Object detection</a></li>
</ul>

## Why the Orange Pi 5

<ul class="bulleted-list">
  <li><strong>The NPU is usable.</strong> Tests in <a href="https://discord.com/channels/1430279849171222682/1440488123279736912/1488654626264715395">March 2026</a> found the Orange Pi's NPU to be in the usable range, and concluded that the roughly 150 dollar Orange Pi is the platform because those NPUs can actually be used.</li>
  <li><strong>One board that can be recommended to everyone.</strong> At the <a href="https://www.youtube.com/watch?v=GRrVtKUC9TI">5 April 2026 meeting</a> the point was that a machine should have very few settings when somebody deploys it, so that an inexperienced builder does not run into problems nobody has seen. Once the Orange Pi was shown to be a stable way to run the detection models, it became the board the project could recommend across the board.</li>
  <li><strong>Why not a Raspberry Pi.</strong> At the same meeting the toolchain for the Raspberry Pi's AI add-on was called substantially difficult, and another attendee had not managed to compile and quantize a model for a Google Coral USB stick. A Raspberry Pi with the AI add-on was to be put online for benchmarking. No result of that comparison is on record.</li>
</ul>

## Cooling

The board gets hot when it is working hard, especially if a model ends up running on the CPU (the general-purpose part of the processor) instead of the NPU. At about 105 °C it shuts itself down to protect itself. The catalog lists the official heatsink fan, which plugs into the board's 5 V fan socket.

<ul class="bulleted-list">
  <li>Cooling notes: <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a></li>
</ul>

## Other computers

The Orange Pi 5 is the board SorterOS is built for. The software can also be installed on other Linux computers (Debian 12, Ubuntu 24.04, or Raspberry Pi OS on a Raspberry Pi 5) with the Linux installer.

<ul class="bulleted-list">
  <li><a href="{{ '/sorter/installation/linux-generic/' | relative_url }}">Install on Linux (generic)</a> and <a href="{{ '/sorter/installation/by-hand/' | relative_url }}">install by hand</a></li>
</ul>
