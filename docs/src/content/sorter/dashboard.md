---
layout: default
title: The dashboard
type: reference
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-dashboard
kicker: SorterOS — Operate
author: jensr80
lede: Watch the three camera channels, home or recover the machine, follow the pieces going through, and check how a run is going. Includes the Runtime page and the two pages that track how much of a set you have sorted.
permalink: /sorter/dashboard/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and the wording on screen has
  not been checked against a real machine.
---

The dashboard is the page you leave open while the machine sorts. It shows each camera channel live, the state of the hardware, the pieces as they are identified, and how fast the run is going. Four more pages are covered here because they answer the next questions: **Runtime** (where the machine spends its time), **Set progress** and the **Parts checklist** (how much of each set is sorted), and the checklist for a single set.

<div class="img-placeholder">Screenshot of the dashboard with the three camera tiles on the left, and Recent pieces and the Runtime panel in the column on the right.</div>

## Open it

Press **Dashboard**, the first item in the top menu, or go to the machine's address with no path (`http://sorter.local` on the SorterOS image).

On a machine that has never been set up, the first visit in a browser session opens the [setup wizard]({{ '/sorter/first-setup/' | relative_url }}) instead. **Dashboard** in the menu brings you back here.

If the page says **No machine selected**, connect to a machine in **Settings**.

## The top bar

The bar at the top of every page is where you control the machine.

<ul class="bulleted-list">
  <li><strong>The state badge</strong> beside the machine's name reads <strong>Ready</strong>, <strong>Standby</strong>, <strong>Homing</strong>, <strong>Initializing</strong>, <strong>Initialized</strong> or <strong>Error</strong>. A second badge, such as <strong>2/3 cameras</strong>, appears only when a camera is not online.</li>
  <li><strong>The sorting profile menu</strong> switches profile. It is hidden on a narrow screen. <a href="{{ '/sorter/bins-and-profiles/' | relative_url }}">Bins and profiles</a> covers switching.</li>
  <li><strong>Pause</strong> and <strong>Resume</strong> share one button, shown only while the state is <strong>Ready</strong> or <strong>Initialized</strong>. Resume is greyed out while a motor stall or a chute that needs homing is open, with a tooltip saying which: <em>Clear the motor stall before resuming</em> or <em>Re-home the chute before resuming</em>.</li>
  <li><strong>The ⋯ System menu</strong> holds the machine-wide actions below.</li>
</ul>

The System menu has:

<ul class="bulleted-list">
  <li><strong>Home</strong> (<strong>Re-home</strong> once the machine is ready): starts the hardware and moves every axis to its zero. There is no confirmation, so check nothing is in the way first.</li>
  <li><strong>Initialize without homing:</strong> only in <strong>Standby</strong> or <strong>Error</strong>. Starts the hardware without homing it, so motors and lamps can be used.</li>
  <li><strong>Restart the backend:</strong> asks you to confirm. A running sort or homing stops, the cameras and the hardware start again, and the page is unavailable for a few seconds.</li>
  <li><strong>Restart the machine:</strong> asks you to confirm. Reboots the whole machine, stops a running sort, and the page is unavailable for a couple of minutes.</li>
  <li><strong>Power down the machine:</strong> asks you to confirm, then shuts the machine down completely. Wait until it is fully off before cutting power, and read <a href="{{ '/sorter/safe-shutdown/' | relative_url }}">Shutting down the machine</a>.</li>
</ul>

A hardware fault that does not stop the machine shows as a red banner under the bar, with **Dismiss** and, when the machine needs homing, **Home**. A fault that does stop it opens a dialog with the message and **Home again**.

## Hardware state card

A card at the top of the right-hand column appears while the state is **Standby**, **Homing** or **Error**, and goes away once the machine is ready.

<ul class="bulleted-list">
  <li><strong>Standby</strong> with a <strong>Not homed</strong> badge: press <strong>Home</strong>. It starts the hardware and moves every axis to its zero. On a development machine without motor power there is also <strong>Sim home</strong>, which runs the same recovery and skips only the physical homing.</li>
  <li><strong>Homing:</strong> a spinner and the current step. Let it finish before starting a run. A <strong>Homing</strong> card at the top right shows the same step, and its <strong>Details</strong> opens a dialog.</li>
  <li><strong>Stopped</strong> with the fault's title and message: fix what the message says, then press <strong>Retry</strong>, which runs the same recovery as <strong>Home</strong>.</li>
</ul>

## Camera tiles

Three tiles show the channels live: **C-channel 2**, **C-channel 3** and **Classification channel**. Their buttons are:

