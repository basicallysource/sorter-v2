---
layout: default
title: What is connected to the Orange Pi
type: explanation
section: design
slug: design-orange-pi
kicker: Design — Electronics
lede: Everything the Orange Pi 5 talks to, what each connection is for, and which part of the software handles it.
permalink: /design/orange-pi/
last_verified: 2026-10-10
---

The Orange Pi 5 is the machine's computer. It runs the backend, the web UI, the camera pipeline and the detection models. It has no screen or keyboard in the machine: you reach it from a browser. Almost everything it talks to arrives over one USB cable, because the cameras and the Pico all sit behind a powered USB hub.

This page is the whole list of what connects to the Orange Pi and why. Which socket each cable goes into is on [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}). The USB side in detail is on [The USB connections and the hub]({{ '/design/usb/' | relative_url }}).

## The big picture

<ul class="bulleted-list">
  <li><strong>Power in:</strong> 5 V into the board's power USB-C socket, made from the machine's 24 V supply by a small buck converter.</li>
  <li><strong>USB:</strong> one cable to a powered 4-port hub. On the hub: the Pico control board and three cameras.</li>
  <li><strong>Network:</strong> Ethernet, or WiFi from an M.2 module or a USB adapter. This is how you reach the UI.</li>
  <li><strong>Storage:</strong> a microSD card that holds SorterOS and everything the machine saves.</li>
  <li><strong>Cooling:</strong> the board needs a fan on the processor.</li>
  <li><strong>Not used:</strong> the video outputs, the camera ribbon connectors and the 26-pin header. The cameras are USB and the Pico is on USB, so nothing in the machine needs them.</li>
</ul>

## Power in

The machine has one 24 V power supply. The Orange Pi cannot run from 24 V, so a 24 V to 5 V buck converter sits between them, and its USB-C lead goes into the board's `PWR IN` socket. The board has two USB-C sockets that look the same, and only `PWR IN` takes power. The other one is a data and display port that the machine does not use.

The hub has its own 24 V feed from the same supply. The Orange Pi does not power the hub, and it does not power the cameras or the Pico through it.

<ul class="bulleted-list">
  <li>Where the three 24 V leads go: <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">Connecting the components</a></li>
  <li>The Orange Pi's lead: <a href="{{ '/hardware/helpers/pi-24v-lead/' | relative_url }}">Make the Orange Pi's 24 V lead</a></li>
  <li>The converter and the board in the catalog: <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts-calculator/catalog/parts.json</code></a> (<code>buck-24v-5v-usbc</code>, <code>sbc-orange-pi-5</code>)</li>
</ul>

## USB: the Pico and the cameras

The Orange Pi's blue `UP USB3.0` port is cabled to the hub, and the hub is the only thing on the Orange Pi's USB. Four devices hang off the hub, which fills it:

<ul class="bulleted-list">
  <li><strong>The Pico</strong> on the control board. It drives the steppers, servos, lamps and switches. The Orange Pi sees it as a serial port and sends it short commands. The protocol is on <a href="{{ '/design/electronics/' | relative_url }}">How the electronics talk to each other</a>.</li>
  <li><strong>The 4K camera</strong> (IMX415), for classification.</li>
  <li><strong>Two 720p cameras</strong> (OV9732), for the C-channel and carousel drop plate detection.</li>
</ul>

The software finds the Pico by its USB ID and the cameras by their video device number. That difference, and what happens when a cable is pulled, is on the USB page. The other two USB 2.0 ports on the board are free.

<ul class="bulleted-list">
  <li>The USB tree and how each device is found: <a href="{{ '/design/usb/' | relative_url }}">The USB connections and the hub</a></li>
  <li>Finding the Pico and opening its serial port: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/bus.py"><code>hardware/bus.py</code></a> and <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/machine_platform/control_board.py"><code>machine_platform/control_board.py</code></a></li>
  <li>Opening and reading the cameras: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/vision/camera.py"><code>vision/camera.py</code></a></li>
  <li>Listing and assigning cameras from the UI: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/server/routers/cameras.py"><code>server/routers/cameras.py</code></a></li>
