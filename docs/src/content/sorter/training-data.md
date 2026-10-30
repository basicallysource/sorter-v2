---
layout: default
title: Training data
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-training-data
kicker: SorterOS — Operate
author: jensr80
lede: Choose what the machine shares with each Hive, watch what has been uploaded, set how it captures training frames, and run labelled color-training runs. All under Settings, Data.
permalink: /sorter/training-data/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and the wording of the
  messages on these pages has not been checked against a real machine.
---

**Settings**, then **Data** is where the machine's data leaves for a Hive, and where it is kept until then. It has three pages in the side menu: **Data**, and under it **Uploads** and **Training runs**. All of it only matters once a machine is connected to a Hive in **Settings**, then **Hive**. Without one, nothing is sent.

What each kind of data carries, and everything else the machine sends anywhere, is in [what leaves the machine]({{ '/sorter/what-leaves-the-machine/' | relative_url }}). What Hive does with camera frames is in [Reviewing samples]({{ '/hive/review-samples/' | relative_url }}).

## Data

The **Data** page has three panels.

<div class="img-placeholder">Screenshot of Settings > Data with the Shared with Hive, Sample capture and On this machine panels.</div>

### Shared with Hive

One row per kind of data the machine can send. Each row has an info icon that says what it carries. Most have a switch. **Machine telemetry** says **Always** instead of a switch: while a Hive is connected, it is always sent.

<ul class="bulleted-list">
  <li><strong>Agree first.</strong> Until you agree, nothing is shared with a Hive except the keep-alive. A box at the top says <strong>Nothing is shared with a Hive yet</strong>: look over the list, then press <strong>Agree</strong>. If what the machine shares has changed since you agreed, the box says <strong>What this sorter shares has changed</strong> and the button is <strong>OK</strong>.</li>
  <li><strong>Every Hive, or one.</strong> The <strong>Shared with</strong> menu (shown when at least one Hive is connected) starts on <strong>Every Hive</strong>. Switches there apply to every Hive that has no setting of its own. Choose a Hive by name to see and change what only that Hive gets.</li>
  <li><strong>A change applies at once</strong>, including to uploads that are already waiting: a kind that is off is not sent.</li>
  <li><strong>Back to what it was.</strong> A row that differs from its default (or, for one Hive, from what every Hive gets) is tinted, with a button that puts it back. <strong>Reset to defaults</strong> at the top of the panel does it for the whole list. For a single Hive the button reads <strong>Use every Hive's settings</strong>.</li>
</ul>

### Sample capture

Camera frames taken while the machine sorts, to train detection. The panel says it changes nothing about sorting. The frames are saved to a capped store on the machine and uploaded to Hive in the background, as the **Full camera frames** kind above.

<ul class="bulleted-list">
  <li><strong>Capture training frames</strong> takes the latest frame from every live camera, only while the machine is sorting.</li>
  <li><strong>Annotate with OpenRouter</strong> runs the Gemini detector on each frame before it is saved, so the sample reaches Hive already outlined. It makes one OpenRouter call per frame per camera, and needs your own OpenRouter key. Off, or without a key, frames are saved and uploaded raw. See the OpenRouter part of <a href="{{ '/sorter/what-leaves-the-machine/' | relative_url }}">what leaves the machine</a>.</li>
  <li><strong>Decay capture rate</strong> takes a burst of frames when a run starts, then slows to a floor over a ramp, so the machine does not keep saving near-identical frames. The panel shows the schedule in force ("Every ... slowing to every ... over ...") and the interval it is on now. <strong>Reset decay</strong> starts the burst again. Four fields tune it: <strong>Burst interval</strong> (seconds), <strong>Floor interval</strong> (minutes), <strong>Ramp</strong> (hours) and <strong>Jitter</strong> (a percentage, random wobble so captures are not perfectly regular).</li>
  <li><strong>Capture rate</strong> replaces the decay fields when Decay capture rate is off: frames per minute per camera, at most 0.5 (one every 2 minutes).</li>
  <li><strong>Sample store size</strong> is the most the machine keeps (in GB), never more than Hive allows. When it is full, samples every Hive already has are deleted first, then the oldest.</li>
</ul>

Burst interval, Floor interval, Ramp and Sample store size follow the limits Hive sets until you type a value. The box shows Hive's value as a hint, and the reset button on the row (or clearing the box) goes back to following Hive. The burst interval is never faster than Hive allows or than one frame every 2 minutes.

Under the rows, the panel counts frames saved since the machine started, and warns about frames dropped because saving could not keep up or skipped because the disk was low. If it says the sample collector has not started, the machine has no camera service yet, and the switches are disabled.

### On this machine

What is stored here until every Hive that should have it does. The table has one row per kind, with **Stored**, **Size** (and the cap, where there is one) and **Waiting for a Hive**. Below it, the free disk space. Saving samples stops when free space falls below the limit the line shows, and starts again when there is that much free.

**Delete all samples on this machine** appears when there are samples. It asks you to confirm, then deletes every training sample stored here, including those no Hive has yet. This cannot be undone.

## Uploads

**Settings**, then **Data**, then **Uploads** shows what this machine has sent to a Hive, what is waiting, and what will never be sent. It refreshes every 30 seconds.

