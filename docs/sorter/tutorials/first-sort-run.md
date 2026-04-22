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

This tutorial assumes the first-boot setup wizard is done and `./dev.sh` is running. If anything stalls, jump to [troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}) — this walkthrough does not recover from broken state.

## Before you start

- Setup wizard finished (no wizard at `http://localhost:5173/`).
- `./dev.sh` running. `curl -fsS http://localhost:8000/api/health` returns JSON.
- 10–20 mixed bricks, plates, tiles. Skip stickered/printed parts on your first run.
- Empty bins in their slots. Nothing left in the chute, carousel, or chamber.

## 1. Pick a profile

Open the UI → **Profiles** → click **Deploy to this machine** on **Presort**. Presort has eight categories plus a catch-all "Other", so nothing falls through.

## 2. Confirm the dashboard is ready

Back on the home dashboard, check:

- **Lifecycle: READY** (not `PAUSED` or `RUNNING`).
- **All cameras live** — every tile shows a moving image.
- **Chute homed.** If not, **Hardware → Chute → Home**.
- **Carousel idle** — no part visible in the dropzone.

## 3. Load five parts

Place five parts loosely in the feeder hopper. Not the whole pile — five is slow enough to spot trouble before it compounds.

## 4. Start the run

Click **Start run**. Lifecycle: `READY → PAUSED → RUNNING`. Within ~10 s you should see the feeder agitating, parts appearing in a C-channel, and the MOG2 overlay highlighting the first one.

Nothing happening? Stop the run and read the `[backend]` lines in `./dev.sh`.

## 5. Watch one part go through

The five transitions you should see, in order:

1. `feeder: idle → feeding`
2. `classification: idle → detecting`
3. `classification: detecting → snapping` (1–2 s pause — this is the OpenRouter call)
4. `distribution: idle → positioning → ready`
5. `distribution: ready → sending` — chute drops the part into a bin.

If it stalls in `detecting`, see [Carousel keeps rotating past the part]({{ '/sorter/troubleshooting/' | relative_url }}#carousel-keeps-rotating-past-the-part--classification-never-completes).

## 6. Drain the rest

Once the first part lands, top up the hopper with the remaining parts. Expect 4–8 parts/min on a first run. Don't hand-feed the carousel in `auto_channels` mode — the state machine doesn't expect it.

## 7. Check a bin

When the dashboard shows no pending work, **Stop run**. Open the Bricks bin — it should contain only bricks. A misroute is a classification accuracy issue, not a machine failure; flag it from **Classification Samples** for later.

## 8. Shut down clean

- Remove any part still sitting in a C-channel, the carousel, or the chamber. Stuck parts at shutdown break the next MOG2 bootstrap.
- Backend can keep running — no need to `Ctrl-C` `./dev.sh`.

## What you learned

The full happy path: profile → start → feed → classify → distribute → check → stop. Every run uses the same five transitions.

## Next

- Edit a profile: **Profiles → Edit**. Schema: [profile reference]({{ '/sorter/profile-reference/' | relative_url }}).
- Read the [architecture]({{ '/sorter/architecture/' | relative_url }}) to understand what runs under the hood.
- Bookmark [troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}).