</ul>

## Network

The Orange Pi has a gigabit Ethernet port and no WiFi of its own. The machine works with a cable alone. For WiFi you fit the optional M.2 WiFi module, or plug in a Linux-compatible USB WiFi adapter.

The network is how you use the machine at all. On first boot SorterOS opens a setup network called `SorterOS-Setup` plus six characters, you join it from a phone and pick your WiFi, and from then on the UI is at `sorter.local` on that network. SorterOS keeps a small file describing the current network state, and the backend reads it so the machine's Hive page can link to it where it is now.

<ul class="bulleted-list">
  <li>WiFi options and the two kinds of M.2 slot: <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a></li>
  <li>First boot and joining WiFi: <a href="{{ '/sorter/installation/sorter-os/' | relative_url }}">Install the SorterOS image</a></li>
  <li>Reading the network state: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/machine_network.py"><code>machine_network.py</code></a></li>
</ul>

## Storage

Storage is the microSD card. SorterOS is flashed to it, and the machine runs from it. The card should be 32 GB or larger and high-endurance, because the software writes to it all day.

The board has one M.2 socket, and that socket takes either an NVMe drive or the WiFi module, not both. The machine's documentation covers only the microSD card.

<ul class="bulleted-list">
  <li>Card requirements: <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a></li>
  <li>Flashing and first boot: <a href="{{ '/sorter/installation/sorter-os/' | relative_url }}">Install the SorterOS image</a></li>
  <li>Shutting down without damaging the card: <a href="{{ '/sorter/safe-shutdown/' | relative_url }}">Shutting down the machine</a></li>
</ul>

## Display, keyboard and debugging

None is needed. The machine is headless: you set it up and run it from a browser on another device, and you can log in over SSH if you need a shell. The board has HDMI and a 3-pin debug serial header, but nothing in the machine's design uses them.

<ul class="bulleted-list">
  <li>Setting up from a browser: <a href="{{ '/sorter/first-setup/' | relative_url }}">First setup</a></li>
  <li>When something does not appear: <a href="{{ '/sorter/troubleshooting/' | relative_url }}">Troubleshooting</a></li>
  <li>The housing: <a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi housing</a></li>
</ul>

## The NPU

The detection models run on the RK3588S processor's built-in neural processing unit (NPU), which is the reason the Orange Pi 5 is the specified board. The NPU has three cores. The perception service pins each of the three camera channels to its own core, in a fixed order, so a channel always lands on the same core after a restart. The backend can also report which AI runtimes the computer offers, and the RKNN runtime is the one the Orange Pi uses.

There is a Hailo probe in the same file, for computers that carry a Hailo accelerator. No Hailo accelerator is part of the Orange Pi build.

<ul class="bulleted-list">
  <li>Channels and cores: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/perception/service.py"><code>perception/service.py</code></a></li>
  <li>Which runtimes are available: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/server/routers/runtimes.py"><code>server/routers/runtimes.py</code></a></li>
  <li>The detection models: <a href="{{ '/lab/object-detection/' | relative_url }}">Object detection</a></li>
</ul>

## Cooling

The board gets hot when it is pinned hard, especially if a model ends up running on the CPU rather than the NPU, and it can reach thermal shutdown at about 105 °C. The catalog lists the official heatsink fan, which plugs into the board's 5 V fan socket.

<ul class="bulleted-list">
  <li>Cooling notes: <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a></li>
</ul>

## Other computers

The Orange Pi 5 is the board SorterOS is built for. The software can also be installed on other Linux computers (Debian 12 or Ubuntu 24.04, and Raspberry Pi OS on a Pi 5) with the Linux installer.

<ul class="bulleted-list">
  <li><a href="{{ '/sorter/installation/linux-generic/' | relative_url }}">Install on Linux (generic)</a> and <a href="{{ '/sorter/installation/by-hand/' | relative_url }}">install by hand</a></li>
</ul>
