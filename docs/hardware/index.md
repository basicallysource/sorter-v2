---
layout: default
title: Hardware
type: landing
section: hardware
slug: hardware
kicker: The Physical Machine
lede: The mechanics, electronics, BOM, and assembly notes for the Sorter V2 hardware. This section is still a stub — content is being promoted here as it stabilizes.
permalink: /hardware/
---

## Coming soon

This section will cover:

- **Mechanics** — chamber geometry, belt path, servo mounts, camera cage.
- **Electronics** — stepper drivers, servo controller, limit switches, lighting, the camera and the AI HAT cabling.
- **[Bill of materials]({{ 'hardware/BOM' | relative_url }})** — the canonical BOM with sources, part numbers, and substitutes.
- **[Assembly]({{ '/hardware/assembly' | relative_url }})** — the maintained order of operations and the quirks worth warning future builders about.

Until those pages land, the authoritative place for hardware decisions is the per-machine profile files under `software/sorter/backend/irl/example_configs/` and the running `HANDOFF.md` at the repo root.
