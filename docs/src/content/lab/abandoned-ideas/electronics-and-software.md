---
layout: default
title: Electronics and software
type: explanation
section: lab
slug: lab-abandoned-electronics-and-software
kicker: Design and research — Abandoned ideas
lede: Board mounts, the PSU box, Firmata and the ArUco tags: electronics and software choices that were replaced, and why.
permalink: /lab/variants/abandoned/electronics-and-software/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-11
---

Back to <a href="{{ '/lab/variants/abandoned/' | relative_url }}">Abandoned ideas</a>. Mounts and boxes for the electronics, and software choices that were replaced. Each entry says what the idea was and why it went, as far as the reasons are written down. The status of each is as of 11 October 2026.

## Boards on plates screwed to the extrusion

**What it was.** The control board and the Orange Pi each stood on a printed plate bolted to the 2020 extrusion, with a 40 mm fan on a bracket over the board.

**Why it was dropped.** The printed control board housing replaced the plate on 23 August 2026, and the printed Orange Pi housing replaced the other in September 2026. The reason for the move is not written down in the parts calculator. The fan bracket went because each housing now carries its own fan, or the Orange Pi's own heatsink fan does the job. Old photos still show the plates.

<ul class="bulleted-list">
  <li>The housings: <a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi housing</a></li>
</ul>

## The three-plate box for the power supply

**What it was.** Three printed plates screwed onto the Mean Well 24 V supply's own case.

**Why it was dropped.** The cap was not secure. The five-piece PSU housing, whose two lids screw down, replaced it in September 2026.

## Firmata for talking to the motor board

**What it was.** The first version of the machine used Firmata, a ready-made protocol for controlling a microcontroller from a computer.

**Why it was dropped.** Its 7-bit encoding mangled data, the project is effectively dead, and its threading behaved unreliably. The current firmware uses its own protocol, over USB. Klipper, ROS 2, Marlin and Wi-Fi to the board were also considered and rejected (<a href="{{ '/lab/software-architecture-decisions/' | relative_url }}">Software architecture decisions</a>).

## ArUco tags for finding the hardware in the picture

**What it was.** Small square printed markers (ArUco tags, 4 x 4 grid) fixed to the channels, the bulk bucket and the carousel trays. The software found them in the camera image and worked out from them where each channel's centre, exit and bulk boundary were, and which pieces were inside a drop zone. Slots for them were added to the stator, the light post cap and the carousel trays in January and February 2026 (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1473095560251572385">how they were meant to work</a>).

**Why it was dropped.** The zones are now drawn by the builder as polygons on the camera image, in the setup wizard, and nothing in the software reads a tag. The reasons written down:

<ul class="bulleted-list">
  <li><strong>Hand-drawn zones replaced them.</strong> By 1 March 2026 the tags had been removed from the feeder code in favour of polygons drawn by the user (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1477459759564324965">1 March</a>).</li>
  <li><strong>Lighting.</strong> One lamp had to expose both the pieces and the tags, and an overhead lamp washed the tags out (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1471915579232358471">13 February</a>, <a href="{{ '/lab/feeder-experiments/' | relative_url }}">Feeder experiments</a>).</li>
  <li><strong>Jitter.</strong> Detection of the tags moved from frame to frame, so smoothing had to be added (<a href="https://discord.com/channels/1430279849171222682/1437920132893511740/1475877127596281866">24 February</a>).</li>
  <li><strong>Not needed.</strong> On 31 March 2026 most of the tags were taken off a machine and it was judged that none might be needed in future (<a href="https://discord.com/channels/1430279849171222682/1440488123279736912/1488577122028224734">31 March</a>).</li>
</ul>

**What is left.** The recessed square on top of the light post cap is the pocket for a tag. It does nothing now, so you can print the cap and leave it empty. The tags still appear in the write-up on <a href="{{ '/lab/c-channel-singulation/' | relative_url }}">C-channel singulation</a>, which describes the early design.
