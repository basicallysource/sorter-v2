---
title: Getting started
type: tutorial
audience: newcomer, either building a machine or joining the project
applies_to: sorter v2
owner: docs
last_verified: 2026-09-24
section: home
slug: getting-started
kicker: Start Here
lede: What Sorter V2 is, how to build one, and how to work on it.
permalink: /getting-started/
---

## What Sorter V2 is

Sorter V2 is an open-source LEGO sorting machine. Feed bulk LEGO into a hopper, and the machine singulates each piece, classifies it by part number (and optionally color), and drops it into the correct bin. The project is source-available; see [CONTRIBUTING.md](https://github.com/basicallysource/sorter-v2/blob/main/CONTRIBUTING.md) for licensing details. V1 exists as a reference but is no longer maintained; V2 is the active development target.

Machines are built and running, and they sort every day. It is not a product: there is no kit, no price, and nothing for sale. What exists is the design, the parts list, and these instructions.

## I want to build one

Read these three in order.

- **[Hardware]({{ '/hardware/' | relative_url }})** — the size of the job. How tall a machine to build, what it costs in parts and printing time, and the two things you may not be able to make yourself. Read it before you buy filament.
- **[Bill of materials](https://parts-calculator.basically.website/hardware)** — everything to buy, with vendor links and part numbers, at your own layer count. The site root lists the parts to print, and [/framing](https://parts-calculator.basically.website/framing) is the aluminium cut list.
- **[Assembly]({{ '/hardware/assembly/' | relative_url }})** — the build order, section by section, ending in [Software setup]({{ '/hardware/software-setup/' | relative_url }}) and then the [Sorter]({{ '/sorter/' | relative_url }}) section.

The instructions are written and being built from, but they are not finished. Of the {{ site.data.docs_status.how_to }} hardware pages with steps on them, {{ site.data.docs_status.verified }} have been followed on a real machine and {{ site.data.docs_status.drafts }} are unverified first drafts. Every page says which it is at the top.

Each page lists the tools that page needs. There is no single tool list for the whole build, because what you need in front of you depends on the step you are standing at.

## I want to help build the project

- **Mechanical / CAD** — The project uses [Onshape](https://www.onshape.com/) (free, web-based, collaborative). Every V2 document is public and listed in the repo's `mechanical/README.md`; the folder holding them is private, so ask in the [Discord](https://discord.gg/6PZtqkwtaS) to be added to it. Start by browsing the V2 CAD and checking open bounties for mechanical tasks.
- **Electronics** — PCB schematics are in KiCad, in the repo under `electronics/KiCad/`. Background in EE or PCB layout is valuable.
- **Software** — Python backend + SvelteKit frontend. See the [Sorter install guide]({{ '/sorter/installation/' | relative_url }}).
- **ML / Vision** — Classification research, training data collection, model optimization. See [Classification research]({{ '/lab/classification-research/' | relative_url }}) and [Object detection research]({{ '/lab/object-detection/' | relative_url }}).

To run the software from source you need Python 3.12+, Node.js 20+ and pnpm. The install script handles dependencies on Debian 12 / Ubuntu 24.04 / Pi OS Bookworm. Building a machine does not need any of this: the [Sorter install guide]({{ '/sorter/installation/' | relative_url }}) has a pre-built image.

## Key resources

| Resource | Link |
|----------|------|
| Bill of materials and printed parts | [parts-calculator.basically.website](https://parts-calculator.basically.website/) |
| Assembly instructions | [Assembly]({{ '/hardware/assembly/' | relative_url }}) |
| GitHub organization | [github.com/basicallysource](https://github.com/basicallysource) |
| V2 CAD (active) | [Onshape document](https://cad.onshape.com/documents/59b1b8e595daebcff3d3711c/w/77adcf46916b421c55e6a947/e/626a2d725f7a102031079019) |
| V1 CAD (reference only) | [Onshape document](https://cad.onshape.com/documents/57a6deba5df3f2fefb14bfa4/w/69c1555983f7ea624f0cf5a5/e/62f915a1f9533b22259df854) |
| Brickognize API docs | [api.brickognize.com/docs](https://api.brickognize.com/docs) |
| Shared Google Drive | [Design docs and presentations](https://drive.google.com/drive/folders/19ZV8AnAjYpwCfDaukLdA2u8vyNN1H8Yf) |
| Documentation site | [docs.basically.website](https://docs.basically.website/) |
| Basically on YouTube | [youtube.com/@basicallyhandle](https://www.youtube.com/@basicallyhandle) |
| Community build videos | A contributor's own machine, built differently from the one documented here: [overview](https://www.youtube.com/watch?v=NfSrd4IZd58) and [engineering deep dive](https://www.youtube.com/watch?v=I6AhcB-rUWc) |

## How the project works

- **Contributions** go through pull requests on GitHub. Branch protection is enabled on main.
- **Bounties** are posted on the Discord bounty board for discrete, high-priority tasks. Claim one if you can deliver within the posted timeline.
- **Communication** happens on Discord. Engineering sync calls happen periodically and are recorded for async viewing.
- **CAD collaboration** uses Onshape shared documents. The individual documents are public; for the shared folder, ask in the Discord with your Onshape email.
- **Design reviews** are scheduled for electronics and mechanical changes before merging.
