---
layout: default
title: Sorter
type: landing
section: sorter
slug: sorter
kicker: Local Machine Software
lede: The Sorter V2 local software — the Python backend that drives the hardware and the SvelteKit UI that operates it. Install it, operate it, and read how it works under the hood.
permalink: /sorter/
---

## Install

- **[Installation]({{ '/sorter/installation/' | relative_url }})** — the three routes: the SorterOS image for the Orange Pi 5, the one-command installer for generic Linux, or the sequence by hand.

## Set up a new machine, in this order

<ol class="numbered-steps">
  <li><strong><a href="{{ '/sorter/first-setup/' | relative_url }}">First setup in the UI</a></strong>. The setup wizard: name the machine, find the boards, check motion and endstops, assign the servos and the cameras, link Hive.</li>
  <li><strong><a href="{{ '/sorter/camera-calibration/' | relative_url }}">Camera calibration</a></strong>. Focus each camera against a printed Siemens Star.</li>
  <li><strong><a href="{{ '/sorter/chute-calibration/' | relative_url }}">Chute calibration</a></strong>. Home the chute, capture two bins to set the bin locations, and test every bin it can reach.</li>
  <li><strong><a href="{{ '/sorter/before-first-sort-run/' | relative_url }}">Before your first sort run</a></strong>. The last five settings to check in the UI.</li>
  <li><strong><a href="{{ '/sorter/preparing-lego/' | relative_url }}">Preparing LEGO for a sort run</a></strong>. What to take out of a tub of bulk LEGO before it goes in the bulk bucket, and what each thing does to the machine if it stays in.</li>
  <li><strong><a href="{{ '/sorter/tutorials/first-sort-run/' | relative_url }}">Your first sort run</a></strong>. The end-to-end happy path: pick a profile, feed the machine, check a bin, stop cleanly.</li>
</ol>

## Operate

- **[Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }})** — decide your boxes, have Hive's assistant write the rules, and assign the result to the machine.
- **[Shutting down the machine]({{ '/sorter/safe-shutdown/' | relative_url }})** — the two proper ways to power it down, and why pulling the plug is a last resort.
- **[Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }})** — symptom-led entries for install, first-run, and runtime problems.

## Under the hood

- **[Dev flow]({{ '/sorter/dev-flow/' | relative_url }})** — the dev backend and UI services, how to enable them, and the difference between a soft restart and a full restart.
- **[Sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }})** — the on-disk shape of `sorting_profile.json` — rules, conditions, `part_to_category`, set inventories. Accurate for `schema_version: 1`.
- **[machine.toml reference]({{ '/sorter/machine-toml-reference/' | relative_url }})** — every field in the machine-specific config file: servo, chute, carousel, stepper bindings and overrides, cameras, and GPIO LEDs. This lives in the docs site, not the Sorter UI.

## Coming soon

These flows do not yet have dedicated pages:

- **Operating the UI at scale** — running long sessions, reviewing classification samples, tuning vision, checking runtime health.

Until those land, the authoritative sources are `software/README.md`, `software/sorter/backend/coordinator.py`, and the in-app [`/styleguide`]({{ '/lab/styleguide/' | relative_url }}) route which renders the live component set.
