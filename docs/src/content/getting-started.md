---
title: Getting started
type: tutorial
audience: newcomer, either building a machine or joining the project
applies_to: sorter v2
owner: docs
last_verified: 2026-09-28
section: home
slug: getting-started
kicker: Start Here
lede: What Sorter V2 is, how to build one, and how to work on it.
permalink: /getting-started/
---

## What I should know

Sorter V2 is not a kit yet. You buy the parts, print the plastic and build it yourself from these instructions. What the machine sorts is on the [home page]({{ '/' | relative_url }}).

**It is a big job, not a hard one.** Thousands of parts and months of work. [Hardware]({{ '/hardware/' | relative_url }}) has the size of the job for 3 and 5 layers.

**Printing takes the longest**, months on one printer. See [what the print figures mean]({{ '/hardware/#what-the-print-figures-mean' | relative_url }}).

**Height is your choice.** Each layer adds 160 mm. See [how tall the machine is]({{ '/hardware/#you-choose-how-tall-the-machine-is' | relative_url }}).

**The instructions are not finished.** Of the {{ site.data.docs_status.how_to }} hardware pages with steps, {{ site.data.docs_status.verified }} have been followed on a real machine and {{ site.data.docs_status.drafts }} are first drafts. Every page says which it is.

**Cost, as a rough guide:** about US$1,400 to 1,700 for 1 layer, and about US$100 to 150 for each extra layer. That is parts and filament at US prices in September 2026, without the 3D printer. Expect more outside the US, for shipping and import tax. The [bill of materials](https://parts-calculator.basically.website/hardware) prices the parts at your layer count; its total is lower, because some parts have no price there yet.

## What skills I should have

You do not need to be an engineer.

**Taken as read.** You can run a 3D printer, and you are at ease with hex keys, side cutters, wire strippers and pliers.

**Taught here, when you need it.** [Heat-set inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}), [crimping]({{ '/hardware/helpers/channel-stepper-lead/' | relative_url }}) and [using a multimeter]({{ '/hardware/helpers/multimeter/' | relative_url }}).

**A little soldering.** [Four solder jumpers on the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}). The cable joints are crimped, and soldering them is only an alternative.

**Not needed.** No CAD, no PCB design and no programming.

## What tools I need

Each page lists the tools for its own steps.

**For the whole build:**

<ul class="bulleted-list">
  <li>A 3D printer with a bed of at least 256 x 256 mm. See <a href="{{ '/hardware/printing/' | relative_url }}">Printing the parts</a>.</li>
  <li>Hex keys: 2, 2.5, 3 and 4 mm.</li>
  <li>A soldering iron, and flux-cored solder. Set the iron to around 350 C, or 320 C if your solder is leaded. A standard build solders four jumpers on the control board. The cable joints, on the <a href="{{ '/hardware/helpers/chute-stepper-lead/' | relative_url }}">chute stepper lead</a> (<code>CH</code>), the <a href="{{ '/hardware/helpers/board-24v-lead/' | relative_url }}">board's 24 V lead</a> (<code>W1</code>) and the <a href="{{ '/hardware/helpers/led-strip/' | relative_url }}">LED lamp cables</a> (<code>L1</code> to <code>L3</code>, <code>L1p</code> to <code>L3p</code>), are crimped or clamped, and soldering is only their alternative.</li>
  <li>Only if you solder a cable joint instead of crimping it: adhesive-lined heat shrink, to insulate and seal it. The lamp cables (<code>L1</code> to <code>L3</code>, <code>L1p</code> to <code>L3p</code>) use 3:1 dual-wall tubing, 3 mm (1/8 in) before shrinking, in 25 mm (1 in) pieces. You also need a heat gun, or the side of a lighter flame, to shrink it.</li>
  <li>A multimeter with a continuity buzzer.</li>
  <li>Side cutters, wire strippers and needle-nose pliers.</li>
  <li>A ratcheting crimp tool for open-barrel contacts (Dupont, JST-PH, JST-VH), unless you <a href="{{ '/hardware/parts/harness-order/' | relative_url }}">order the harness ready made</a>.</li>
  <li>Insulated-terminal crimping pliers, with a die for 22 AWG (0.33 mm²) to 16 AWG (1.3 mm²) wire, for butt connectors, fork terminals and receptacles. Not needed if you solder those joints.</li>
  <li>Small flat and Phillips screwdrivers, an 8 mm spanner, a mallet and a tape measure.</li>
