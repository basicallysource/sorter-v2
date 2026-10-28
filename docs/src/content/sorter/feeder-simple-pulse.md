---
layout: default
title: Feeder simple pulse
type: reference
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-feeder-simple-pulse
kicker: SorterOS — Operate
author: jensr80
lede: Every setting on the Feeder simple pulse tuning page, what it does, and its default. Use it when pieces reach the classification channel two at a time, when a channel moves too fast or too slowly, or when you want the machine to find faster settings for itself.
permalink: /sorter/feeder-simple-pulse/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and none of the advice has
  been checked against a real machine.
---

The feeder moves pieces along C1, C2 and C3 in short pulses: it turns a channel a set distance, pauses so the camera can look again, and decides what to do next from what it sees. The **Feeder simple pulse** page holds the numbers behind that: how far each pulse goes, how long each pause lasts, how the exit of each channel hands a piece to the next, and a search that tries values for you.

This page is for the simple pulsing feeder. The setup wizard's **Out of view** fields are also here, and are explained in [First setup]({{ '/sorter/first-setup/' | relative_url }}).

Saving a change applies it to a running machine within about a second, with no restart. Pulse distances and speeds decide how the channels move on the machine, so change a few settings at a time and watch the next few pieces.

## Open it

<ol class="numbered-steps">
  <li>Open <strong>Settings</strong>.</li>
  <li>Under the <strong>Tuning</strong> heading in the side menu, press <strong>Feeder simple pulse</strong>.</li>
</ol>

The page has four panels, from the top: **Exit pulse speed**, **Hold after a fall**, **Parameters** and **Auto-tune**.

<div class="img-placeholder">Screenshot of the Feeder simple pulse page with the Exit pulse speed panel and the first sections of Parameters.</div>

## Saving

Edits stay in the form until you press **Save**. **Save** and **Reset to saved** sit at the top of the page and again under **Parameters**. **Reset to saved** reloads what the machine has and drops your edits.

<ul class="bulleted-list">
  <li>A row you have changed from its default is tinted and shows a <strong>Reset to</strong> button with the default value. It puts the default back in the form. You still press <strong>Save</strong> to keep it.</li>
  <li>The text under each setting's name is a short explanation of it.</li>
  <li>While the form differs from what the machine has, <strong>Unsaved changes</strong> appears beside the buttons. If you try to leave the page, a box asks what to do, with <strong>Stay on the page</strong>, <strong>Discard the changes</strong> and <strong>Save and leave</strong>.</li>
  <li>The page does not check a value against a minimum or maximum. A number you type is saved as typed, so the defaults below are the reference point.</li>
</ul>

## Exit pulse speed

The exit pulse is how hard C2 and C3 push a piece off the edge into the next channel. Bigger nudges hand pieces over faster but are more likely to push two through at once.

Each preset sets only **Exit pulse distance (output deg)** and **Exit pause between pulses (ms)** in the form. Review them, then press **Save**.

<ul class="bulleted-list">
  <li><strong>Conservative (2°):</strong> 2° per pulse, 100 ms pause. The gentlest metering, the least chance of two pieces entering the classification channel together, and the slowest hand-off. This is the default.</li>
  <li><strong>Balanced (4°):</strong> 4° per pulse, 100 ms pause. A faster hand-off with a modest double-feed risk.</li>
  <li><strong>Aggressive (8°):</strong> 8° per pulse, 100 ms pause. The fastest and the most likely to push two pieces through together.</li>
</ul>

## Hold after a fall

This panel only reports. After a piece is pushed off an exit and falls, that exit pushes nothing for a while, so the next channel sees the piece land before another can follow. Here you see how long that wait is for each exit: **C2 to C3** and **C3 to the classification channel**. The panel refreshes every few seconds.

<ul class="bulleted-list">
  <li><strong>A time in seconds, with "9 in 10 of the last N pieces landed within..."</strong> The machine has watched at least 20 pieces fall and land on that exit, and the hold follows them. The hold is the time 9 in 10 of those pieces took to land plus 0.3 s, kept between 0.5 s and 2.5 s. Landings that took longer than 3 s are left out.</li>
  <li><strong>"The hold setting, until 20 pieces have been seen to fall and land (N so far)."</strong> Not enough pieces yet, so the <strong>Hold after a piece falls (ms)</strong> value from Hand-off below applies.</li>
  <li><strong>"The hold setting; it does not follow how long pieces take to land."</strong> <strong>Hold follows how long pieces take to land</strong> is off.</li>
  <li><strong>"Measured from when this channel next runs."</strong> The machine has not run that exit since it started.</li>
</ul>

## Parameters

The settings are grouped under small headings. Distances are in output degrees, as each label says. Defaults are what a machine uses until you change it.

### Motion

