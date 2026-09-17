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
last_verified: 2026-09-17
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

<div class="notice notice-warn">
  <strong>SorterOS Setup is currently broken</strong>
  <p>On the current release it rejects every configuration with <code>config too large: N bytes, capacity 2</code>, whatever you enter. This is a bug in the tool, not in your download, and shortening the configuration does not get past it. See <a href="https://github.com/basicallysource/sorter-v2/issues/675">issue #675</a>. Until it is fixed, flash the <code>.zip</code> directly and connect the Pi to your router over Ethernet; WiFi and Tailscale can both be set from the Sorter UI afterwards, on its Settings page.</p>
</div>

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

Once first-boot initialization completes and the Pi has finished downloading its dependencies, the Sorter UI is available on port `80`, so the address takes no port suffix. Which address reaches it depends on whether you ran SorterOS Setup in Step 2, which is what sets the Pi's hostname.

- **Ran SorterOS Setup** — use the hostname you entered there: `http://<hostname>.local/`. That field defaults to `sorter`, so if you left it alone the address is [http://sorter.local/](http://sorter.local/).
- **Flashed the `.zip` directly** — nothing sets a hostname, so the Pi keeps the one from the base Orange Pi Ubuntu image, normally `orangepi5`: [http://orangepi5.local/](http://orangepi5.local/).

Both use mDNS, so the device you're browsing from must be on the same network as the Pi. mDNS resolves natively on macOS and iOS; on Windows it usually needs [Bonjour](https://support.apple.com/en-us/106380) installed.

If no `.local` address resolves, find the Pi in your router's list of connected devices and browse to its IP address, again with no port.

`5173` is the Vite dev server's port and applies only to the [by hand]({{ '/sorter/installation/by-hand/' | relative_url }}) and [generic Linux]({{ '/sorter/installation/linux-generic/' | relative_url }}) install paths, not to SorterOS.

## SSH access

SorterOS services run as root. The default SSH username is `root` and the default password is `orangepi`. If you are using Tailscale SSH, no password is required.

## Troubleshooting

See [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}) for common first-boot problems.
