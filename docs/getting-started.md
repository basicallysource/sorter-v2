---
title: Getting started
type: tutorial
audience: newcomer who discovered the project
applies_to: sorter v2
owner: docs
last_verified: 2026-04-14
section: home
slug: getting-started
kicker: Start Here
lede: Everything a new contributor needs to orient themselves — what the project is, what you need, and where to jump in.
permalink: /getting-started/
---

## What Sorter V2 is

Sorter V2 is an open-source LEGO sorting machine. Feed bulk LEGO into a hopper, and the machine singulates each piece, classifies it by part number (and optionally color), and drops it into the correct bin. The entire project — CAD, PCB schematics, firmware, host software — is MIT-licensed. V1 exists as a reference but is no longer maintained; V2 is the active development target.

## Current status

| Subsystem | Status | Notes |
|-----------|--------|-------|
| C-channel singulation | Working | 3-stage design, ~330 pieces/hour, targeting 1,000 |
| Classification (Brickognize API) | Working | 98.5% accuracy on supported parts, 0.56s avg response |
| Object detection (chamber zone) | Working | NanoDet + YOLO11s trained, benchmarked on Pi 5 + Orange Pi 5 |
| Host software (Python backend) | WIP | Coordinator, state machines, vision manager functional |
| SvelteKit UI | WIP | Setup wizard, camera calibration, runtime dashboard in progress |
| Hive community platform | WIP | Upload pipeline, shared profiles, crowd verification |
| Electronics / PCB | WIP | Feeder + distribution board schematics in review (Rev 0.3) |
| Hardware CAD | WIP | V2 CAD mostly complete in Onshape, validation in progress |
| Build guide / assembly docs | Stub | No step-by-step guide yet |

## What you need

### Hardware

| Item | Details | Approx. cost |
|------|---------|-------------|
| Raspberry Pi 5 | Main host computer (vision, logic, coordination) | $80 |
| AI accelerator | Hailo-8 AI HAT (Pi 5) or RKNN (Orange Pi 5) | $25-70 |
| Cameras | 3× OV9732 100° wide-angle USB cameras | $30 (3-pack) |
| Stepper motors + drivers | 3× steppers, TMC2209 drivers on shared UART bus | $40 |
| Servos | ST3215 serial bus servos for distribution | $30 |
| 3D-printed parts | Structural and mechanical — PLA/PETG | Filament cost |
| Extrusion + fasteners | 2020 aluminum extrusion, M3 heat-set inserts, M8 bolts | $50 |
| Vibration motor | RS-385 DC 12V for feeder | $5 |
| Springs | ISO 10243 die springs (8×4×20mm yellow, from 3D printer suppliers) | $5 |

**Total materials target:** ~$500. Everything is off-the-shelf, 3D-printable, or laser-cuttable.

### Tools

Soldering iron (PINECIL V2 recommended), pliers, wire strippers, screwdrivers, hacksaw.

### Software

Python 3.12+, Node.js 20+, pnpm. The install script handles dependencies on Debian 12 / Ubuntu 24.04 / Pi OS Bookworm.

## Pick a contribution track

- **Mechanical / CAD** — The project uses [Onshape](https://www.onshape.com/) (free, web-based, collaborative). DM Spencer your email for document access. Start by browsing the V2 CAD and checking open bounties for mechanical tasks.
- **Electronics** — PCB schematics are in KiCad. Active work on feeder and distribution board reviews. Background in EE or PCB layout is valuable.
- **Software** — Python backend + SvelteKit frontend. See the [Sorter install guide]({{ '/sorter/installation/' | relative_url }}) and [architecture overview]({{ '/sorter/architecture/' | relative_url }}).
- **ML / Vision** — Classification research, training data collection, model optimization. See [Classification research]({{ '/lab/classification-research/' | relative_url }}) and [Object detection research]({{ '/lab/object-detection/' | relative_url }}).

## Key resources

| Resource | Link |
|----------|------|
| GitHub organization | [github.com/basicallysource](https://github.com/basicallysource) |
| V2 CAD (active) | [Onshape document](https://cad.onshape.com/documents/59b1b8e595daebcff3d3711c/w/77adcf46916b421c55e6a947/e/626a2d725f7a102031079019) |
| V1 CAD (reference only) | [Onshape document](https://cad.onshape.com/documents/57a6deba5df3f2fefb14bfa4/w/69c1555983f7ea624f0cf5a5/e/62f915a1f9533b22259df854) |
| Brickognize API docs | [api.brickognize.com/docs](https://api.brickognize.com/docs) |
| Shared Google Drive | [Design docs and presentations](https://drive.google.com/drive/folders/19ZV8AnAjYpwCfDaukLdA2u8vyNN1H8Yf) |
| Documentation site | [docs.basically.website](https://docs.basically.website/) |

## How the project works

- **Contributions** go through pull requests on GitHub. Branch protection is enabled on main.
- **Bounties** are posted on the Discord bounty board for discrete, high-priority tasks. Claim one if you can deliver within the posted timeline.
- **Communication** happens on Discord. Engineering sync calls happen periodically and are recorded for async viewing.
- **CAD collaboration** uses Onshape shared documents. Request access by DMing Spencer your Onshape email.
- **Design reviews** are scheduled for electronics and mechanical changes before merging.
