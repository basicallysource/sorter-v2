---
layout: default
title: Before your first sort run
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-before-first-sort-run
kicker: SorterOS — Operate
author: reveryx
lede: The last five things to check in the UI, once the setup wizard, the cameras and the chute are done.
permalink: /sorter/before-first-sort-run/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not
  from setting up a machine that has sorted. It has no screenshots, and the model
  names in step 3 have not been checked against the list a real machine shows.
---

Five things stand between a set-up machine and a first sort run. All of them are in the UI and none of them takes long. Four are checks; the one that may need doing is step 4, a sorting profile (a machine linked to Hive already has one).

## Before you start

- [First setup in the UI]({{ '/sorter/first-setup/' | relative_url }}) is done: the UI opens on the dashboard, not on the wizard.
- [Camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) is done.
- [Chute calibration]({{ '/sorter/chute-calibration/' | relative_url }}) is done, and a test aim landed the chute centred over the bins you tried.

## 1. Check the machine setup matches your build

Open **Settings** &rarr; **General** &rarr; **Machine setup**. It names the shape of your machine: standard carousel, classification channel, or manual carousel. A new install is set to classification channel.

It has to match the machine you built. If it is wrong, change it here before you go any further, then go back through the Cameras step of the setup wizard: this setting decides which cameras and which endstops the machine asks for.

## 2. Set the storage layers

Open **Settings** &rarr; **Storage Layers**. Each layer needs four things: switched on, its number of sections, the number of bins in a section, and the servo that opens its doors.

The setup wizard assigned the servos, and you set the counts at [chute calibration]({{ '/sorter/chute-calibration/' | relative_url }}). This is the check: if your chute test aim landed centred every time, the counts are already right.

## 3. Check the detection model

Detection is how the machine sees that a piece is there and where it is on the channel. Each camera channel runs its own model.

There is nothing to choose on a new machine. When it first comes online it asks [Hive](https://hive.basically.website) for the default detection model for its hardware (on an Orange Pi 5, **r5 C-Channel Full YOLO11s 320**, a model built for the Orange Pi's NPU), downloads it, and puts it on every channel that has none. If the machine was offline, it tries again every five minutes.

To check, open **Settings** &rarr; **Local Models**. The model is in the **Installed** list, and its **Active** menu names every channel. To use a different model on a channel, pick it from that model's **Activate for subsystem** menu.

Three things about this page:

- **Classification C-Channel and Carousel detect are one setting shown as two rows.** Set either one and both change.
- **The page lets you activate a model on a channel it was not trained for.** It marks the row with a note and does not stop you.
- **The change takes effect in a second or two.** Nothing needs restarting.

## 4. Check the sorting profile

Open **Profiles**. No profile ships on the machine, and the machine has one only once it is linked to Hive.

- **A machine linked to Hive** (step 8 of first setup, or **Settings** &rarr; **Hive**) with no profile starts on Hive's first default profile, **BrickLink categories**, with one bin for each BrickLink category. The page shows it under **On this machine**. To use another of Hive's defaults, press **Activate** on its card under **Profiles from Hive**. Activating a different profile asks you to empty the bins first, and bins are assigned again as pieces are sorted.
- **A machine that is not linked to Hive** has no profile, so every piece would end up in the discard bin. Link it, or press **Upload** and choose a profile file. Activating an uploaded profile asks how the bins should start. **Pre-assign from the rules** fills the bins in order: the first rule goes to the first bin of the first section of the first layer, the next rule to the next bin, and so on. Read that order off the screen and put your bins where the machine expects them. **Reset the bins** empties them instead and assigns each box to a bin the first time a piece needs one.

When you want your own boxes, [build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}) walks through making one in Hive and getting it onto this machine. [Decide your boxes]({{ '/hive/first-profile/decide-your-boxes/' | relative_url }}) describes the three defaults.

No bin is kept for pieces that no box takes, unless the profile sorts them by category or color. Those drop out of the bottom of the tower, so put a box or a tray under it before you start. A profile with more boxes than the machine has bins stops on **No bin for this piece** when a box finds none free. [Send it to your machine]({{ '/hive/first-profile/send-it-to-your-machine/#when-a-category-has-no-bin-free' | relative_url }}) has the details.

## 5. Check the machine is on the internet

Every piece is identified by a service on the internet. A machine with no connection still feeds, sees and moves pieces, and identifies none of them. [What leaves the machine]({{ '/sorter/what-leaves-the-machine/' | relative_url }}) covers what is sent.

You need no account and no key for this. The **OpenRouter** key on the Settings page is a separate, optional thing.

## Home the chute before every run

The aiming is saved. The homing is not. Home the chute from **Settings** &rarr; **Chute** &rarr; **Home to Endstop** before each run, and again after any stall. Until it is homed, the aiming numbers mean nothing.

## The finished result

A profile active and the chute homed.

<div class="img-placeholder">Screenshot of the dashboard with a profile active and the machine reading READY.</div>

## Next

[Preparing LEGO for a sort run]({{ '/sorter/preparing-lego/' | relative_url }}), which is what to take out of a tub of bulk LEGO before it goes in the bulk bucket, then [your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }}).
