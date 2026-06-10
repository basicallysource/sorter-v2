---
layout: default
title: Install SorterOS
type: installation
section: sorter
slug: installation-sorter-os
kicker: Installation — SorterOS
lede: Flash SorterOS onto an SD card and configure it for first boot. The recommended way to run Sorter on an Orange Pi 5.
permalink: /sorter/installation/sorter-os/
audience: self-hosting operator
applies_to: sorteros v4.x
last_verified: 2026-06-09
---

<div class="notice notice-warn">
  <strong>Orange Pi 5 required</strong>
  <p>SorterOS is designed specifically for the <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a>. See the <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5 hardware page</a> for board selection, memory, storage, and WiFi requirements before continuing here.</p>
</div>

## What is SorterOS

SorterOS is a purpose-built OS image for Sorter, based on the official Ubuntu image from Orange Pi. It ships with the Sorter backend, frontend, and firmware pre-installed and configured to start on boot — no manual install steps required after flashing.

## Prerequisites

- An [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) with at least 8 GB of memory
- A 32 GB or larger SD card
- A computer with an SD card reader
- [Balena Etcher](https://etcher.balena.io/) installed on your computer

## Step 1 — Download the image

Go to **[github.com/basicallysource/sorter-v2/releases](https://github.com/basicallysource/sorter-v2/releases)**, find the latest SorterOS release, and download the `.zip` file from its assets.

## Step 2 — Flash to SD card

1. Open **[Balena Etcher](https://etcher.balena.io/)**
2. Click **Flash from file** and select the downloaded `.zip` file
3. Click **Select target** and choose your SD card
4. Click **Flash**

Wait for Etcher to finish writing and verifying. Do not remove the card until it reports success. The image ships generic — there is nothing to configure before flashing.

## Step 3 — Boot and connect to WiFi

Insert the SD card into the Orange Pi 5 and power it on.

- **Ethernet** — if the Pi is wired to your router, it comes online automatically without any WiFi configuration.
- **WiFi** — when the Pi boots without a network connection, it opens a temporary hotspot named **`SorterOS-Setup-…`**. Join it from your phone or laptop; a captive portal opens automatically where you pick your WiFi network and enter its password. The Pi then shuts down the hotspot and joins your network.

The Pi needs an internet connection to complete first-boot initialization and to run Sorter on an ongoing basis. Once first-boot setup completes and the Pi has finished downloading its dependencies — less than 5 minutes if everything is working — the Sorter UI is available at:

**[http://sorter.local:5173/](http://sorter.local:5173/)**

This uses mDNS — the device you're browsing from must be on the same network as the Pi.

## SSH access

SorterOS services run as root. The default SSH username is `root` and the default password is `orangepi`. If you are using Tailscale SSH, no password is required.

## Troubleshooting

See [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}) for common first-boot problems.