<ul class="bulleted-list">
  <li><strong>Annotations</strong> (tooltip <em>Hide annotations</em> or <em>Show annotations</em>): draws what perception found on each frame. Green boxes are pieces. The zones are tinted blue (drop), orange-red (exit) and magenta (precise), and the channel's edge is outlined in cyan. These are the colors <a href="{{ '/sorter/perception-debug/' | relative_url }}">Perception debug</a> explains. The choice is remembered per camera in this browser.</li>
  <li><strong>Full screen</strong> enlarges the tile.</li>
  <li><strong>The turn control</strong> (a left arrow, an amount such as <strong>10°</strong>, a right arrow): see below.</li>
  <li><strong>Shake</strong>: see below.</li>
</ul>

A tile can also read **Reconnecting** (the camera says it is online but no frame has arrived for 3 seconds), **Camera offline**, or **No camera assigned**. The picture fades while the camera is not healthy.

### Turn a channel

The left arrow turns the channel counterclockwise and the right arrow clockwise, by the amount between them, in degrees of the channel itself. Press the amount to open **Each press turns**: choose **10°** or **180°**, or type any amount above 0 up to 360. The amount is remembered per channel in this browser.

**This moves the real channel at once, with no confirmation.** The machine refuses while it is homing or initializing, and if the hardware has not been started the tile says *Hardware not started. Press Home in the dashboard first.*

### Shake a channel

**Shake** opens a menu of five shakes, each with a one-line hint: **Brief** (a short, sharp burst), **Heavy stuck** (medium throw, medium length), **Soft and long** (gentle but long), **Big and hard** (big throw, strong jerk) and **Max shake** (the largest throw, strong). They are the same shakes the machine's automatic recovery uses, run once on that channel. Use one to free a piece that has stuck. It is refused while a recovery is already moving the channels, or while that channel is still moving.

## Incident card

When the machine hits a problem it cannot clear by itself, a yellow card appears in the right-hand column: a title (with the channel or motor it concerns), one line saying what to do, and buttons. Press the first button for the usual fix. If a button fails, the card shows why.

<ul class="bulleted-list">
  <li><strong>Stuck on the classification channel:</strong> a piece is not leaving. Take it off and press <strong>Done</strong>, or press <strong>Turn to clear</strong> to let the channel turn until it is empty. Turning to clear opens every layer door first, so what is still on the channel goes to the bottom bucket rather than a sorted bin.</li>
  <li><strong>A piece is going around the classification channel:</strong> it keeps coming back instead of falling off (the card suggests a tire). Take it off, then press <strong>Done</strong>.</li>
  <li><strong>A piece is stuck where pieces land:</strong> on C2 or C3 it does not move with the channel. Take it off, then press <strong>Done</strong>.</li>
  <li><strong>Motor stalled:</strong> check the named motor turns freely, then press <strong>Done</strong>. If the stall cost the chute its position, the button is <strong>Home chute</strong> instead.</li>
  <li><strong>Chute needs homing:</strong> press <strong>Home chute</strong>.</li>
  <li><strong>Bin doors not answering:</strong> check the door servos' cable and power, then press <strong>Done</strong>.</li>
  <li><strong>No bin for this piece:</strong> assign a bin or free one up, or press <strong>Send to bucket</strong>.</li>
</ul>

**Done** only tells the machine you dealt with it; it does not fix anything. While the machine is working on an incident automatically, the card shows a progress bar and a line reading *Step N of M* with what it is doing, and a **Stop** button. How each kind is handled is set on **Settings**, **Incidents**. Past incidents are in [Records]({{ '/sorter/records/' | relative_url }}).

## Recent pieces

This panel follows pieces through the classification channel. Click its title to collapse it; that is remembered in this browser. While training mode is on, a **Training data** panel with a **Training mode** badge takes its place ([Training data]({{ '/sorter/training-data/' | relative_url }})).

The list reads top to bottom as the pieces travel. Pieces on the channel now come first, the farthest from the exit at the top and the nearest just above the **Distributed** divider. Below the divider are the last 8 pieces delivered, newest first. An empty list says *No pieces yet*. Click a card for the [piece page]({{ '/sorter/tracked-piece/' | relative_url }}).

A card shows:

