---
layout: default
title: Perception debug
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-perception-debug
kicker: SorterOS — Operate
author: reveryx
lede: See what the detector sees on each channel, which boxes the machine acts on, and where the zones sit. Use it when pieces are missed, or when a channel behaves as if it cannot see them.
permalink: /sorter/perception-debug/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and the wording of the text
  panel on each frame has not been checked against a real one.
---

Perception is the part of SorterOS that finds pieces on the three camera channels and decides where each one is: still on the channel, in the drop zone, in the exit zone. The **Perception debug** page draws that decision onto the latest camera frame of each channel, so you can see it instead of guessing from how the machine behaves.

It only reads. Opening it does not change a setting or move anything.

## Open it

There is no entry for it in the top menu.

<ol class="numbered-steps">
  <li>Open <strong>Settings</strong>, then <strong>C-channel 2</strong>, <strong>C-channel 3</strong> or <strong>Classification channel</strong>.</li>
  <li>Press <strong>Detection</strong> on that channel's page.</li>
  <li>Press <strong>See the live detection results</strong>.</li>
</ol>

Or go straight to `/perception-debug` on the machine's address (`http://sorter.local/perception-debug` on the SorterOS image).

The page shows one tile per channel: **C-channel 2**, **C-channel 3** and **Carousel / classification (channel 4)**. Press a tile's expand button to see it bigger.

<div class="img-placeholder">Screenshot of the Perception debug page in the Cropped view, with all three channel tiles showing boxes and the text panel.</div>

## The controls

<ul class="bulleted-list">
  <li><strong>Cropped (production)</strong> and <strong>Full frame (debug)</strong> choose which of the two views every tile shows. They are explained below.</li>
  <li><strong>Refresh</strong> fetches a new frame. <strong>The frames do not update on their own.</strong> Each tile is a still of the last frame the detector worked on, so press <strong>Refresh</strong> whenever you want to see what is happening now.</li>
</ul>

A tile that says **No frame is available** has no picture to show: either that channel's detector is not running, or it has not finished its first detection yet. Give a machine that has just started a few seconds and press **Refresh**.

## Cropped view

This is the real thing: exactly what the machine detects and acts on. The detector does not look at the whole camera image. It looks at a rectangle cut around the channel, and then throws away every box whose centre is not on the channel.

What the colors mean:

<ul class="bulleted-list">
  <li><strong>Green box:</strong> a detection that is on the channel. These are the pieces the machine reacts to.</li>
  <li><strong>Orange box:</strong> a detection the detector made but the channel filter threw away, because it is not on the channel.</li>
  <li><strong>White rectangle:</strong> the crop, the only part of the image the detector saw.</li>
  <li><strong>Cyan outline:</strong> the edge of the channel.</li>
  <li><strong>Magenta dot:</strong> the centre of the channel's ring.</li>
  <li><strong>Grey outline:</strong> on C-channel 2 and 3, a band just past the exit. A piece wholly inside it has left the channel. The machine still sees it, but does not count it as on the channel.</li>
  <li><strong>Blue, red and magenta tint:</strong> the channel's zones, from the <a href="{{ '/sorter/zones/' | relative_url }}">zone editor</a>. Blue is the <strong>drop</strong> zone, red is the part of the <strong>exit</strong> zone before the precise part, and magenta is the <strong>precise</strong> zone.</li>
</ul>

The text panel in the top left of each frame says what produced it:

<ul class="bulleted-list">
  <li><strong>ch, role, cam_src:</strong> the channel number, its camera role, and the camera it is reading.</li>
  <li><strong>frame, crop:</strong> the size of the frame, and the size of the crop the detector was given.</li>
  <li><strong>algo, model:</strong> the detection method and the exact model file. This is where you confirm the model you chose in <a href="{{ '/sorter/before-first-sort-run/' | relative_url }}">Before your first sort run</a> is the one running.</li>
  <li><strong>imgsz, conf:</strong> the size the model works at, and the confidence a detection needs to be kept.</li>
  <li><strong>core, infer:</strong> the channel mask in use, and how long the last detection took in milliseconds.</li>
  <li><strong>raw, kept, rejected:</strong> how many boxes the detector drew, how many are green, and how many are orange.</li>
  <li><strong>state:</strong> what the machine takes from the frame. <code>pieces</code> is the number of pieces on the channel. <code>in_drop</code>, <code>in_exit</code> and <code>in_precise</code> say whether a piece is in that zone. <code>in_exit</code> also goes true when a piece is in the precise zone, because the precise zone is the last part of the exit.</li>
  <li><strong>sections:</strong> how many 1-degree slices of the ring each zone covers.</li>
</ul>

## Full frame view

The same model, run on the whole camera image with no crop. The page asks the machine for a second detection per cycle to draw it, which is only done while the page is open and stops about ten seconds after you leave. The first load can take a moment, and the page asks again once by itself.

<ul class="bulleted-list">
  <li><strong>Green box:</strong> a detection whose centre is on the channel.</li>
  <li><strong>Orange box:</strong> a detection anywhere else in the frame.</li>
</ul>

The white crop rectangle is still drawn, for comparison, but is not applied in this view.

## What to look for

Switch between the two views on the same piece.

<ul class="bulleted-list">
  <li><strong>A piece with no box in either view.</strong> The detector does not recognise it. Check the model in the text panel, then that the camera is in focus (<a href="{{ '/sorter/camera-calibration/' | relative_url }}">camera calibration</a>) and lit.</li>
  <li><strong>A box in Full frame but none in Cropped.</strong> The crop is leaving the piece out. The channel area is drawn too small, or in the wrong place, so review the zone for that channel in the setup wizard or its settings page.</li>
  <li><strong>Orange boxes on pieces that are on the channel.</strong> The detector found them and the channel filter rejected them. The channel outline does not cover where they sit, so redraw it.</li>
  <li><strong>Orange boxes on things that are not pieces.</strong> The detector is producing junk, and the filter is doing its job. It is a model problem, not a zone problem.</li>
  <li><strong>A green box, but the machine ignores it.</strong> Look at the zones and the <code>state</code> line. A piece that is not inside a zone does not trigger the drop or exit logic, and <code>in_drop</code> or <code>in_exit</code> stays false.</li>
</ul>

If the frames look wrong in more than one of these ways at once, start with the model and the focus. Zones cannot fix a detector that does not see the piece.
