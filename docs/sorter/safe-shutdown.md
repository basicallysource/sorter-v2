---
layout: default
title: Shutting down the machine
type: how-to
section: sorter
slug: sorter-safe-shutdown
kicker: Sorter — Operations
lede: Two proper ways to power the machine down, and why pulling the plug is a last resort.
permalink: /sorter/safe-shutdown/
---

The machine's computer writes files continuously while it runs. Cutting power mid-write can corrupt those files and leave the machine unable to start. Use one of the two shutdowns below, then cut power.

## Option 1: from the UI

Click the dropdown at the top right of the UI and select **Full Machine Power Down**.

<img class="doc-figure" src="https://img.basically.website/web/sorter/safe-shutdown/full-machine-power-down-menu.jpg" alt="The top-right UI dropdown open, showing the Full Machine Power Down action">

## Option 2: the button on the Orange Pi

Press the small black button on the side of the Orange Pi (circled below).

<img class="doc-figure" src="https://img.basically.website/web/sorter/safe-shutdown/orange-pi-power-button.jpg" alt="Orange Pi 5 board with the side power button circled in red">

With either option, the full shutdown takes about a minute and a half. Wait for it to finish before flipping the switch or unplugging the machine.

## Cutting power directly

Flipping the power switch or pulling the plug while the machine is running skips the shutdown entirely. Any file being written at that instant can be corrupted, and the machine may not start again until it is serviced.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Cut power directly only in an emergency (a jam you cannot stop, smoke, anything unsafe). It is an emergency stop, not a shutdown.</p>
</div>
