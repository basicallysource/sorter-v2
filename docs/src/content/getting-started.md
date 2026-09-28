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

Sorter V2 is not a kit. There is nothing to order in one box: you buy the parts, print the plastic and put it together yourself, from these instructions. What the finished machine sorts, and what it will not, is on the [home page]({{ '/' | relative_url }}).

**It is a big job, not a hard one.** No single step is difficult, but there are thousands of parts, and turning them into a working machine takes months. Treat it as a project, not an experiment you can abandon cheaply halfway.

**The instructions are in use but not finished.** Of the {{ site.data.docs_status.how_to }} hardware pages with steps on them, {{ site.data.docs_status.verified }} have been followed on a real machine and {{ site.data.docs_status.drafts }} are unverified first drafts. Every page says which it is at the top.

**Time.** Printing is the longest part. A 3 layer machine is about {{ site.data.build_scale.small.printed_hours }} hours of printing on one printer, and a real build runs about twice that, because the printer stands finished waiting for a plate change. A 5 layer set of parts has taken about three months on one printer. Parts arrive over several weeks, and assembly runs alongside the printing.

**Space.** A 3 layer machine stands about 1.45 m (4 ft 9 in) to the top of the bulk bucket you pour the LEGO into, and each extra layer adds 160 mm (6.3 in). You also need a bench to build on and somewhere to keep a few thousand parts sorted while you work.

**Cost.** These are rough estimates from US prices in September 2026, not quotes, and they leave out the 3D printer.

- **A 1 layer machine: roughly US$1,400 to 1,700** in parts and filament. That is most of the money, because it carries everything that is built only once: the Orange Pi, the cameras, the control board, the power supply, the feeder and most of the motors.
- **Each extra layer: roughly US$100 to 150**, plus about US$40 of filament if you print that layer's bins rather than use boxes you already have.
- So **3 layers is roughly US$1,600 to 1,900** and **5 layers roughly US$1,800 to 2,200**.

Buying in Europe, the UK or Australia usually costs more once shipping and import tax are added. The [bill of materials](https://parts-calculator.basically.website/hardware) prices every part that has a US listing at your own layer count ("select all" gives the total). The Orange Pi, the screws, the 2020 extrusion, the circuit boards, the harness connectors and the plywood have no price there yet, and they are a large part of the gap between that total and the figures above.

[Hardware]({{ '/hardware/' | relative_url }}) has the full breakdown: how tall a machine to build, the parts count and filament for 3 and 5 layers, and the two things you may not be able to make yourself.

## What skills I should have

You do not need to be an engineer, and none of the build is specialist work.

**Taken as read.** You can run a 3D printer and print a part from an STL file. You are at ease with hex keys, side cutters, wire strippers and pliers, and you can work from a parts list.

**Taught here, at the point you need it.** [Heat-set inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}), [crimping contacts onto wire]({{ '/hardware/helpers/channel-stepper-lead/' | relative_url }}) and [using a multimeter]({{ '/hardware/helpers/multimeter/' | relative_url }}). Those pages start from the tool in your hand, so you can arrive at them having never done it.

**Some soldering.** Nothing on the machine needs fine electronics work, but a few joints do need an iron: [four solder jumpers on the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}), and a spliced wire under adhesive-lined heat shrink on [the chute stepper lead]({{ '/hardware/helpers/chute-stepper-lead/' | relative_url }}) and [the board's 24 V lead]({{ '/hardware/helpers/board-24v-lead/' | relative_url }}). If you have never soldered, practise on scrap wire first. The Pico comes with its pins already fitted, and the LED strips take a clamp-on connector.

**Not needed at all.** No CAD, no PCB design and no programming, to build the machine or to run it.

## What tools I need

Each page also lists the tools its own steps need, so you can check before you start a step.

**For the build**

- A 3D printer with a bed of at least 256 x 256 mm, and a slicer. See [Printing the parts]({{ '/hardware/printing/' | relative_url }}).
- Hex keys: 2, 2.5, 3 and 4 mm. They are the tool you will use most.
- A soldering iron and solder, plus adhesive-lined heat shrink. The iron also melts in the heat-set inserts if you have no insert press.
- A multimeter with a continuity buzzer.
- Side cutters, wire strippers and needle-nose pliers.
- A crimp tool for open-barrel contacts, and one for insulated terminals. You can skip both by [ordering the harness ready made]({{ '/hardware/parts/harness-order/' | relative_url }}).
- Screwdrivers: a small flat one for screw-terminal plugs, a small Phillips, and one that fits the power supply's M3.5 terminal screws.
- An 8 mm spanner, for the M5 nuts.
- A mallet or hammer, with a cloth to protect the printed brackets.
- A tape measure.

**Worth having**

- A heat-set insert press. A 3 layer machine has {{ site.data.build_scale.small.heat_inserts }} inserts to set, and a press keeps them straight.
- A drill or electric screwdriver with hex bits, including a long one that reaches between the layers. There are hundreds of screws.

**For the software**

- A computer with a microSD card reader, and a phone or an Ethernet cable to your router. See [Sorter OS]({{ '/sorter/installation/sorter-os/' | relative_url }}).
- A paper printer, for the camera focus chart.

**Not needed.** No saw and no laser cutter. The aluminium extrusion can be ordered cut to length, and the flat parts are cut for you by a service or a maker space. Cardboard bins are the one exception, and [Install the bins]({{ '/hardware/assembly/install-bins/' | relative_url }}) has a route by hand with a knife and a ruler.

## I want to build one

Read these three in order.

- **[Hardware]({{ '/hardware/' | relative_url }})**: the size of the job. How tall a machine to build, what it costs in parts and printing time, and the two things you may not be able to make yourself. Read it before you buy filament.
- **[Bill of materials](https://parts-calculator.basically.website/hardware)**: everything to buy, with vendor links and part numbers, at your own layer count. The site root lists the parts to print, and [/framing](https://parts-calculator.basically.website/framing) is the aluminium cut list.
- **[Assembly]({{ '/hardware/assembly/' | relative_url }})**: the build order, section by section, ending in [Software setup]({{ '/hardware/software-setup/' | relative_url }}) and then the [Sorter]({{ '/sorter/' | relative_url }}) section.

## I want to help build the project

- **Mechanical / CAD**: The project uses [Onshape](https://www.onshape.com/) (free, web-based, collaborative). Every V2 document is public and listed in the repo's `mechanical/README.md`; the folder holding them is private, so ask in the [Discord](https://discord.gg/6PZtqkwtaS) to be added to it. Start by browsing the V2 CAD and checking open bounties for mechanical tasks.
- **Electronics**: PCB schematics are in KiCad, in the repo under `electronics/KiCad/`. Background in EE or PCB layout is valuable.
- **Software**: Python backend + SvelteKit frontend. See the [Sorter install guide]({{ '/sorter/installation/' | relative_url }}).
- **ML / Vision**: Classification research, training data collection, model optimization. See [Classification research]({{ '/lab/classification-research/' | relative_url }}) and [Object detection research]({{ '/lab/object-detection/' | relative_url }}).

To run the software from source you need Python 3.12+, Node.js 20+ and pnpm. The install script handles dependencies on Debian 12 / Ubuntu 24.04 / Pi OS Bookworm. Building a machine does not need any of this: the [Sorter install guide]({{ '/sorter/installation/' | relative_url }}) has a pre-built image.

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