<ul class="bulleted-list">
  <li><strong>The picture.</strong> While a piece is being recognized it flashes through the photos taken of it. Hover over any card to step through them.</li>
  <li><strong>The name, and a percentage</strong> for how sure the recognizer is: green from 90%, amber from 80%, dimmer amber from 60%, red below that. Under the name are the part number and, when known, a BrickLink moving-average price (with a leading <strong>≈</strong> when it is estimated from the base mold).</li>
  <li><strong>A badge.</strong> <strong>Tracking</strong> (seen on the channel, not photographed yet), <strong>Capturing</strong>, <strong>Classifying</strong>, <strong>Pending</strong>, <strong>Classified</strong>, <strong>Unidentified</strong> (no usable match), <strong>ID failed</strong> (the identification request itself failed) or <strong>Multi drop</strong>. A piece that went silent without being delivered shows <strong>Timed out</strong>.</li>
  <li><strong>Extra tags.</strong> <strong>Too big</strong> or <strong>Too big for layer</strong>, with its size in mm, means it went to the bottom bin. <strong>High value</strong> means its price cleared the profile's threshold. <strong>Not in inventory</strong> means the part and color are not in the active BrickLink inventory. The year the part was first released, its color and its category may also appear.</li>
  <li><strong>The bin</strong> it was delivered to, written as layer, section and bin (<strong>L</strong>, <strong>S</strong>, <strong>B</strong>). Pieces that were unidentified, rejected or too big read <strong>Discard</strong> with the bin, or <strong>Discard bin</strong>.</li>
  <li><strong>A wand icon</strong> (<em>Correct this Brickognize prediction</em>) on pieces that can be corrected. It opens <strong>Correct the prediction</strong> with the captured photos and the recognizer's answer. The icon turns amber after one correction is sent and green after both the part and the color have been.</li>
</ul>

Pieces that overlapped on the channel are rejected without being identified. They appear as one stacked <strong>Multi drop</strong> card with a <strong>Rejected</strong> badge and a count.

## Runtime panel

The panel at the bottom of the right-hand column says how sorting is going. Choose **10 min**, **1 hour** or **Today** (since midnight). It refreshes every 15 seconds and is calculated from the machine's piece records, so it survives a restart.

<ul class="bulleted-list">
  <li><strong>Classified a minute</strong> and <strong>Fed a minute</strong> (in ppm, pieces per minute): pieces classified, and pieces seen, per minute of sorting. Minutes in which no piece was seen are left out, so a pause does not drag the rate down.</li>
  <li><strong>Multi-drop rate</strong>: the share of pieces seen that were rejected because several arrived together.</li>
  <li><strong>Classified</strong>: the share of pieces seen that were classified.</li>
</ul>

The graph under the numbers draws <strong>Classified/min</strong> (solid), <strong>Fed/min</strong> (grey) and <strong>Multi-drop %</strong> (dashed red). Its footer gives the piece count and the top of each scale. Point at the graph, or touch it on a phone, and the four numbers change to that moment's. Moving away puts the span's numbers back.

Read it as follows. A **Classified** share that falls means more pieces are ending as **Unidentified** or **ID failed**: look at Recent pieces for which. A **Multi-drop rate** that climbs means pieces are arriving on the classification channel overlapped. For one run's detail, or older runs, use [Records]({{ '/sorter/records/' | relative_url }}).

## The Runtime page

The Runtime page shows how long each part of the machine spent in each state. It has no menu entry. Go to `/dashboard/runtime` on the machine's address (`http://sorter.local/dashboard/runtime`).

Three controls sit at the top:

<ul class="bulleted-list">
  <li><strong>Subsystem:</strong> <strong>All subsystems</strong>, <strong>Feeder</strong>, <strong>Classification</strong> or <strong>Distribution</strong>. The feeder has no lane of its own on these charts, so choosing it shows every lane.</li>
  <li><strong>Run:</strong> <strong>Live runtime</strong>, or a saved run, named by its start time, its piece count and the first characters of its run ID. Live data refreshes every 2 seconds while the browser tab is visible.</li>
  <li><strong>Refresh</strong> reloads the list of saved runs.</li>
</ul>

Time is counted only while the sorter is in its running state, so a paused machine does not add to any state. Below the controls:

<ul class="bulleted-list">
  <li><strong>Occupancy share by subsystem:</strong> one bar per lane, split by the percent of the run spent in each state. Hover a slice for its name and percentage. The legend underneath names every color. A state always has the same color in both charts.</li>
  <li><strong>Occupancy over the last 180 seconds:</strong> the same lanes as a timeline, from 180 s ago to now. Hover a bar for its length. It always ends at the moment you look, so read it on <strong>Live runtime</strong>.</li>
  <li><strong>Top occupancy blocks:</strong> the 12 states with the most time over the run, as lane and state with seconds.</li>
</ul>

