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

1. Open **Settings**, then **C-channel 2**, **C-channel 3** or **Classification channel**.
2. Press **Detection** on that channel's page.
3. Press **See the live detection results**.

Or go straight to `/perception-debug` on the machine's address (`http://sorter.local/perception-debug` on the SorterOS image).

The page shows one tile per channel: **C-channel 2**, **C-channel 3** and **Carousel / classification (channel 4)**. Press a tile's expand button to see it bigger.

<div class="img-placeholder">Screenshot of the Perception debug page in the Cropped view, with all three channel tiles showing boxes and the text panel.</div>

## The controls

- **Cropped (production)** and **Full frame (debug)** choose which of the two views every tile shows. They are explained below.
- **Refresh** fetches a new frame. **The frames do not update on their own.** Each tile is a still of the last frame the detector worked on, so press **Refresh** whenever you want to see what is happening now.

A tile that says **No frame is available** has no picture to show: either that channel's detector is not running, or it has not finished its first detection yet. Give a machine that has just started a few seconds and press **Refresh**.

## Cropped view

This is the real thing: exactly what the machine detects and acts on. The detector does not look at the whole camera image. It looks at a rectangle cut around the channel, and then throws away every box whose centre is not on the channel.

What the colors mean:

- **Green box:** a detection that is on the channel. These are the pieces the machine reacts to.
- **Orange box:** a detection the detector made but the channel filter threw away, because it is not on the channel.
- **White rectangle:** the crop, the only part of the image the detector saw.
- **Cyan outline:** the edge of the channel.
- **Magenta dot:** the centre of the channel's ring.
- **Grey outline:** on C-channel 2 and 3, a band just past the exit. A piece wholly inside it has left the channel. The machine still sees it, but does not count it as on the channel.
- **Blue, red and magenta tint:** the channel's zones, from the [zone editor]({{ '/sorter/first-setup/' | relative_url }}#review-zone). Blue is the **drop** zone, red is the part of the **exit** zone before the precise part, and magenta is the **precise** zone.

The text panel in the top left of each frame says what produced it:

- **ch, role, cam_src:** the channel number, its camera role, and the camera it is reading.
- **frame, crop:** the size of the frame, and the size of the crop the detector was given.
- **algo, model:** the detection method and the exact model file. This is where you confirm the model you chose in [Before your first sort run]({{ '/sorter/before-first-sort-run/' | relative_url }}) is the one running.
- **imgsz, conf:** the size the model works at, and the confidence a detection needs to be kept.
- **core, infer:** the channel mask in use, and how long the last detection took in milliseconds.
- **raw, kept, rejected:** how many boxes the detector drew, how many are green, and how many are orange.
- **state:** what the machine takes from the frame. `pieces` is the number of pieces on the channel. `in_drop`, `in_exit` and `in_precise` say whether a piece is in that zone. `in_exit` also goes true when a piece is in the precise zone, because the precise zone is the last part of the exit.
- **sections:** how many 1-degree slices of the ring each zone covers.

## Full frame view

The same model, run on the whole camera image with no crop. The page asks the machine for a second detection per cycle to draw it, which is only done while the page is open and stops about ten seconds after you leave. The first load can take a moment, and the page asks again once by itself.

- **Green box:** a detection whose centre is on the channel.
- **Orange box:** a detection anywhere else in the frame.

The white crop rectangle is still drawn, for comparison, but is not applied in this view.

## What to look for

Switch between the two views on the same piece.

- **A piece with no box in either view.** The detector does not recognise it. Check the model in the text panel, then that the camera is in focus ([camera calibration]({{ '/sorter/camera-calibration/' | relative_url }})) and lit.
- **A box in Full frame but none in Cropped.** The crop is leaving the piece out. The channel area is drawn too small, or in the wrong place, so review the zone for that channel in the setup wizard or its settings page.
- **Orange boxes on pieces that are on the channel.** The detector found them and the channel filter rejected them. The channel outline does not cover where they sit, so redraw it.
- **Orange boxes on things that are not pieces.** The detector is producing junk, and the filter is doing its job. It is a model problem, not a zone problem.
- **A green box, but the machine ignores it.** Look at the zones and the `state` line. A piece that is not inside a zone does not trigger the drop or exit logic, and `in_drop` or `in_exit` stays false.

If the frames look wrong in more than one of these ways at once, start with the model and the focus. Zones cannot fix a detector that does not see the piece.
