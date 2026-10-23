---
layout: default
title: Incident handling
type: reference
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-incident-handling
kicker: SorterOS — Operate
author: reveryx
lede: Choose what the machine does when a piece sticks or a bin runs out mid-sort, for each kind of incident. Ignore it, wait for you, or try to free the piece itself.
permalink: /sorter/incident-handling/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and the wording of the
  incident cards on the dashboard has not been checked against a real one.
---

An **incident** is the machine noticing something it cannot sort past on its own. Only one can be open at a time, and the machine holds while it is open. **Settings**, then **Incidents** (under **Helpers**) sets, for each kind of incident, whether the machine raises it, and who deals with it.

Which kinds exist and what triggers them is also listed in the [happy path and incident inventory]({{ '/sorter/happy-path-incident-inventory/' | relative_url }}). Past incidents are in the Incidents view of [Records]({{ '/sorter/records/' | relative_url }}#incidents).

<div class="img-placeholder">Screenshot of Settings > Incidents with the five rows, each with its Off, Manual and Automatic control.</div>

## The three settings

Each row has a name, a small label for where it happens (**Classification**, **Feeder** or **Distribution**), and a control with these choices:

<ul class="bulleted-list">
  <li><strong>Off:</strong> the machine does not raise the incident at all. What it does instead depends on the kind, below.</li>
  <li><strong>Manual:</strong> the machine raises the incident, holds, and shows a card on the dashboard saying what to do and with buttons to press. It waits for you.</li>
  <li><strong>Automatic:</strong> the machine raises the incident and tries to free the piece itself, then asks you if that fails. Only some kinds have this choice. Where it does, the steps it tries are listed under the row.</li>
</ul>

A choice is saved as soon as you press it. If saving fails, a red message appears and the control goes back to what it was. A row that differs from its default is tinted and has a reset button that puts the default back (its tooltip says what the default does). A row shows **Active** while that incident is open now.

**Automatic moves the channel motors by itself**, including shaking them back and forth. Keep hands and loose objects clear of the channels while the machine runs. Press **Stop** on the card to end an attempt.

## What happens, per kind

<ul class="bulleted-list">
  <li><strong>Stuck on the classification channel</strong> (<code>exit_stuck</code>, Classification, default Automatic). Raised when a piece has been on the classification channel for 30 seconds without the flow making any progress. <strong>Automatic:</strong> turn the channel forward until it clears, up to two full turns, checking as it goes. If the piece is gone, the machine carries on and nothing is asked of you. If not, the card appears. <strong>Manual:</strong> the card appears straight away. Its buttons are <strong>Turn to clear</strong>, which makes the same forward turn on request, and <strong>Done</strong>. The incident also closes by itself as soon as the machine sees the channel empty. <strong>Off:</strong> it is not raised.</li>
  <li><strong>A piece is going around the classification channel</strong> (<code>piece_circling</code>, Classification, default Automatic). Raised when the same part in the same color is classified again soon after one was dropped, when the part rolls or the first drop was never seen. That second record is not counted, since the first already counts it. <strong>Automatic:</strong> shake it off, then call the operator. The machine turns the channel to bring the piece into its exit, then shakes the channel in turn: Heavy stuck, Big and hard, back 10 degrees, forward 10 degrees, then Max shake. It only does this when turning cannot carry another piece through the exit, and turns the channel back afterwards. If the piece is freed, the incident closes by itself. If not, the card asks you to take the piece off and press <strong>Done</strong>. <strong>Manual:</strong> the card appears with <strong>Done</strong>, and nothing moves. <strong>Off:</strong> it is not raised.</li>
  <li><strong>A piece is stuck where pieces land</strong> (<code>piece_held</code>, Feeder, default Automatic). Raised when a piece where pieces land on C2 or C3 does not move with the channel; it most likely hangs off the channel above, and holds that channel back. <strong>Automatic:</strong> try to free it, then call the operator. After each of these steps the machine turns the channel back a little to see whether the piece rides again, and stops as soon as it does: nudge the channel above forward 3 degrees; forward 6; back 6; shake the channel above (Brief); shake this channel (Heavy stuck); turn it back 15 degrees; shake it (Big and hard). If the piece is freed, the incident closes by itself. If it is still stuck after all seven, the card asks you to take it off and press <strong>Done</strong>. <strong>Manual:</strong> the card appears with <strong>Done</strong>, and nothing moves. <strong>Off:</strong> it is not raised.</li>
  <li><strong>Bin doors not answering</strong> (<code>distribution_servo_bus_offline</code>, Distribution, default Off). Raised when the servos that open the bin doors stop answering. It has no Automatic choice. <strong>Manual:</strong> a card asks you to check the servo cable and power, then press <strong>Done</strong>. <strong>Off:</strong> no card, and the hardware alert is left to say it. The machine pauses and shows that alert either way.</li>
  <li><strong>No bin for this piece</strong> (<code>distribution_no_bin_available</code>, Distribution, default Off). Raised when no bin is assigned for a piece, or every bin that fits is full. It has no Automatic choice. <strong>Manual:</strong> the machine holds and the card asks you to assign a bin or free one up, or to press <strong>Send to bucket</strong>, which lets that one piece fall through to the bottom bucket and closes the incident. <strong>Off:</strong> such pieces are sent to the bucket and sorting continues without stopping. See <a href="{{ '/sorter/bins-and-profiles/' | relative_url }}">Bins and profiles</a> for how the machine looks for a bin first.</li>
</ul>

## The card on the dashboard

An open incident shows on the dashboard as a card with a title, one line on what to do, and buttons. The first button is the main one:

<ul class="bulleted-list">
  <li><strong>Done</strong> closes the incident. Press it after you have fixed the cause.</li>
  <li><strong>Turn to clear</strong> turns the classification channel forward to clear the piece, as Automatic does.</li>
  <li><strong>Send to bucket</strong> lets the piece with no bin fall through to the bucket, and closes the incident.</li>
  <li><strong>Stop</strong> appears while an automatic attempt is running, together with a bar showing which step it is on. After it is stopped, or after it has tried every step, the card asks you again.</li>
</ul>

## Incidents with no setting

Two kinds are not on this page, so they always raise a card:

<ul class="bulleted-list">
  <li><strong>Motor stalled:</strong> a motor reported a stall. Check it turns freely, then press <strong>Done</strong>. If the stalled motor is the chute, the card's button is <strong>Home chute</strong> instead, because a chute stall loses its position, and it homes the chute while clearing the stall.</li>
  <li><strong>Chute needs homing:</strong> follows a chute stall. Press <strong>Home chute</strong>.</li>
</ul>
