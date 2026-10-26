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
  <li><strong>Exit (red):</strong> the opening in the wall where pieces leave. On C-channel 2 and 3 a piece here is pushed onto the next channel in small steps, but only when that channel can take it, and otherwise the channel waits. On C4 the platter turns the piece off the exit into the chute.</li>
</ul>

C-channel 2 can push when C-channel 3's drop zone is empty. C-channel 3 can push when C4 is ready for a piece. <a href="{{ '/sorter/feeder-simple-pulse/' | relative_url }}">Feeder simple pulse</a> has the settings for these pushes.

A wider drop zone makes the channel before it wait more often. Fewer pieces arrive at once, and the channel is slower.

## Set the zones

Open the zones during [First setup]({{ '/sorter/first-setup/' | relative_url }}#review-zone) with **Review** on each camera card, or later on the channel's page under [Channel settings]({{ '/sorter/channel-settings/' | relative_url }}#zones). Do it for each of the three cameras.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/sorter-first-setup-step7-zone-editor-full-8149e45a5d8b.png" alt="The zone editor over a live C-channel view, with every handle labelled: center, inner, outer, drop start, drop end, precise start, precise end, exit start, exit end and exit outer"><figcaption>What the camera should see, and a starting point for setting the zones. <cite>Screenshot courtesy of Daddy-O's Bricks - Bill.</cite></figcaption></figure>
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

## When pieces go wrong

<ul class="bulleted-list">
  <li><strong>A piece is seen but nothing happens.</strong> It is outside every zone. Open <a href="{{ '/sorter/perception-debug/' | relative_url }}">Perception debug</a> and compare where the piece sits with the zones.</li>
  <li><strong>Pieces on C4 end up in misc as <em>Never photographed</em>.</strong> The drop zone does not cover where pieces land. Move or widen it.</li>
  <li><strong>A piece lands on top of one still in the drop zone.</strong> Raise <strong>C2/C3 drop-zone occupancy hold</strong> in <a href="{{ '/sorter/feeder-simple-pulse/' | relative_url }}">Feeder simple pulse</a>.</li>
  <li><strong>The channel before is slow, and pieces arrive one at a time.</strong> Narrow the drop zone.</li>
  <li><strong>Pieces vanish on one part of the ring and reappear further round.</strong> The camera does not see that part. Set the <strong>Out of view</strong> arc, see <a href="{{ '/sorter/first-setup/' | relative_url }}#review-zone">First setup</a>.</li>
</ul>
