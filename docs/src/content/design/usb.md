---
layout: default
title: The USB connections and the hub
type: explanation
section: design
slug: design-usb
kicker: Design — Electronics
lede: How the Pico and the three cameras reach the Orange Pi through one powered hub, and how the software finds each of them.
permalink: /design/usb/
last_verified: 2026-10-10
---

Everything the Orange Pi talks to over USB goes through one powered hub. The Orange Pi has a single cable to the hub, and the Pico and the three cameras plug into the hub. This page describes that tree and how the software finds each device on it. What else the Orange Pi is connected to is on [What is connected to the Orange Pi]({{ '/design/orange-pi/' | relative_url }}). Which cable goes in which socket is on [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

## The USB tree

<ul class="bulleted-list">
  <li><strong>Orange Pi:</strong> the blue <code>UP USB3.0</code> port goes to the hub. It is the only thing on the Orange Pi's USB.</li>
  <li><strong>The hub:</strong> a Waveshare USB3.2-Gen1-HUB-4U, four USB-A ports, powered from the machine's 24 V supply. It sits on the roof of the Orange Pi housing.</li>
  <li><strong>On the hub:</strong> the Pico control board (micro-USB cable), the 4K IMX415 camera for classification, and the two OV9732 720p cameras. That is all four ports.</li>
  <li><strong>Spare:</strong> the Orange Pi's other two USB ports (one USB 2.0 Type-A under the blue one, and one on the board's edge) carry nothing in the machine.</li>
</ul>

The IMX415 is a USB 3.0 camera and the OV9732 modules are USB 2.0. The two cables between the Pico, the hub and the Orange Pi, and the three camera leads, are labelled `USB1` to `USB5` at both ends, so you can tell them apart once they are routed.

<ul class="bulleted-list">
  <li>Every cable and its two ends: <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">Connecting the components</a></li>
  <li>The hub and the camera cards in the catalog: <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts-calculator/catalog/parts.json</code></a> (<code>usb-hub-powered-24v</code>, <code>cam-imx415</code>, <code>cam-ov9732</code>)</li>
  <li>The Orange Pi's ports: <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a></li>
</ul>

## Why the hub has its own power

The hub runs from the machine's 24 V supply (its input takes 7 to 36 V), not from the Orange Pi. A hub that draws its power from the Orange Pi can let the devices on it brown out the board under load, and that shows up as a severe system crash rather than a clean USB disconnect. So the hub in the design is always a powered one, and the model matters: the Waveshare hub is the one that takes 24 V directly.

The cables between the Pico, the hub and the Orange Pi must carry data. A charge-only micro-USB cable powers the Pico and never shows it to the software.

<ul class="bulleted-list">
  <li>Powered-hub rule: <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a></li>
  <li>Where the hub's 24 V lead goes: <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">Connecting the components</a></li>
</ul>

## How the software finds the Pico

The Pico is found by its USB ID. The backend lists the computer's serial ports and keeps only those whose vendor and product ID are `2e8a:000a`, which is the Pico running the machine's firmware. On Linux it shows up as a `/dev/ttyACM` device.

