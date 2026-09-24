---
layout: default
title: Install SorterOS
type: installation
section: sorter
slug: installation-sorter-os
kicker: Installation — SorterOS
lede: Flash SorterOS onto an SD card, power on the Orange Pi, and it sets itself up. The recommended way to run Sorter on an Orange Pi 5.
permalink: /sorter/installation/sorter-os/
audience: self-hosting operator
applies_to: sorteros v4.x
last_verified: 2026-09-23
---

<div class="notice notice-warn">
  <strong>Orange Pi 5 required</strong>
  <p>SorterOS is designed specifically for the <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a>. See the <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5 hardware page</a> for board selection, memory, storage, and WiFi requirements before continuing here.</p>
</div>

## What is SorterOS

SorterOS is an OS image for Sorter, based on the official Ubuntu image from Orange Pi. The image itself is small: on first boot it downloads the current stable release of the Sorter software, builds it on the board, and starts it. Every SorterOS machine answers at [http://sorter.local](http://sorter.local).

## Prerequisites

- An [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) with at least 8 GB of memory
- A 32 GB or larger SD card, ideally a name-brand high-endurance one (see the hardware page)
- A computer with an SD card reader
- [Balena Etcher](https://etcher.balena.io/) installed on your computer
- An internet connection for the Pi: an Ethernet cable to your router, or your WiFi network's name and password

## Step 1 — Download the image

Go to **[github.com/basicallysource/sorter-v2/releases](https://github.com/basicallysource/sorter-v2/releases)**, find the latest **SorterOS** release, and download the `.zip` file from its assets.

## Step 2 — Add your WiFi (optional)

Skip this if the Pi will use Ethernet, or if you'd rather give it your WiFi from a phone after it starts (Step 4).

Otherwise, unzip the download and open the `.img` in **[SorterOS Setup](https://setup.basically.website)**. It writes your WiFi network and password into the image, and optionally a hostname, an SSH key and a Tailscale auth key. It runs entirely in your browser; nothing is uploaded. In Chrome it can save into the original `.img`; other browsers download a changed copy (about 7 GB).

## Step 3 — Flash to SD card

1. Open **[Balena Etcher](https://etcher.balena.io/)**
2. Click **Flash from file** and select the `.zip` (or, if you did Step 2, the `.img` you saved)
3. Click **Select target** and choose your SD card
4. Click **Flash**

Wait for Etcher to finish writing and verifying. Do not remove the card until it reports success.

## Step 4 — Power on

Insert the SD card into the Orange Pi 5 and power it on. It gets online the first way that works:

1. **Ethernet**, if a cable to your router is plugged in.
2. **The WiFi from Step 2.** It gets about a minute and a half to connect.
3. Otherwise it opens its own WiFi network, named `SorterOS-Setup-` followed by six characters. Join it from a phone or laptop; a setup page opens (if it doesn't, browse to [http://10.42.0.1](http://10.42.0.1)). Pick your network, or type its name if it isn't listed, and enter its password. The Pi restarts to join it, which takes about two minutes, and your phone goes back to its usual WiFi. Open the **Find my sorter** link the page gives you: once the Pi is online it shows its address and the network it joined. If the setup network shows up again instead, the Pi couldn't join; connect to it again and the page says why, usually a wrong password.

   Networks that sign in with a username as well as a password (enterprise WiFi, common in offices and schools) can't be set up this way. Use Ethernet on those.

The setup network is also the way back if something changes later: a Pi that can't get online when it starts (a new router, a changed password) opens it again. If you plug in a cable while it's up, the Pi uses the cable instead.

## Step 5 — First boot

Browse to **[http://sorter.local](http://sorter.local)** from a computer on the same network. Until the software is ready this shows a progress page listing every first-boot stage and its state, refreshing itself every few seconds. When the last stage the UI needs is done, the same address becomes the Sorter UI.

<div class="notice">
  <strong>First boot takes a while, and it needs the network throughout</strong>
  <p>The Pi downloads the Sorter software and builds the backend's Python environment and the frontend on the board itself; how long that takes depends on your connection. A stage that needs the network waits and retries rather than failing, and the progress page shows the reason next to any stage that is stuck. The board's LEDs are no guide: they blink the whole time.</p>
</div>

`sorter.local` uses mDNS, so the device you're browsing from must be on the same network as the Pi. It resolves natively on macOS, iOS, Linux and recent Windows; older Windows may need [Bonjour](https://support.apple.com/en-us/106380). A second SorterOS machine on the same network answers at `sorter-2.local`. If no `.local` address resolves, find the Pi in your router's list of connected devices and browse to its IP address.

Once the UI is up, the Pi downloads a detection model from [Hive](https://hive.basically.website) that suits its hardware and puts it on every camera channel, so detection works without picking a model yourself. You can change it later under **Settings → Local Models**.

The first time you open the UI it starts on the setup wizard, which names the machine, finds the control boards, checks motion and endstops, and assigns servos and cameras. [First setup in the UI]({{ '/sorter/first-setup/' | relative_url }}) takes it step by step.

## Updates

The UI's **Settings → Versions** page lists the stable and canary releases and switches between them. A new SorterOS image is only needed when the image itself changes, never to get a newer Sorter release.

## SSH access

SorterOS services run as root. The default SSH username is `root` and the default password is `orangepi`. If you are using Tailscale SSH, no password is required.

## Troubleshooting

See [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}#first-boot) for first-boot problems.
