---
layout: default
title: Your first sort run
type: tutorial
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-first-sort-run
kicker: Sorter — Tutorial
lede: Run your first sort end-to-end. Pick a profile, feed a small handful of parts, watch them land in the right bins, stop cleanly. About fifteen minutes.
permalink: /sorter/tutorials/first-sort-run/
---

Everything here happens in the browser. If anything stalls, jump to [troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}); this walkthrough does not recover from broken state.

## Before you start

- The machine is powered on and its UI opens in your browser. On SorterOS that is `http://sorter.local/`.
- [Before your first sort run]({{ '/sorter/before-first-sort-run/' | relative_url }}) is done: a profile is deployed and the chute is homed.
- 10 to 20 mixed bricks, plates and tiles, picked over as [Preparing LEGO]({{ '/sorter/preparing-lego/' | relative_url }}) describes. Leave stickered and printed parts out of your first run.
- Empty bins in their slots. Nothing left in the chute, the channels, the carousel or the chamber.

## 1. Pick a profile

Open the UI → **Profiles** → click **activate** on **Presort**. Presort has eight categories plus a catch-all "Other", so nothing falls through.

## 2. Confirm the dashboard is ready

Back on the home dashboard, check:

- **Lifecycle: READY** (not `PAUSED` or `RUNNING`).
- **All cameras live** — every tile shows a moving image.
- **Chute homed.** If not, **Settings → Chute → Home to Endstop**.
- **Carousel idle** — no part visible in the dropzone.

## 3. Load five parts

Place five parts loosely in the feeder hopper. Not the whole pile — five is slow enough to spot trouble before it compounds.

## 4. Start the run

Click **Start run**. Lifecycle: `READY → PAUSED → RUNNING`. Within about ten seconds you should see the feeder agitating, parts appearing in a C-channel, and the first one highlighted in that channel's camera view.

Nothing happening? Stop the run and see [troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}).

## 5. Watch one part go through

The five transitions you should see, in order:

<ol class="numbered-steps">
  <li><code>feeder: idle &rarr; feeding</code></li>
  <li><code>classification: idle &rarr; detecting</code></li>
  <li><code>classification: detecting &rarr; snapping</code>. A pause of a second or two: the machine is sending the picture away to be identified. <a href="{{ '/sorter/what-leaves-the-machine/' | relative_url }}">What leaves the machine</a> covers what goes.</li>
  <li><code>distribution: idle &rarr; positioning &rarr; ready</code></li>
  <li><code>distribution: ready &rarr; sending</code>, and the chute drops the part into a bin.</li>
</ol>

If it stalls in `detecting`, see [Carousel keeps rotating past the part]({{ '/sorter/troubleshooting/' | relative_url }}#carousel-keeps-rotating-past-the-part--classification-never-completes).

## 6. Drain the rest

Once the first part lands, top up the hopper with the remaining parts. Expect 4 to 8 parts a minute on a first run. Do not hand-feed the carousel unless your machine setup is **Operator-fed carousel**; on any other setup the machine does not expect it.

## 7. Check a bin

When the dashboard shows no pending work, **Stop run**. Open the Bricks bin — it should contain only bricks. A misroute is a classification accuracy issue, not a machine failure; flag it from **Classification Samples** for later.

## 8. Shut down clean

Remove any part still sitting in a C-channel, the carousel or the chamber. A part left behind confuses the next run's first frames.

Leaving the machine switched on is fine. When you do want it off, [shutting down the machine]({{ '/sorter/safe-shutdown/' | relative_url }}) is the safe way; cutting power while it runs can corrupt the card.

## The finished result

A bin with only the one category in it, and the machine stopped cleanly.

<div class="img-placeholder">Photo of a bin lifted out of its bay after a first run, holding only bricks.</div>

## What you learned

The full happy path: profile, start, feed, classify, distribute, check, stop. Every run uses the same five transitions.

## Next

- Edit a profile: **Profiles → Edit**. Schema: [profile reference]({{ '/sorter/profile-reference/' | relative_url }}).
- Bookmark [troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}).
