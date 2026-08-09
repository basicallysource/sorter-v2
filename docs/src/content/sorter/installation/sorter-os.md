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
applies_to: sorteros v3.x
last_verified: 2026-05-19
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

## Step 2 — Configure WiFi and SSH

If you do not need to configure WiFi, hostname, SSH auth key, or Tailscale auth key, you can flash the `.zip` file directly — skip ahead to Step 3.

Otherwise, decompress the `.zip` file on your computer first, then open the `.img` file in **[SorterOS Setup](https://setup.basically.website)** to set those options before flashing. Everything runs client-side in the browser — nothing is sent to a server.

**Saving the configured image:**
- **Chrome** — SorterOS Setup can overwrite the original `.img` file directly, so no extra disk space is needed.
- **Other browsers** — a new copy is downloaded. The image is about 8 GB, so make sure you have the space. Once you have the configured copy you can delete the original.

The Pi needs an internet connection to complete first-boot initialization and to run Sorter on an ongoing basis. If you are not comfortable working in a terminal, configure WiFi here before flashing — the base image has no desktop environment, so WiFi cannot be set up through a GUI after booting.

Alternatively, plug the Pi into your router via Ethernet and it will come online automatically without any WiFi configuration.

If you ever need to change your WiFi network or SSH key, you can run the image through SorterOS Setup again — it will overwrite the previous configuration.

## Step 3 — Flash to SD card

1. Open **[Balena Etcher](https://etcher.balena.io/)**
2. Click **Flash from file** and select either the `.zip` file (if you skipped setup) or the `.img` file (if you ran it through SorterOS Setup)
3. Click **Select target** and choose your SD card
4. Click **Flash**

Wait for Etcher to finish writing and verifying. Do not remove the card until it reports success.

## Step 4 — Boot

Insert the SD card into the Orange Pi 5 and power it on. SorterOS completes first-boot setup automatically, then starts the Sorter backend and UI. This takes less than 5 minutes if everything is working.

Once first-boot initialization completes and the Pi has finished downloading its dependencies, the Sorter UI is available at:

**[http://sorter.local:5173/](http://sorter.local:5173/)**

This uses mDNS — the device you're browsing from must be on the same network as the Pi. If you set a custom hostname in SorterOS Setup, substitute that name for `sorter`.

## SSH access

SorterOS services run as root. The default SSH username is `root` and the default password is `orangepi`. If you are using Tailscale SSH, no password is required.

## Troubleshooting

See [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}) for common first-boot problems.