It then opens the port at 576000 baud, exclusively, so a second program (the UI's flasher, a probe) cannot talk over the backend. Each control board is asked who it is, and the answer, including the names of the steppers it reports, selects the board profile. Discovery retries up to 8 times, 0.75 seconds apart, so a Pico that is still starting does not fail the boot.

A Pico that has never been flashed has empty flash, so it appears as an `RPI-RP2` storage drive instead of a serial port. Discovery cannot see it until the firmware is on it. This is normal on a new build.

Opening the port needs permission. The repository ships a udev rule for Raspberry Pi vendor `2e8a` that gives the `plugdev` group (and the logged-in desktop user) access, and the Linux installer installs it.

<ul class="bulleted-list">
  <li>The serial port, exclusive open and enumeration by USB ID: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/bus.py"><code>hardware/bus.py</code></a></li>
  <li>Discovery, retries and board profiles: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/machine_platform/control_board.py"><code>machine_platform/control_board.py</code></a></li>
  <li>Flashing, including the blank-board drive: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/firmware_flash.py"><code>hardware/firmware_flash.py</code></a></li>
  <li>The udev rule: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/systemd/99-sorter-pico.rules"><code>software/systemd/99-sorter-pico.rules</code></a></li>
  <li>What the Pico says over the cable: <a href="{{ '/design/electronics/' | relative_url }}">How the electronics talk to each other</a></li>
</ul>

## How the software finds the cameras

The cameras are plain UVC video devices, and the software finds them differently from the Pico: by their video device number, not by a USB ID. On Linux the backend lists the video devices from 0 to 15 and keeps those that offer capture formats. Asking for the formats does not open a stream, so a camera that is already streaming still shows up in the list.

Each camera has a role: C-channel 2, C-channel 3, and the carousel and classification cameras. The role is tied to a device number in the machine's configuration, and you choose which camera is which in the UI (**Settings → Cameras**). Nothing in the code looks at a camera's USB ID or at which hub port it is in.

If a camera stops delivering frames, or is unplugged, the capture thread closes it, waits, and tries to open it again, with a pause that grows from a quarter of a second up to five seconds. The backend reports each camera as online, reconnecting, offline or unassigned.

<ul class="bulleted-list">
  <li>Listing and assigning cameras: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/server/routers/cameras.py"><code>server/routers/cameras.py</code></a></li>
  <li>Capture, reopening and the backoff: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/vision/camera.py"><code>vision/camera.py</code></a>, and the device wrapper <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/vision/camera_device.py"><code>vision/camera_device.py</code></a></li>
  <li>The <code>[cameras]</code> keys: <a href="{{ '/sorter/machine-toml-reference/' | relative_url }}">machine.toml reference</a></li>
  <li>Choosing cameras and checking the picture: <a href="{{ '/sorter/camera-calibration/' | relative_url }}">Camera calibration</a></li>
</ul>

## Bandwidth

The camera code is written on the assumption that the three cameras share one USB 2.0 bus on the Orange Pi. Uncompressed video (YUYV) at any real resolution would fill that bus on its own, so the default capture mode is MJPEG at the camera's own resolution: 4K on the 4K camera and 720p on the others. The same reasoning is why the configuration reference recommends forcing MJPG on Linux with several cameras.

<ul class="bulleted-list">
  <li>The default mode and why: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/vision/camera_modes.py"><code>vision/camera_modes.py</code></a></li>
  <li>Per-camera capture settings: <a href="{{ '/sorter/machine-toml-reference/' | relative_url }}">machine.toml reference</a></li>
</ul>

## When something does not appear

<ul class="bulleted-list">
  <li><strong>No Pico found:</strong> the machine is not powered, the Pico's cable is not in the hub, the cable is charge-only, or the Pico has never been flashed.</li>
  <li><strong>Permission denied on the Pico (Linux installs):</strong> the user is not in <code>plugdev</code>, or has not logged out and in since the installer added it.</li>
  <li><strong>Occasional "MCU bus transient error" lines in the log:</strong> the backend retries each command up to 3 times; a line followed by nothing else means the command got through.</li>
  <li><strong>A camera is missing from the list:</strong> the list only shows video devices that offer capture formats, so check its cable and the hub, then assign the role again in <strong>Settings → Cameras</strong>.</li>
</ul>

<ul class="bulleted-list">
  <li>Steps for each case: <a href="{{ '/sorter/troubleshooting/' | relative_url }}">Troubleshooting</a> and <a href="{{ '/sorter/first-setup/' | relative_url }}">First setup</a></li>
  <li>Flashing a blank board: <a href="{{ '/hardware/software-setup/' | relative_url }}">Software setup</a></li>
</ul>
