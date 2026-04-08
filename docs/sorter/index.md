---
layout: default
title: Sorter
section: sorter
slug: sorter
kicker: Local Machine Software
lede: The Sorter V2 local software — the Python backend that drives the hardware and the SvelteKit UI that operates it. This section is still a stub — content is being promoted here as it stabilizes.
permalink: /sorter/
---

## Coming soon

This section will cover:

- **Architecture** — how the coordinator, vision manager, machine platform, and UI fit together.
- **Setup wizard** — the first-run flow: cameras, lighting, homing, chamber zones, servos, SortHive link.
- **Profiles** — how per-machine configuration is structured and where it lives on disk.
- **Operating the UI** — running sessions, reviewing uploads, tuning vision, checking runtime health.
- **Troubleshooting** — the common first-run problems and how to recognize them.

Until those pages land, the authoritative sources are `software/README.md`, `software/client/coordinator.py`, and the in-app [`/styleguide`]({{ '/lab/styleguide/' | relative_url }}) route which renders the live component set.
