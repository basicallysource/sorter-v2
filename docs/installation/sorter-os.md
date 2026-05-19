---
layout: default
title: Install SorterOS
type: installation
section: installation
slug: installation-sorter-os
kicker: Installation — SorterOS
lede: Flash SorterOS onto an SD card and configure it for first boot. The recommended way to run Sorter on an Orange Pi 5.
permalink: /installation/sorter-os/
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

Download the latest SorterOS image from the releases page:

**[github.com/basicallysource/sorter-v2/releases](https://github.com/basicallysource/sorter-v2/releases)**

Download the `.img` file listed under the latest release.

## Step 2 — Configure WiFi and SSH

Open the image file in **[SorterOS Setup](https://setup.basically.website)** to set WiFi credentials or add an SSH public key before flashing. Everything runs client-side in the browser — nothing is sent to a server.

**Saving the configured image:**
- **Chrome** — SorterOS Setup can overwrite the original `.img` file directly, so no extra disk space is needed.
- **Other browsers** — a new copy is downloaded. The image is about 8 GB, so make sure you have the space. Once you have the configured copy you can delete the original.

The Pi needs an internet connection to complete first-boot initialization and to run Sorter on an ongoing basis. If you are not comfortable working in a terminal, configure WiFi here before flashing — the base image has no desktop environment, so WiFi cannot be set up through a GUI after booting.

Alternatively, plug the Pi into your router via Ethernet and it will come online automatically without any WiFi configuration.

If you ever need to change your WiFi network or SSH key, you can run the image through SorterOS Setup again — it will overwrite the previous configuration.

## Step 3 — Flash to SD card

1. Open **[Balena Etcher](https://etcher.balena.io/)**
2. Click **Flash from file** and select the `.img` file (configured in the previous step, or the original if you skipped it)
3. Click **Select target** and choose your SD card
4. Click **Flash**

Wait for Etcher to finish writing and verifying. Do not remove the card until it reports success.

## Step 4 — Boot

Insert the SD card into the Orange Pi 5 and power it on. SorterOS completes first-boot setup automatically, then starts the Sorter backend and UI.

Once booted, the Sorter UI is reachable from any device on the same network:

```
http://<pi-ip>:5173/
```

## Troubleshooting

See [Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}) for common first-boot problems.
