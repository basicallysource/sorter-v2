---
layout: default
title: Before your first sort run
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-before-first-sort-run
kicker: Sorter — Operate
author: reveryx
lede: The last five things to check in the UI, once the setup wizard, the cameras and the chute are done.
permalink: /sorter/before-first-sort-run/
warning: >-
  **AI-generated first draft.** Written from the Sorter software's own source, not
  from setting up a machine that has sorted. It has no screenshots, and the model
  names in step 3 have not been checked against the list a real machine shows.
---

Five things stand between a set-up machine and a first sort run. All of them are in the UI and none of them takes long. Skip step 3 and the machine sees nothing at all.

## Before you start

- [First setup in the UI]({{ '/sorter/first-setup/' | relative_url }}) is done: the UI opens on the dashboard, not on the wizard.
- [Camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) is done.
- [Chute calibration]({{ '/sorter/chute-calibration/' | relative_url }}) is done, and a test aim landed the chute centred over the bins you tried.

## 1. Check the machine setup matches your build

Open **Settings** &rarr; **General** &rarr; **Machine setup**. It names the shape of your machine: standard carousel, classification channel, or manual carousel. A new install is set to classification channel.

It has to match the machine you built. If it is wrong, change it here before you go any further, then go back through the Cameras step of the setup wizard: this setting decides which cameras and which endstops the machine asks for.

## 2. Set the storage layers

Open **Settings** &rarr; **Storage Layers**. Each layer needs four things: switched on, its number of sections, the number of bins in a section, and the servo that opens its doors.

The setup wizard assigned the servos. The bin counts are separate, and the chute aims from them, so a wrong count sends pieces to the wrong bin. If your chute test aim landed centred every time, the counts are already right.

## 3. Choose a detection model

Detection is how the machine sees that a piece is there and where it is on the channel. Each camera channel runs its own model, and you choose which one.

**If the machine runs on an Orange Pi 5, which is the standard build, you have to change the model before the first run.** On any other computer, the model the machine starts with is the right one, and you can skip this step.

Open **Settings** &rarr; **Hive** &rarr; **Models**. The page is titled **Detection Models**. The **Installed** list holds every model the machine already has, so there is nothing to download. Each row has an **Activate for subsystem** menu with one button per channel.

Set:

- **C-Channel 2** and **C-Channel 3** to `r4-c-channel-yolo11s-320-silu`
- **Classification C-Channel (C4)** to `r3-c-channel-full-yolo11n-320`

Leave **Chamber** as it is.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The model a new machine starts with, <code>c-chamber-combined-yolo11s-320</code>, is in a file format an Orange Pi 5 cannot run, and nothing in the UI tells you. The channel shows no pieces, reports no error and raises no incident. It looks like a dead camera, not a wrong setting.</p>
</div>

Three things about this page:

- **Classification C-Channel and Carousel detect are one setting shown as two rows.** Set either one and both change.
- **The page lets you activate a model on a channel it was not trained for.** It marks the row with a note and does not stop you. Use the two models above.
- **The change takes effect in a second or two.** Nothing needs restarting.

## 4. Deploy a sorting profile

Open **Profiles**, then press **activate** on **Presort**. Presort has eight categories and a catch-all, so nothing falls through on a first run.

Activating asks how the bins should start. **Pre-assign from rules** fills the bins in order: the first category goes to the first bin of the first section of the first layer, the second category to the next bin, and so on. Read that order off the screen and put your bins where the machine expects them. **Reset bins** empties them instead and assigns each category to a bin the first time a piece needs one.

Presort is the profile that ships with the machine. When you want your own boxes, [build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}) walks through making one in Hive and getting it onto this machine.

No bin is kept for pieces that match nothing. Those drop out of the bottom of the tower, so put a box or a tray under it before you start.

## 5. Check the machine is on the internet

Every piece is identified by a service on the internet. A machine with no connection still feeds, sees and moves pieces, and identifies none of them. [What leaves the machine]({{ '/sorter/what-leaves-the-machine/' | relative_url }}) covers what is sent.

You need no account and no key for this. The **OpenRouter** key on the Settings page is a separate, optional thing.

## Home the chute before every run

The aiming is saved. The homing is not. Home the chute from **Settings** &rarr; **Chute** &rarr; **Home to Endstop** before each run, and again after any stall. Until it is homed, the aiming numbers mean nothing.

## Next

[Your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }}).
