---
layout: default
title: Install SorterOS
type: installation
section: sorter
slug: installation-sorter-os
kicker: Installation — SorterOS
lede: Flash an SD card, power on the Orange Pi, and put it on your WiFi from your phone. The Pi sets up the rest.
permalink: /sorter/installation/sorter-os/
audience: self-hosting operator
applies_to: sorteros v4.x
last_verified: 2026-09-24
---

<div class="notice notice-warn">
  <strong>Orange Pi 5 only</strong>
  <p>SorterOS runs on the <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a> with 8 GB of memory or more.</p>
</div>

## What you need

- An [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) with 8 GB of memory or more
- **A 32 GB or larger microSD card from a name brand, like Samsung** ([the SD card part](https://parts-calculator.basically.website/u/7fvo/)). The Pi writes to it all day, and cheap cards corrupt.
- A computer with an SD card reader, and [Balena Etcher](https://etcher.balena.io/)
- A phone and your WiFi's password, or an Ethernet cable to your router

## 1. Download

Download the `.zip` from the latest **SorterOS** release on [GitHub](https://github.com/basicallysource/sorter-v2/releases).

## 2. Flash

In Balena Etcher: **Flash from file**, pick the `.zip`, **Select target**, pick the SD card, **Flash**. Wait until Etcher says the flash is complete.

## 3. Power on

Put the card in the Orange Pi and power it on.

**On Ethernet to your router?** The Pi goes online by itself. Skip to step 5.

## 4. Put it on your WiFi from your phone

About half a minute after power on, the Pi starts its own WiFi network, `SorterOS-Setup-` and six characters.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/sorteros-setup-phone-1-join-network-full-fe8a716277d0.png" alt="An iPhone's WiFi settings listing a network called SorterOS-Setup-63F32A among the nearby networks">
    <figcaption>In your phone's WiFi settings, join the <code>SorterOS-Setup</code> network. <cite>Screenshot recorded on an iPhone.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/sorteros-setup-phone-2-choose-network-full-5db6cef77cbf.png" alt="The Sorter's setup page in the phone's sign-in window, listing the WiFi networks the Sorter can see">
    <figcaption>A setup page opens. Tap your WiFi network. <cite>Screenshot recorded on an iPhone.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/sorteros-setup-phone-3-password-full-87f1684b0c28.png" alt="The setup page asking for the password of the chosen network, with a Join button">
    <figcaption>Enter its password and tap <strong>Join</strong>. <cite>Screenshot recorded on an iPhone.</cite></figcaption>
  </figure>
</div>

No setup page? Stay on the `SorterOS-Setup` network and open [http://10.42.0.1](http://10.42.0.1) in Safari or Chrome.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/sorteros-setup-phone-4-joining-full-52aa8287136c.png" alt="The setup page saying it is joining the network, and to keep the page open">
    <figcaption>The Pi joins while your phone stays on the setup network. <cite>Screenshot recorded on an iPhone.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/sorteros-setup-phone-5-wrong-password-full-44310e947171.png" alt="The setup page showing Wrong password for the network, with the password field ready to try again">
    <figcaption>A wrong password says so. Fix it and join again. <cite>Screenshot recorded on an iPhone.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/sorteros-setup-phone-6-joined-full-bcd8440c578d.png" alt="The setup page saying the Sorter is on the network, with its address, the next steps and a Done button">
    <figcaption>It's on. Note the address and tap <strong>Done</strong>; your phone goes back to your WiFi. <cite>Screenshot recorded on an iPhone.</cite></figcaption>
  </figure>
</div>

## 5. Open the Sorter

On a phone or computer on the same WiFi, open **[http://sorter.local](http://sorter.local)**.

<figure class="single-figure">
  <img src="https://assets.basically.website/sorter-docs/sorteros-setup-phone-7-first-boot-full-c61f9a7eaa82.png" alt="The first boot progress page at sorter.local with every stage checked and a link to reload for the Sorter UI">
  <figcaption>The first boot installs the Sorter software, which takes a few minutes. The page updates itself, then becomes the Sorter UI. <cite>Screenshot recorded on an iPhone.</cite></figcaption>
</figure>

The first time, the UI opens on the [setup wizard]({{ '/sorter/first-setup/' | relative_url }}).

## If something's off

- **No `SorterOS-Setup` network.** It only appears while the Pi is offline. On a cable with internet, the Pi is already online: go to step 5.
- **The setup page didn't open.** Open [http://10.42.0.1](http://10.42.0.1) in Safari or Chrome while on the setup network.
- **Your phone left the setup network during the join** (it can on a WiFi that's only 5 GHz). Join it again to see the result.
- **`sorter.local` doesn't open.** Use the address the setup page showed. Older Windows needs [Bonjour](https://support.apple.com/en-us/106380), and Android usually can't open `.local` names. A second SorterOS machine is `sorter-2.local`.
- **Office or school WiFi** that asks for a username as well as a password can't be set up this way. Use Ethernet.

More in [troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}#first-boot).

## Or: put your WiFi in before you flash

[SorterOS Setup](https://setup.basically.website) writes your WiFi into the image, and optionally a hostname, an SSH key and a Tailscale key. It runs in your browser and uploads nothing. Unzip the download, open the `.img` there, and flash the `.img` it saves instead of the `.zip`.

## Later

- **New router or WiFi password.** When the Pi can't reach the internet for about a minute, its setup network comes back. Do step 4 again.
- **Updates.** Settings, then Versions, in the Sorter UI. You only need a new SorterOS image when the image itself changes.
- **SSH.** User `root`, password `orangepi`.
