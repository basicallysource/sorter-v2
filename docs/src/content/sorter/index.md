---
layout: default
title: SorterOS
type: landing
section: sorter
slug: sorter
kicker: Local Machine Software
lede: SorterOS is the Sorter V2 local software, the Python backend that drives the hardware and the SvelteKit UI that operates it. Install it, operate it, and read how it works under the hood.
permalink: /sorter/
---

## Install

- **[Installation]({{ '/sorter/installation/' | relative_url }})** — the three routes: the SorterOS image for the Orange Pi 5, the one-command installer for generic Linux, or the sequence by hand.

## Flash the control board before the wizard

The board needs its firmware before the wizard can see it. Controller Discovery only lists boards that already answer on USB serial, so a board with nothing on it is invisible there and the step reports `No MCU buses found`.

With SorterOS running, flash it from **Settings** &rarr; **Control board**: pick a release (or upload a `.uf2` directly) and flash it over the Pico's USB serial connection. **The asset you want is the `distribution` one for your board revision**, which is the all-in-one build for a machine with a single control board. A v1.3 board takes the `v1-2` build. A board that has never been flashed is a special case, because it enumerates as an `RPI-RP2` drive rather than a serial port and needs the **Recovery flash** option instead. [SorterOS troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}) has those steps.

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
- **[Bins and profiles]({{ '/sorter/bins-and-profiles/' | relative_url }})**: what Hive and the machine each call things, how bins get their categories, the 3D page, keeping a profile's bins when you switch profiles, and what happens when a bin is full.
- **[Shutting down the machine]({{ '/sorter/safe-shutdown/' | relative_url }})** — the two proper ways to power it down, and why pulling the plug is a last resort.
- **[SorterOS troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }})** — symptom-led entries for install, first-run, and runtime problems.

## Using the UI

Reference pages for the parts of the SorterOS interface you use after setup. Some have no entry in the top menu, and each page says how to reach it.

<ul class="bulleted-list">
  <li><strong><a href="{{ '/sorter/dashboard/' | relative_url }}">The dashboard</a></strong>: camera tiles, hardware state, incidents and recent pieces, plus the Runtime, Set progress and Parts checklist pages.</li>
  <li><strong><a href="{{ '/sorter/records/' | relative_url }}">Records</a></strong>: lifetime figures, runs, pieces and incidents. <a href="{{ '/sorter/tracked-piece/' | relative_url }}">The piece page</a> shows everything recorded about one piece.</li>
  <li><strong><a href="{{ '/sorter/logs/' | relative_url }}">Logs</a></strong>: read the backend log in the browser, with search and a level filter.</li>
  <li><strong><a href="{{ '/sorter/channel-settings/' | relative_url }}">Channel settings</a></strong>: each channel's camera, Picture, Detection and LED panels, and its rotor controls.</li>
  <li><strong><a href="{{ '/sorter/perception-debug/' | relative_url }}">Perception debug</a></strong>: what the detector sees on each channel, which boxes the machine acts on, and where the zones are.</li>
  <li><strong><a href="{{ '/sorter/feeder-simple-pulse/' | relative_url }}">Feeder simple pulse</a></strong> and <strong><a href="{{ '/sorter/tuning/' | relative_url }}">Tuning</a></strong>: every tuning setting, with its default.</li>
  <li><strong><a href="{{ '/sorter/stallguard/' | relative_url }}">StallGuard</a></strong> and <strong><a href="{{ '/sorter/diagnostics/' | relative_url }}">Diagnostics</a></strong>: the stall check, and the Performance, Cycle time, Jitter test and Power stress test pages.</li>
  <li><strong><a href="{{ '/sorter/incident-handling/' | relative_url }}">Incident handling</a></strong>: what the machine does when something goes wrong mid-sort.</li>
  <li><strong><a href="{{ '/sorter/networking/' | relative_url }}">Networking</a></strong> and <strong><a href="{{ '/sorter/training-data/' | relative_url }}">Training data</a></strong>: Wi-Fi and Tailscale, and the Data, Uploads and Training runs pages.</li>
</ul>

## Under the hood

- **[Dev flow]({{ '/sorter/dev-flow/' | relative_url }})** — the dev backend and UI services, how to enable them, and the difference between a soft restart and a full restart.
- **[Sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }})** — the on-disk shape of `sorting_profile.json` — rules, conditions, `part_to_category`, set inventories. Accurate for `schema_version: 1`.
- **[machine.toml reference]({{ '/sorter/machine-toml-reference/' | relative_url }})** — every field in the machine-specific config file: servo, chute, carousel, stepper bindings and overrides, cameras, and GPIO LEDs. This lives in the docs site, not the SorterOS UI.
