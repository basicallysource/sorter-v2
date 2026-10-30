---
layout: default
title: Zones
type: reference
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-zones
kicker: SorterOS — Operate
author: barthel
lede: What the drop, precise and exit zones do on C-channel 2, C-channel 3 and the classification channel, and how to set them. Use it when you set up a channel's camera, or when pieces land, wait or leave in the wrong place.
permalink: /sorter/zones/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots of the current zone editor yet, and
  nobody has measured how wide each zone should be.
---

C-channel 2, C-channel 3 and the classification channel (C4) each have a camera. The machine decides what to do with a piece by where the camera sees it. Those places are the zones. C-channel 1 has no camera and no zones.

Pieces ride a band at the rim of the rotor, the **ring**, and always travel the same way: **drop**, then **precise**, then **exit**.

## The three zones

<ul class="bulleted-list">
  <li><strong>Drop (blue):</strong> where pieces land from the channel before. A piece here is moved along the channel. While a channel's drop zone holds a piece, the channel before it waits. On C4 it is where the piece is photographed and identified, so a piece first seen outside it is never identified and goes to misc.</li>
  <li><strong>Precise (magenta):</strong> a narrow band just before the exit. A piece here counts as being at the exit. On C4 it is the holding area: the piece waits here while it is identified and the chute is aimed. It is optional. A width of 0 means the channel has none.</li>
  <li><strong>Exit (red):</strong> the opening in the wall where pieces leave. On C-channel 2 and 3 a piece here is pushed onto the next channel in small steps, but only when that channel can take it, and otherwise the channel waits. On C4 the channel turns the piece off the exit into the chute.</li>
</ul>

C-channel 2 can push when C-channel 3's drop zone is empty. C-channel 3 can push when C4 is ready for a piece. <a href="{{ '/sorter/feeder-simple-pulse/' | relative_url }}">Feeder simple pulse</a> has the settings for these pushes.

A wider drop zone makes the channel before it wait more often. Fewer pieces arrive at once, and the channel is slower.

## Set the zones