<ul class="bulleted-list">
  <li><strong>Forward direction sign (+1/-1):</strong> which way the motor turns to carry pieces toward the exit. Default 1. Leave it at 1. Use -1 only if a channel's stepper is wired backwards and pieces move the wrong way.</li>
  <li><strong>Min move (output deg):</strong> moves smaller than this are treated as noise and skipped. Default 0.1.</li>
</ul>

### Speeds

The motor speed used for every pulse on that channel, in microsteps per second. Higher is snappier. The three channels are independent, and changing one does not affect the others. Default 2000 for each.

<ul class="bulleted-list">
  <li><strong>C1 move speed (µsteps/s):</strong> C1 shifts the whole bulk pile, so it usually wants a different speed from the metering channels.</li>
  <li><strong>C2 move speed (µsteps/s)</strong></li>
  <li><strong>C3 move speed (µsteps/s):</strong> C3 meters single pieces into the classification channel. A slower speed trades throughput for fewer double drops.</li>
</ul>

### Max move

A hard cap on any single pulse on that channel, so a bad value cannot spin it wildly. Default 120 for each.

<ul class="bulleted-list">
  <li><strong>C1 max move clamp (output deg):</strong> raise this if C1 drives something that wants long moves, such as a conveyor belt rather than a C-channel rotor, and the bulk pulse distance is being cut short by the clamp.</li>
  <li><strong>C2 max move clamp (output deg)</strong></li>
  <li><strong>C3 max move clamp (output deg)</strong></li>
</ul>

### Drop-zone pulse

How a channel carries a piece that is still back in the drop zone, not yet at the exit edge.

<ul class="bulleted-list">
  <li><strong>Drop-zone pulse distance (output deg):</strong> how far a piece is nudged per pulse. Default 30.</li>
  <li><strong>Drop-zone pause between pulses (ms):</strong> the pause after each pulse so the camera can read the piece again before the next nudge. Default 100.</li>
</ul>

### Exit pulse

How a channel moves a piece off its exit edge into the next channel.

<ul class="bulleted-list">
  <li><strong>Exit pulse distance (output deg):</strong> how far a piece is nudged per pulse once it is at the exit edge. Smaller is gentler and less likely to push two pieces through at once. Default 2. The <strong>Exit pulse speed</strong> presets set this.</li>
  <li><strong>Longest exit move (output deg):</strong> when nothing is close behind the piece at the exit, one move pushes it this far so it drops in one go. The move always stops short of letting the next piece reach the exit. Set it equal to the exit pulse distance to always pulse. Default 10.</li>
  <li><strong>Room kept for the next piece (output deg):</strong> a longer exit move stops this far before the next piece's front edge would reach the exit. Default 4.</li>
  <li><strong>C2: keep the next piece back (deg):</strong> while the piece at C2's exit is in the opening, C2 never turns so far that the next piece's centre comes within this many degrees of the opening. It shakes the piece at the exit loose instead (back a little, then forward as far) so the two do not fall together. 0 is off, and the next piece is pushed in after the first. Default 2.</li>
  <li><strong>C3: keep the next piece back (deg):</strong> the same for C3's exit onto the classification channel. Default 0 (off).</li>
  <li><strong>Exit pause between pulses (ms):</strong> the pause after each exit pulse so the next channel registers the piece before another nudge. Default 100.</li>
</ul>

### Out of view