<ul class="bulleted-list">
  <li><strong>Hive</strong> and <strong>Time shown</strong> (24 hours or 7 days) are at the top right, when at least one Hive is connected. A Hive the machine cannot reach is marked <strong>Unreachable</strong> in the menu, and a box says nothing is being sent to it and what is waiting stays here until it answers. With no Hive connected the page says <strong>No Hive is connected</strong> and links to Hive settings.</li>
  <li><strong>Uploaded</strong> is the bytes and items sent in the time shown. <strong>Waiting now</strong> is the items still to send. <strong>Not uploaded</strong> is what was skipped to keep up, or deleted here before it was sent. <strong>Held back</strong> is how long uploads waited for the upload budget, the limit on bytes and files a minute that the page prints below the numbers.</li>
  <li><strong>Uploaded</strong> chart: bytes sent each hour, by kind. Point at an hour for its numbers.</li>
  <li><strong>Waiting to upload</strong> chart: items waiting at the end of each hour. A mark along the bottom is an hour when some items were skipped or deleted before they could be sent.</li>
  <li><strong>By kind</strong> table: for each kind, the last upload, how many were uploaded and their size, how many are waiting now, and how many were not uploaded. A kind marked <strong>Off for this Hive</strong> is switched off in the Shared with Hive panel for that Hive.</li>
</ul>

Nothing on this page changes anything. To stop a kind going, switch it off on the Data page. To stop uploads piling up, see [Hive uploads pile up and never drain]({{ '/sorter/troubleshooting/' | relative_url }}#hive-uploads-pile-up-and-never-drain).

## Training runs

A training run labels every piece the machine sees with a color you feed it, so the pieces can train color recognition. The machine sorts as usual while one runs. **Settings**, then **Data**, then **Training runs**. The old `/settings/training-data` addresses forward to this page.

**Training mode changes where pieces go if you set a Bin.** With **Bin** set to a bin, every piece goes to that bin while training mode is on, and the chute stays there. Left on **None (route by the profile)**, pieces go where the sorting profile sends them.

<div class="img-placeholder">Screenshot of Settings > Data > Training runs with the Training mode panel and the Runs table.</div>

### Start a run

<ol class="numbered-steps">
  <li>Turn on <strong>Training mode</strong>. While it is on, the dashboard shows the training run in place of Recent pieces. Turning it off ends the run.</li>
  <li>Leave <strong>Mode</strong> on <strong>Color</strong>, the only mode. It sets what a run labels its pieces with.</li>
  <li>Choose a <strong>Bin</strong>, or leave it on <strong>None (route by the profile)</strong>. The menu lists the bins on enabled layers. See the warning above.</li>
  <li>Under <strong>Color</strong>, press the color button and pick the color you are feeding. The picker shows colors used lately first, then the commonest, and has a search. If the list says the color list has not loaded, the machine has not reached Hive yet.</li>
  <li>Press <strong>Start run</strong>. It is disabled until training mode is on and a color is picked (<strong>Pick a color first</strong>).</li>
</ol>

While a run is open, the **Run** row shows a **Collecting** tag, when it started, and how many pieces and segments it has. A run collects every piece the machine sees until you press **End run**, across pauses.

**Pick another color while the run is open** and the run starts a new segment of that color at once. Pieces keep the color they were fed with, so pieces still on the way from before the change keep the old label.

### The Runs table

Newest first (the newest 100). Each row has **Started**, **Duration** (or **Collecting**), **Colors**, **Pieces**, **Labeled** and **Excluded**. A run you excluded has an **Excluded** badge. Press a row to open it.

### One run

The page is titled **Run from** and the start time. It shows the colors, how long it ran, and the counts for segments, pieces, labeled and excluded.

<ul class="bulleted-list">
  <li><strong>Back to training runs</strong> returns to the table.</li>
  <li><strong>End run</strong> appears while it is collecting and ends it.</li>
  <li><strong>Exclude run</strong> marks the whole run as excluded. The button then reads <strong>Include run</strong> and brings it back.</li>
</ul>

The **Pieces** list shows each piece the machine saw, newest first, with a picture, its part, the color it was labelled with and the time. A divider appears wherever the segment changes, with that segment's colors, its piece count and when it ran. Pieces seen outside any segment sit under **Outside a segment**. If the machine's own color for a piece differs from the label, the row also shows **Machine** and that color.

<ul class="bulleted-list">
  <li><strong>Click a piece</strong> to exclude it, and again to bring it back. An excluded piece is faded and badged <strong>Excluded</strong>. Use it for a piece that is clearly the wrong color, or one that did not come from what you were feeding.</li>
  <li><strong>All</strong>, <strong>Disagrees with the machine</strong> and <strong>Excluded</strong> filter the list. Disagrees shows the labelled, not excluded pieces whose label differs from the machine's color (its corrected color, if you corrected one). That is the quickest way to find mislabelled pieces.</li>
  <li><strong>Load more</strong> loads the next pieces. The page shows how many of the total are loaded.</li>
  <li>While the run is collecting, new pieces appear on their own every few seconds, until you have loaded more than the first page. They wait while the pointer is over the list, so nothing moves under a click.</li>
</ul>

### What is sent

The label, the run and its segments, and whether a piece or run is excluded, go to Hive with the piece records. That makes them part of the **Piece records** kind on the Data page: if that is off for a Hive, runs and labels are not sent to it. Piece pictures are a separate kind.