Open the zones during [First setup]({{ '/sorter/first-setup/' | relative_url }}#review-zone) with **Review** on each camera card, or later on the channel's page under [Channel settings]({{ '/sorter/channel-settings/' | relative_url }}#zones). Do it for each of the three cameras.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/zones-c3-view-full-5b29aef61683.png" alt="C-channel 3 live view with its three zones shaded and labelled: the drop zone in blue, the precise zone in magenta and the exit zone in red"><figcaption>What the camera should see: the zones on the live view of C-channel 3. <cite>Screenshot courtesy of Daddy-O's Bricks - Bill. Labels added by Balloon.</cite></figcaption></figure>
</div>

<ol class="numbered-steps">
  <li>Press <strong>Find</strong>. It fits the ring to the rotor and puts the exit on the opening in the wall. It leaves the drop and precise widths as they are.</li>
  <li>Press <strong>Edit</strong>. Check each part against the picture, and change what is off:
    <ul class="bulleted-list">
      <li><strong>Ring:</strong> sits on the rim of the rotor, where pieces ride. It does not include the hub or the walls.</li>
      <li><strong>Drop:</strong> covers where pieces land from the channel before.</li>
      <li><strong>Exit:</strong> covers the opening in the wall.</li>
      <li><strong>Precise:</strong> sits just before the exit.</li>
    </ul>
  </li>
  <li>Press <strong>Save</strong>. The machine uses the new zones from its next picture.</li>
</ol>

To change a part, drag a zone to move it, drag an edge handle to make it wider or narrower, or turn the mouse wheel over a zone to widen it. Drag the circles to size the ring. Or press the smaller and bigger buttons beside a part. They change it by 1 or 5 each press, in degrees for a zone and in pixels for the ring.

Each part has a **Lock** switch. A locked part cannot be changed, and **Find** leaves it where it is. Lock a part once it is right. A badge beside each part says where its value came from.

### Starting values

On a machine with nothing saved, the editor starts with these widths.

| | Drop | Precise | Exit |
|---|---|---|---|
| C-channel 2 and 3 | 81° | 6° | 32° |
| C4 | 197° | 85° | 41° |

### Drawings and a finished setup

The drawings show the zones the editor starts with on a machine with nothing saved. 0° is to the right of the ring's center, and angles grow clockwise, the way pieces travel. Treat them as a start, not as settings for your machine.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/zones-c2-start-full-a90e126e0ca6.png" alt="Diagram of C-channel 2 as a ring, with the drop zone from 288 to 9 degrees, the precise zone from 163 to 169 and the exit zone from 169 to 201"><figcaption>C-channel 2. <cite>Render: Balloon.</cite></figcaption></figure>
</div>

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/zones-c3-start-full-7398927a3534.png" alt="Diagram of C-channel 3 as a ring, with the drop zone from 288 to 9 degrees, the precise zone from 163 to 169 and the exit zone from 169 to 201"><figcaption>C-channel 3. <cite>Render: Balloon.</cite></figcaption></figure>
</div>

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/zones-c4-start-full-b5f2207ac094.png" alt="Diagram of the classification channel as a ring, with the drop zone from 282 to 119 degrees, the precise zone from 148 to 233 and the exit zone from 233 to 274"><figcaption>Classification channel (C4). <cite>Render: Balloon.</cite></figcaption></figure>
</div>

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/sorter-first-setup-step7-three-channels-full-b17f9f7815d3.png" alt="The three camera cards side by side, each showing its live view with the drop, precise and exit zones shaded and labelled"><figcaption>Base line for how all 3 channels should look after setup. <cite>Screenshot courtesy of Daddy-O's Bricks - Bill. Labels added by Balloon.</cite></figcaption></figure>
</div>

## Cameras that do not see the whole ring

**C-channel 2 and C-channel 3 do not show their whole ring, and that is expected.** In the three-channel picture above, the top or bottom edge of each rotor is cut off by the frame. If the drop zone and the exit zone are both visible, the camera is positioned correctly even though part of the ring is not. Do not raise the lamp to fit more in. [Why the cameras are placed this way]({{ '/lab/sorter/' | relative_url }}#camera-crop) has the reasons and the numbers.

A piece that rides through the part of the ring the camera cannot see vanishes from the picture and reappears further round. To keep the channel turning while it is out of sight, tell the machine where that part is: open **Settings** → **Feeder simple pulse**, find the **Out of view** section, and set the **unseen arc start** (where pieces vanish) and **unseen arc end** (where they come back) for C2 and C3. Both are angles on the same scale as the drawings above, counted in the direction the channel turns. Leave both at 0 if the camera sees the whole ring.

## When pieces go wrong

<ul class="bulleted-list">
  <li><strong>A piece is seen but nothing happens.</strong> It is outside every zone. Open <a href="{{ '/sorter/perception-debug/' | relative_url }}">Perception debug</a> and compare where the piece sits with the zones.</li>
  <li><strong>Pieces on C4 end up in misc as <em>Never photographed</em>.</strong> The drop zone does not cover where pieces land. Move or widen it.</li>
  <li><strong>A piece lands on top of one still in the drop zone.</strong> Raise <strong>C2/C3 drop-zone occupancy hold</strong> in <a href="{{ '/sorter/feeder-simple-pulse/' | relative_url }}">Feeder simple pulse</a>.</li>
  <li><strong>The channel before is slow, and pieces arrive one at a time.</strong> Narrow the drop zone.</li>
  <li><strong>Pieces vanish on one part of the ring and reappear further round.</strong> The camera does not see that part. Set the <strong>Out of view</strong> arc, see <a href="#cameras-that-do-not-see-the-whole-ring">Cameras that do not see the whole ring</a>.</li>
</ul>