On the classification lane the states are <code>waiting</code> (stopped while the channel looks at, photographs and classifies a piece and aims the chute), <code>ejecting</code> (turning the head piece off the channel), <code>staging</code> (turning forward until the drop zone is clear) and <code>waiting_for_piece</code> (waiting on the feeder for the next piece). A large <code>waiting_for_piece</code> share means the classification channel is idle for want of pieces, so look upstream at the feeder rather than at classification. The distribution lane's states are named for the step they wait on, for example `wait_chute_settle` and `wait_piece_exit`. Before anything has run, each chart says *No occupancy data yet*.

## Set progress

Set progress shows how many of each set's parts the sorter has found. It has no menu entry. Go to `/dashboard/sets`. It needs a set-based sorting profile ([Sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }}#set-based-profiles)); with any other active profile it says *The active sorting profile is not set-based*.

<ul class="bulleted-list">
  <li><strong>Overall progress</strong> gives parts found over parts needed across every set, with the percentage and a bar.</li>
  <li><strong>One card per set</strong> shows its name and set number, found over needed with a percentage, a bar that turns green at 100%, and either <strong>Complete</strong> or <em>N parts still missing</em>. That count is part-and-color lines, not pieces.</li>
  <li><strong>Click a card</strong> to open a table of the lines still missing: <strong>Part</strong> (number and name), <strong>Color</strong> (<em>Any color</em> when the set accepts any), <strong>Found</strong> and <strong>Needed</strong>. A complete set has nothing to open.</li>
  <li><strong>Checklist</strong> (top right) opens the Parts checklist below.</li>
</ul>

The page refreshes every 3 seconds. A piece counts when it is delivered under the set's category and the set still needs that part, in that color or in any color. Counts never go past what the set needs, and they are saved, so they survive a restart. If the sorting profile changes, the counts start again from zero.

## Parts checklist

The Parts checklist is a printable list of what is still missing from every set, for walking to your storage to find them. Press **Checklist** on Set progress, or go to `/dashboard/sets/checklist`. It loads once, so reload it to pick up newly sorted pieces. With no set-based profile it says *No set-based sorting profile is active*.

Controls at the top:

<ul class="bulleted-list">
  <li><strong>Back to set progress.</strong></li>
  <li><strong>Missing only</strong> (the default) or <strong>All parts</strong>: lists only the lines still missing, or every line. In Missing only, a set that is complete is hidden, and if every set is complete the page says <em>All clear</em>.</li>
  <li><strong>Print or save as PDF</strong> opens the browser's print dialog. Printing hides these controls, starts each set on a new page and uses light colors whatever the page's mode.</li>
</ul>

**Hunt summary** gives <strong>Found</strong>, <strong>Missing</strong> and <strong>Needed</strong> piece totals, and in words how many parts are missing across how many unique part and color combinations in how many sets. Each set then has its picture, number, year and name, a <strong>Complete</strong> badge or <em>N parts missing</em>, a progress bar, and a table of <strong>Part</strong>, <strong>Color</strong>, <strong>Found</strong>, <strong>Needed</strong> and <strong>Missing</strong> (<strong>OK</strong> when none). The box in the first column is ticked and locked for lines that are complete. Boxes for missing lines can be ticked in the browser as you find things, but ticks are not saved and do not change any count: tick them on paper, or accept that a reload clears them.

## The checklist for one set

A separate, single-set checklist lets you record parts you found by hand. Open it from the **Bins** page: click a bin that holds exactly one set, and in the details window press **Open the checklist**. It opens in a new tab, without the top bar, at `/bins/set-view/` followed by the set's category ID.

It shows the set's picture, set number, year and name, badges for <strong>found / needed</strong>, the percentage and the set's total part count, and a **QR code** (*Scan to continue*) of this page's address, so you can carry on from a phone. **Print or save as PDF** prints the cards without the buttons.

Tabs filter the parts: <strong>All</strong>, <strong>Unknown</strong> (the default: not enough found yet), <strong>Deferred</strong> and <strong>Complete</strong>, each with a count. Each part is a card with its picture, the number needed in a large badge, its name, part number and color, and a counter:

<ul class="bulleted-list">
  <li><strong>The minus and plus buttons</strong> lower or raise the found count by one. This replaces the machine's own count for that part.</li>
  <li><strong>Complete</strong> counts the part as fully found. <strong>Reset</strong> (on a complete part) goes back to the machine's own count.</li>
  <li><strong>Defer</strong> parks a part you are not looking for now, and moves it to the <strong>Deferred</strong> tab. <strong>Resume</strong> brings it back, on the machine's own count.</li>
</ul>

Each press is saved on the machine at once; if it cannot save, the page shows *The update failed* and puts the card back. These marks are kept by set number, so they survive a profile swap, a bin being emptied and a restart. They change this page's totals but not the numbers on Set progress.
