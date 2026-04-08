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

- **[Install the Sorter on a Linux machine]({{ '/sorter/installation/' | relative_url }})** — the one-command install path for Debian 12 / Ubuntu 24.04 / Pi OS Bookworm. The path you walk once per machine.
- **[Install the Sorter by hand]({{ '/sorter/install-by-hand/' | relative_url }})** — the manual sequence, for when the installer does not yet support your platform.

## Operate

- **[Your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }})** — the end-to-end happy path: pick a profile, feed the machine, check a bin, stop cleanly.
- **[Sorter troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }})** — symptom-led entries for install, first-run, and runtime problems.

## Under the hood

- **[Sorter architecture]({{ '/sorter/architecture/' | relative_url }})** — how the coordinator, the three subsystem state machines, the vision manager, the machine platform abstraction, and the SvelteKit UI fit together. For contributors touching the code.
- **[Sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }})** — the on-disk shape of `sorting_profile.json` — rules, conditions, `part_to_category`, set inventories. Accurate for `schema_version: 1`.

## Coming soon

These flows do not yet have dedicated pages:

- **Setup wizard** — the first-boot flow: cameras, lighting, homing, chamber zones, servos, SortHive link.
- **Operating the UI at scale** — running long sessions, reviewing classification samples, tuning vision, checking runtime health.

Until those land, the authoritative sources are `software/README.md`, `software/client/coordinator.py`, and the in-app [`/styleguide`]({{ '/lab/styleguide/' | relative_url }}) route which renders the live component set.