The part of C2's or C3's ring that its camera cannot see. While a piece is out of view between the two angles, the channel keeps advancing, never so far that it could pass the staging zone unseen. Equal start and end angles mean the camera sees the whole ring. All four default to 0. [Zones]({{ '/sorter/zones/' | relative_url }}#cameras-that-do-not-see-the-whole-ring) explains how to find the angles; they are on the same scale as the zone diagrams there.

<ul class="bulleted-list">
  <li><strong>C2 unseen arc start (deg)</strong> and <strong>C2 unseen arc end (deg)</strong></li>
  <li><strong>C3 unseen arc start (deg)</strong> and <strong>C3 unseen arc end (deg)</strong></li>
</ul>

### C1 (bulk)

C1 has no camera. It pulses forward a fixed amount whenever C2's drop zone is clear.

<ul class="bulleted-list">
  <li><strong>C1 bulk pulse distance (output deg):</strong> default 1.</li>
  <li><strong>C1 pause between pulses (ms):</strong> default 300.</li>
</ul>

### Channels

<ul class="bulleted-list">
  <li><strong>Gate C3 on classification ready:</strong> C3 does not push a piece into the classification channel (C4) until C4 reports it is ready for one, so two pieces do not land in the same spot. Default on.</li>
  <li><strong>Enable C1 (bulk)</strong>, <strong>Enable C2</strong> and <strong>Enable C3</strong>: off means that channel never moves. Default on for all three. If a channel does not move at all, check its switch here.</li>
</ul>

### Hand-off

How a channel passes a piece to the next one, and how crowded it lets a channel get.

<ul class="bulleted-list">
  <li><strong>Most pieces on C3:</strong> C2 hands C3 no new piece while C3 holds this many. Pieces crowded on C3 sit touching, and C3's exit then drops two at once onto the classification channel. 0 is no limit. Default 0.</li>
  <li><strong>Most pieces on C2:</strong> C1 adds nothing to C2 while C2 holds this many, so a heavy pour from the hopper does not flood C2 and pack C3 behind it. 0 is no limit. Default 0.</li>
  <li><strong>C3 stand-off while C4 is busy (output deg):</strong> while the classification channel is turning or has a piece in its drop zone, C3 moves its lead piece only to this far short of the exit, so nothing waits at the lip to fall onto C4 mid-turn. 0 advances right up to the exit edge. Default 0.</li>
  <li><strong>Fallen after gone for (ms):</strong> the piece being pushed off counts as fallen once the camera has not seen it for this long. A longer time ignores detector blinks, a shorter one reacts sooner. Default 150.</li>
  <li><strong>Hold after a piece falls (ms):</strong> after the piece being pushed off falls, the exit pushes nothing for this long. Default 1500.</li>
  <li><strong>Hold follows how long pieces take to land:</strong> once 20 pieces have been seen to fall and land, each exit holds for the time 9 in 10 of them took to land on the next channel, plus 0.3 s (between 0.5 and 2.5 s). Until then, and when this is off, the hold above applies. Default on. The <strong>Hold after a fall</strong> panel shows the result.</li>
</ul>

### Detection persistence

<ul class="bulleted-list">
  <li><strong>C2/C3 drop-zone occupancy hold (ms):</strong> after a piece is seen in C2's or C3's drop zone, the zone stays marked as occupied for this long even if the detector misses the piece for a frame or two. It stops the channel upstream from dropping another piece on top during a brief detection flicker. 0 trusts every frame as it is. Default 500.</li>
</ul>

### Greedy mode

In the normal flow a channel pulses a piece only while it is in the drop zone, then waits until the piece reaches the exit zone. In greedy mode it starts pushing a piece toward the exit as soon as it is seen anywhere on the channel, which clears the channel for the next piece sooner.

<ul class="bulleted-list">
  <li><strong>C2 greedy (advance piece anywhere on channel)</strong> and <strong>C3 greedy (advance piece anywhere on channel)</strong>: default on for both.</li>
  <li><strong>Greedy advance pulse distance (output deg):</strong> the pulse distance used for a piece that has left the drop zone but not yet reached the exit edge. Default 30.</li>
  <li><strong>Greedy advance pause between pulses (ms):</strong> default 250.</li>
</ul>

## Which setting for which symptom

Only the symptoms the settings' own explanations cover.

<ul class="bulleted-list">
  <li><strong>Two pieces land on the classification channel together.</strong> Choose a gentler <strong>Exit pulse speed</strong> preset, or lower <strong>Exit pulse distance (output deg)</strong>. A slower <strong>C3 move speed (µsteps/s)</strong> trades throughput for fewer double drops. If pieces sit touching on C3, set <strong>Most pieces on C3</strong>. If a piece waits at C3's lip while C4 turns, set <strong>C3 stand-off while C4 is busy (output deg)</strong>. Keep <strong>Gate C3 on classification ready</strong> on.</li>
  <li><strong>Two pieces fall off C2's or C3's exit together.</strong> Set <strong>C2: keep the next piece back (deg)</strong> or <strong>C3: keep the next piece back (deg)</strong> above 0.</li>
  <li><strong>C2 floods and C3 packs up behind it.</strong> Set <strong>Most pieces on C2</strong>.</li>
  <li><strong>Another piece drops on top of one that is still in the drop zone.</strong> Raise <strong>C2/C3 drop-zone occupancy hold (ms)</strong>.</li>
  <li><strong>A piece vanishes on one part of the ring and reappears further round.</strong> Set the <strong>Out of view</strong> arc for that channel.</li>
  <li><strong>A channel does not move.</strong> Check its <strong>Enable</strong> switch. If a channel moves the wrong way, the direction fix is <strong>Forward direction sign (+1/-1)</strong>.</li>
  <li><strong>C1 drives a belt and its pulses are cut short.</strong> Raise <strong>C1 max move clamp (output deg)</strong>.</li>
</ul>

## Auto-tune

Auto-tune searches for the fastest pulse settings on your machine. Each trial applies a set of values to the feeder and measures how many pieces a minute reach the classification channel. A trial counts only if its double-drop rate stays under the cap you set. A double drop is two or more pieces in C4's drop zone at once. Of the trials that count, the one with the highest throughput wins.

**It changes the live settings while the machine sorts.** Each trial writes its values to the machine's saved feeder settings, and they stay until the run ends. Values are held inside the ranges listed under **Parameters to tune**. The trial clock runs only while the machine is sorting, so auto-tune runs alongside normal sorting. If the machine is not sorting, the page says so and the clock waits.

When a run ends, or the machine's software restarts mid-run, the settings from before the run are put back, unless you stop with **Stop and apply the best**.

### Before you start

<ul class="bulleted-list">
  <li><strong>Trial length:</strong> how long each trial measures, in seconds of sorting. Starts at 120. The machine does not accept less than 20.</li>
  <li><strong>Most double drops:</strong> the cap, as a percentage of pieces. Starts at 5. The machine accepts 0 to 50.</li>
  <li><strong>Jam cost:</strong> a jam or stall during a trial docks its score as if it had delivered this many fewer pieces. Starts at 10.</li>
  <li><strong>Parameters to tune:</strong> a checkbox for each setting the search may vary, with its range. All are on to start. At least one must stay on or <strong>Start tuning session</strong> shows "Select at least one parameter to tune".</li>
</ul>

The ranges are:

<ul class="bulleted-list">
  <li><strong>C1, C2 and C3 move speed (µsteps/s):</strong> 800 to 5000 each.</li>
  <li><strong>Drop-zone pulse distance (deg):</strong> 5 to 90. <strong>Drop-zone pause (ms):</strong> 0 to 600.</li>
  <li><strong>Exit pulse distance (deg):</strong> 0.5 to 12. <strong>Exit pause (ms):</strong> 30 to 500.</li>
  <li><strong>Greedy pulse distance (deg):</strong> 5 to 90. <strong>Greedy pause (ms):</strong> 0 to 600.</li>
  <li><strong>C1 pulse distance (deg):</strong> 0.25 to 8. <strong>C1 pause (ms):</strong> 50 to 1000.</li>
</ul>

Below the fields the page works out the cost: each trial takes about 4 s to settle plus the trial length, and the page shows the trials an hour of sorting that gives. It suggests about 30 trials for each parameter you chose (at least 30) before the search has covered the space. A run continues until you stop it, and the results accumulate across runs, so stopping and resuming later loses nothing.

### Two ways to run

<ul class="bulleted-list">
  <li><strong>Start tuning session:</strong> hunts for the best settings. The first trial measures your current settings as the baseline. After that, three trials in four stay near the best so far and one in four is a random jump. Both kinds are listed in the table as <strong>refine</strong> and <strong>explore</strong>.</li>
  <li><strong>Enable background exploration:</strong> tries purely random values during normal sorting. It finds a winner more slowly, but it builds an even picture of the whole range, and it keeps collecting across restarts until you turn it off.</li>
</ul>

Only one runs at a time.

### While it runs

The page shows the current trial (its number, its kind, seconds measured out of the trial length, pieces delivered and double drops) and the values being tried. Two alerts can appear:

<ul class="bulleted-list">
  <li><strong>Background exploration is on:</strong> a new random candidate is tried every trial while you sort.</li>
  <li><strong>The machine isn't sorting, so the trial clock is paused.</strong> Start sorting to resume.</li>
</ul>

To end a tuning session:

<ul class="bulleted-list">
  <li><strong>Stop and restore the baseline:</strong> puts back the settings from before the run.</li>
  <li><strong>Stop and apply the best:</strong> keeps the best trial's values. It is greyed out until a trial has counted.</li>
</ul>

For background exploration, the button is **Turn off background exploration**, and it restores the baseline. A couple of seconds after any stop the form reloads to show what is live.

### Reading the results

<ul class="bulleted-list">
  <li><strong>Best so far:</strong> the winning trial's pieces a minute, double-drop percentage, score and values. <strong>Load into form</strong> copies those values into the form above. It does not save them; press <strong>Save</strong> to keep them.</li>
  <li><strong>Throughput against double-drop rate, every trial collected:</strong> a chart with one square per trial, pieces a minute upward and double-drop percentage across. Filled squares are <strong>Within the cap</strong>, outlined squares are <strong>Over the cap</strong>, and the dashed line is your cap. Hover a square for its numbers.</li>
  <li><strong>Trials in this run:</strong> a table with <strong>Trial</strong>, <strong>Kind</strong> (baseline, explore or refine), <strong>Measured</strong>, <strong>Pieces</strong>, <strong>A minute</strong>, <strong>Incidents</strong>, <strong>Double drops</strong> and <strong>Score</strong>. A trial over the cap shows <strong>Over the cap</strong> in place of a score. <strong>Load</strong> on a row copies that trial's values into the form, unsaved.</li>
</ul>

The score is pieces a minute, where each incident during the trial counts as if **Jam cost** fewer pieces had been delivered.
