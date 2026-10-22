---
layout: default
title: Shutting down the machine
type: how-to
section: sorter
slug: sorter-safe-shutdown
kicker: SorterOS — Operations
lede: Two proper ways to power the machine down, and why pulling the plug is a last resort.
permalink: /sorter/safe-shutdown/
warning: >-
  **SorterOS changes quickly.** This page describes what each step does, but a
  button's name, or where it is, may have changed since this page was written,
  so it keeps screenshots to a minimum.
---

The machine's computer writes files continuously while it runs. Cutting power mid-write can corrupt those files and leave the machine unable to start. Use one of the two shutdowns below, then cut power.

## Option 1: from the UI

Click the **⋯** menu at the top right of the UI and select **Power down the machine**. Press **Power down the machine** again to confirm.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/sorter-safe-shutdown-full-machine-power-down-menu-full-fb7d3867ed81.jpg" alt="The top-right UI dropdown open, showing the Full Machine Power Down action">
  <figcaption>An older version of the menu, where it was called <strong>Full Machine Power Down</strong>. <cite>UI screenshot. Who took it isn't recorded.</cite></figcaption>
</figure>

The UI then shows **Powering down** and stays on that screen, even after the machine is off and even if you unplug it. It never tells you the shutdown has finished, so watch the board instead (below).

## Option 2: the button on the Orange Pi

Press the small black button on the side of the Orange Pi once (circled below). That begins the shutdown procedure.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/sorter-safe-shutdown-orange-pi-power-button-full-a39aa5a490fc.jpg" alt="Orange Pi 5 board with the side power button circled in red">
  <figcaption><cite>Photographer not recorded.</cite></figcaption>
</figure>

## Knowing it has finished

With either option, the full shutdown takes about a minute and a half. It has finished when the red and green lights on the Orange Pi have stopped blinking. Wait for that before flipping the switch or unplugging the machine.

## Cutting power directly

Flipping the power switch or pulling the plug while the machine is running skips the shutdown entirely. Any file being written at that instant can be corrupted, and the machine may not start again until it is serviced.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Cut power directly only in an emergency (a jam you cannot stop, smoke, anything unsafe). It is an emergency stop, not a shutdown.</p>
</div>