</ul>

**Worth having:**

<ul class="bulleted-list">
  <li>A heat-set insert press.</li>
  <li>A drill or electric screwdriver with hex bits, including a long one.</li>
</ul>

**Not needed:**

<ul class="bulleted-list">
  <li>A saw.</li>
  <li>A laser cutter.</li>
</ul>

See [two things you may not be able to make yourself]({{ '/hardware/#two-things-you-may-not-be-able-to-make-yourself' | relative_url }}).

## I want to build one for myself

Read these three in order.

- **[Hardware]({{ '/hardware/' | relative_url }})**: the size of the job. How tall a machine to build, what it costs in parts and printing time, and the two things you may not be able to make yourself. Read it before you buy filament.
- **[Bill of materials](https://parts-calculator.basically.website/hardware)**: everything to buy, with vendor links and part numbers, at your own layer count. The site root lists the parts to print, and [/framing](https://parts-calculator.basically.website/framing) is the aluminium cut list.
- **[Assembly]({{ '/hardware/assembly/' | relative_url }})**: the build order, section by section, ending in [Software setup]({{ '/hardware/software-setup/' | relative_url }}) and then the [SorterOS]({{ '/sorter/' | relative_url }}) section.

## I want to contribute to the project

- **Mechanical / CAD**: The project uses [Onshape](https://www.onshape.com/) (free, web-based, collaborative). Every V2 document is public and listed in the repo's `mechanical/README.md`; the folder holding them is private, so ask in the [Discord](https://discord.gg/6PZtqkwtaS) to be added to it. Start by browsing the V2 CAD and checking open bounties for mechanical tasks.
- **Electronics**: PCB schematics are in KiCad, in the repo under `electronics/KiCad/`. Background in EE or PCB layout is valuable.
- **Software**: Python backend + SvelteKit frontend. See the [SorterOS install guide]({{ '/sorter/installation/' | relative_url }}).
- **ML / Vision**: Classification research, training data collection, model optimization. See [Classification research]({{ '/lab/classification-research/' | relative_url }}) and [Object detection research]({{ '/lab/object-detection/' | relative_url }}).

To run the software from source you need Python 3.12+, Node.js 20+ and pnpm. The install script handles dependencies on Debian 12 / Ubuntu 24.04 / Pi OS Bookworm. Building a machine does not need any of this: the [SorterOS install guide]({{ '/sorter/installation/' | relative_url }}) has a pre-built image.

## Key resources

| Resource | Link |
|----------|------|
| Bill of materials and printed parts | [parts-calculator.basically.website](https://parts-calculator.basically.website/) |
| Assembly instructions | [Assembly]({{ '/hardware/assembly/' | relative_url }}) |
| GitHub organization | [github.com/basicallysource](https://github.com/basicallysource) |
| V2 CAD (active) | [Onshape document](https://cad.onshape.com/documents/59b1b8e595daebcff3d3711c/w/77adcf46916b421c55e6a947/e/626a2d725f7a102031079019) |
| Brickognize API docs | [api.brickognize.com/docs](https://api.brickognize.com/docs) |
| Shared Google Drive | [Design docs and presentations](https://drive.google.com/drive/folders/19ZV8AnAjYpwCfDaukLdA2u8vyNN1H8Yf) |
| Documentation site | [docs.basically.website](https://docs.basically.website/) |
| Basically on YouTube | [youtube.com/@basicallyhandle](https://www.youtube.com/@basicallyhandle) |
| Community build videos | A contributor's own machine, built differently from the one documented here: [overview](https://www.youtube.com/watch?v=NfSrd4IZd58) and [engineering deep dive](https://www.youtube.com/watch?v=I6AhcB-rUWc) |

## How the project works

- **Contributions** go through pull requests on GitHub. Branch protection is enabled on main. The project is source-available; the repo's [CONTRIBUTING.md](https://github.com/basicallysource/sorter-v2/blob/main/CONTRIBUTING.md) has the licensing details.
- **Bounties** are posted on the Discord bounty board for discrete, high-priority tasks. Claim one if you can deliver within the posted timeline.
- **Communication** happens on Discord. Engineering sync calls happen periodically and are recorded for async viewing.
- **CAD collaboration** uses Onshape shared documents. The individual documents are public; for the shared folder, ask in the Discord with your Onshape email.
- **Design reviews** are scheduled for electronics and mechanical changes before merging.
