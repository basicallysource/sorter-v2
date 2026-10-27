---
layout: default
title: Tuning
type: reference
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-tuning
kicker: SorterOS — Operate
author: reveryx
lede: The Classification channel, Object tracker and Piece link tuning pages under Settings, with every field, its default, and what it changes. Use it when the classification channel misfeeds or sticks, when piece ids change between frames, or to try the experimental piece-link matcher.
permalink: /sorter/tuning/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and none of the advice has
  been checked against a real machine.
---

The **Tuning** group in the Settings side menu holds four pages. This page covers three of them: **Classification channel**, **Object tracker** and **Piece link (experimental)**. The fourth, **Feeder simple pulse**, has its own page: [Feeder simple pulse]({{ '/sorter/feeder-simple-pulse/' | relative_url }}).

The defaults suit a stock machine. Change a setting when you can name the symptom it addresses, and change one at a time.

## How the pages work

<ul class="bulleted-list">
  <li>Open <strong>Settings</strong>, then press the page's name under the <strong>Tuning</strong> heading.</li>
  <li>On <strong>Classification channel</strong> and <strong>Object tracker</strong>, each setting is a row with a name, a short explanation under it, and a number box or a switch. A row you have changed from its default is tinted and shows a <strong>Reset to</strong> button with the default value. It puts the default back in the form; you still press <strong>Save</strong> to keep it.</li>
  <li><strong>Save</strong> stores the values on the machine. <strong>Reset to saved</strong> reloads what the machine has and drops your edits. <strong>Piece link (experimental)</strong> has its own layout, described below.</li>
  <li>Saved changes take effect on a running machine with no restart. The page says when: the next piece for Classification channel, about a second for Object tracker.</li>
</ul>

## Classification channel

This page tunes the rev01 state machine that runs the classification channel (C4): how it turns the platter, photographs a piece at rest, sends the pictures to be classified, and shakes a piece loose if it sticks. The page title is **Classification channel tuning**. Changes apply to the next piece.

It moves the classification platter. A faster speed moves pieces faster but can fling light pieces, and the discharge and jitter settings decide how the platter is driven when a piece will not drop. The page does not check values against a range, so change one setting at a time and watch the next few pieces.

The page lists every setting in one **Parameters** panel. They are grouped by purpose below.

### Rotation

<ul class="bulleted-list">
  <li><strong>Rotate speed (µsteps/s):</strong> motor speed for normal C4 platter rotation. Default 7000.</li>
  <li><strong>Move-to-precise converge speed (µsteps/s):</strong> motor speed for the reverse move into the narrow precise staging band. Slower than normal rotation so the approach is gentle. Default 5000.</li>
  <li><strong>Move-to-precise: precise-centre tolerance (output deg):</strong> how close the piece must be to the centre of the precise band to count as parked. Default 4.</li>
  <li><strong>Home offset (output deg):</strong> the offset from the homing sensor position to the channel's actual zero. Default 22.</li>
  <li><strong>Rotate timeout (s):</strong> give up on a rotation if the stepper has not reported done within this long. It raises an incident instead of hanging. Default 30.</li>
</ul>

### Detecting a piece

<ul class="bulleted-list">
  <li><strong>Presence streak to start rotation:</strong> consecutive frames a piece must be detected before the channel starts processing it. It filters one-frame detector blips. Default 2.</li>
  <li><strong>Empty streak to abort rotation:</strong> consecutive empty frames during rotation before the machine decides the piece is gone and aborts the cycle. Default 3.</li>
  <li><strong>Idle: zero-read streak to confirm clear (open feed gate):</strong> consecutive zero-piece readings, while idle, before the channel counts as clear and C3 may feed the next piece. It guards against a one-frame detector dropout causing a double feed. Default 3.</li>
  <li><strong>Multi-feed: frames of &gt;=2 pieces to confirm:</strong> consecutive distinct frames showing two or more pieces on the channel before a multi-feed is declared, which sends the whole cycle to MISC. It stops a one-frame split detection from mis-flagging. Default 3.</li>
  <li><strong>Stuck-in-exit-zone warn timeout (s):</strong> if a piece sits in the exit zone this long without dropping, the operator is warned. Default 30.</li>
</ul>

### Photographing and classifying

<ul class="bulleted-list">
  <li><strong>Capture-at-rest window (ms):</strong> how long the piece is photographed at rest. The burst ends at this window or at the frame ceiling, whichever comes first. Default 350.</li>
  <li><strong>Burst frames to grab per piece (hard ceiling):</strong> the most frames the at-rest burst grabs for one piece. It is deliberately more than the classification ceiling, so the automatic quality selection has frames to choose from. Default 6.</li>
  <li><strong>Burst frames to use for classification (ceiling):</strong> the most burst frames ever sent to be classified. The quality selection picks which, and often sends fewer when part of the burst is motion-blurred or the piece is not fully in the crop. Default 4.</li>
  <li><strong>Also classify the last burst frame alone, in parallel (keep best):</strong> also send just the last burst frame as its own request and keep whichever result scores highest. A lone clean frame often recognises a piece the combined set confuses. Default on.</li>
  <li><strong>Crop padding (px):</strong> extra pixels added around the detected box when cropping the piece image for classification. Default 15.</li>
  <li><strong>Classify timeout (s):</strong> give up on the classification request after this long. The piece is sent to MISC. Default 30.</li>
</ul>

### Discharge

The discharge drives a classified piece off the platter. It moves the platter in repeated bounded moves until the channel reads clear.

<ul class="bulleted-list">
  <li><strong>Discharge speed (µsteps/s):</strong> motor speed for discharge moves, which drive the piece into the fall-off zone. Default 5000.</li>
  <li><strong>Discharge: fall-off centre tolerance (output deg):</strong> how close the piece must be driven to the centre of the fall-off zone before the closed-loop discharge stops commanding moves. Default 3.</li>
  <li><strong>Discharge: max single converge move (output deg):</strong> a clamp on any single discharge move, so a bad angle reading can never spin the platter wildly. Default 270.</li>
  <li><strong>Discharge: total budget before give-up (ms):</strong> one overall time budget for discharging a piece-set, not per move. If it runs out with the channel still occupied, the stuck-piece handling starts. Default 30000.</li>
  <li><strong>Discharge: continuous-clear window to confirm drop (ms):</strong> how long the exit must read clear without interruption before the piece counts as dropped. One non-clear frame restarts the window, so one-frame detector blinks cannot fake a drop. Default 500.</li>
  <li><strong>Discharge: settle delay before auto-crediting on give-up (ms):</strong> when the discharge runs out of attempts without a confirmed clear, usually because the piece did drop and a newcomer is holding the count up, wait this long for the channel to settle, then credit the piece and return to idle. Default 1500.</li>
</ul>

### Unsticking a piece

If a piece sits in the fall-off region for too long, the platter shakes it loose with a short back-and-forth jitter.

<ul class="bulleted-list">
  <li><strong>Discharge: dwell in fall-off region before jitter (ms):</strong> a piece that sits continuously in the fall-off region this long is parked, so the machine shakes it loose. A piece dropping normally is there only for a frame or two. Default 250.</li>
  <li><strong>Verify-discharge: settle wait before re-check (ms):</strong> after a discharge move settles, wait this long before the first exit-zone re-check. Default 1000.</li>
  <li><strong>Verify-discharge: max jitter attempts:</strong> if the piece still reads stuck after the settle wait, run up to this many jitter attempts before giving up. Default 3.</li>
  <li><strong>Jitter: pause between attempts (ms):</strong> the pause between attempts, giving the piece time to fall before shaking again. Default 350.</li>
  <li><strong>Jitter amplitude (motor deg):</strong> the size of each back-and-forth oscillation. Default 8.</li>
  <li><strong>Jitter cycles per burst:</strong> back-and-forth oscillations per attempt. Default 6.</li>
  <li><strong>Jitter speed (µsteps/s):</strong> motor speed during the oscillations. Default 4000.</li>
  <li><strong>Jitter accel (µsteps/s²):</strong> motor acceleration during the oscillations. It is high, so the shake is sharp enough to unstick a piece. Default 80000.</li>
</ul>

### Legacy settings

The labels and explanations of these three rows say they belong to a fallback path used only without perception, and that the active perception path does not use them. Leave them alone.

<ul class="bulleted-list">
  <li><strong>Capture sweep (output deg, legacy):</strong> default 180.</li>
  <li><strong>Kick-off move (output deg):</strong> default 180.</li>
  <li><strong>Post-discharge pause (ms):</strong> default 300.</li>
</ul>

## Object tracker

The tracker gives each piece on the classification channel one id from frame to frame, so a piece keeps its id through brief detector dropouts. Open **Object tracker** under **Tuning**. Changes apply within about a second.

<div class="img-placeholder">Screenshot of the Object tracker page with the Tracker panel, the Presets panel and the first parameter sections.</div>

### Choose the tracker

The **Tracker** panel offers three trackers. The one in use is marked **(running)**. A machine that has never had one chosen uses **Ordered + Color (channel)**.

<ul class="bulleted-list">
  <li><strong>ByteTrack:</strong> follows each piece by motion and by how much its box overlaps the last one, with no appearance. Fast and simple, but loses ids when a piece moves far, curves, or briefly leaves the frame.</li>
  <li><strong>Angular + Color:</strong> follows each piece by its angle around the channel centre, so circular motion and off-screen excursions are predicted correctly, with a colour gate. It is best at keeping ids through the curve and brief disappearances.</li>
  <li><strong>Ordered + Color (channel):</strong> on a one-way platter pieces never pass each other, so it matches each frame's detections to the pieces it is following in travel order, requiring only that the order is kept and pieces move forward. Colour and size only break ties. It copes with the platter's large jumps between frames, and is described as best for 0 to 4 pieces.</li>
</ul>

**Pressing Save switches the running tracker to the one selected**, and stores the parameters shown for it. Each tracker keeps its own parameters, so switching back later brings its tuning with it.

### Presets

The **Presets** panel appears for **ByteTrack** and **Angular + Color**, and not for **Ordered + Color (channel)**. A preset fills in the parameters below. Review them, then press **Save**.

<ul class="bulleted-list">
  <li><strong>ByteTrack, Balanced:</strong> activation threshold 0.1, min consecutive frames 1, matching threshold 0.9, lost-track buffer 30, frame rate 30. About a one second hold.</li>
  <li><strong>ByteTrack, Sensitive:</strong> the same but matching threshold 0.95 and lost-track buffer 60. About a two second hold. It still loses ids when a piece curves or leaves the frame. Use the Angular tracker for that.</li>
  <li><strong>Angular + Color, Balanced:</strong> a default gate and about a 2.5 s coast. Good for 0 to 2 pieces.</li>
  <li><strong>Angular + Color, Sticky (recommended):</strong> a wide angular gate (24°) and a 4 s coast, so a fast piece that rounds the curve or leaves the frame keeps its id. The colour gate is on to avoid mixing up pieces.</li>
  <li><strong>Angular + Color, Tight:</strong> a narrow gate (8°), a strict colour match and a 1.5 s coast, for when three or four pieces crowd close together and you want to avoid id swaps.</li>
</ul>

### ByteTrack parameters

<ul class="bulleted-list">
  <li><strong>Activation threshold</strong> (Track creation): the minimum detection confidence to start a new track. Keep it below the detector's own confidence threshold or pieces will not get tracked. Default 0.1.</li>
  <li><strong>Min consecutive frames</strong> (Track creation): frames in a row a detection must be tracked before it gets a stable id. 1 labels it immediately. Raise it to suppress one-frame false detections. Default 1.</li>
  <li><strong>Matching threshold</strong> (Matching): a pair of boxes matches when 1 minus their overlap is below this, so 0.9 accepts an overlap of 0.1 or more. The boxes must actually overlap: a piece that leaves the frame and curves back gets a new id whatever this is set to. Default 0.9.</li>
  <li><strong>Lost-track buffer (frames)</strong> (Occlusion / lifetime): frames a track keeps coasting after detections stop before it loses its id. At 30 frames a second, 30 is about one second. Default 30.</li>
  <li><strong>Frame rate</strong> (Occlusion / lifetime): the frame rate the tracker assumes. It only scales the lost-track buffer into a real frame count. Set it near the perception loop's actual rate. Default 30.</li>
</ul>

### Angular + Color parameters

<ul class="bulleted-list">
  <li><strong>Min hits</strong> (Track creation): frames a new detection must be seen before it gets a stable id. Default 1.</li>
  <li><strong>Activation score</strong> (Track creation): the minimum detection confidence to start a new track. Default 0.1.</li>
  <li><strong>Match gate (°)</strong> (Matching): the largest angle around the channel centre between a track's predicted position and a new detection for them to be the same piece. Raise it to tolerate faster pieces or longer gaps. Lower it if nearby pieces get confused. Default 14.</li>
  <li><strong>Radius gate (fraction)</strong> (Matching): the largest difference in distance from the centre, as a fraction of the radius. It rejects matches that jump across the channel width. 0.3 is within 30%. Default 0.3.</li>
  <li><strong>Use color gate</strong> (Color): require a detection's average colour to resemble the track's before matching. Default on.</li>
  <li><strong>Color tolerance (0–1)</strong> (Color): how different two average colours can be and still match, 0 being identical and 1 anything. Only used when the colour gate is on. Lower is stricter. Default 0.22.</li>
  <li><strong>Velocity smoothing (0–1)</strong> (Motion): smoothing for the estimated angular speed used to predict where a piece will be after a gap. Higher reacts faster to speed changes, lower is steadier. Default 0.5.</li>
  <li><strong>Coast time (s)</strong> (Occlusion / lifetime): how long to keep predicting a piece's position after it stops being detected before giving up its id. Default 2.5.</li>
</ul>

### Ordered + Color parameters

<ul class="bulleted-list">
  <li><strong>Backward tolerance (°)</strong> (Matching): a detection that moved backward by more than this many degrees cannot be the same piece. It absorbs detection jitter. Default 8.</li>
  <li><strong>Backward tolerance while landing (°)</strong> (Matching): a piece that has just landed bounces back as well as forward. In the drop zone a detection may be this much further back and still be the same piece, so it keeps the id it was photographed and classified under. Default 60.</li>
  <li><strong>Same piece when one box holds the other</strong> (Matching): the detector can box one piece two ways from frame to frame. A box that would start a new piece is instead the piece whose last box it sits inside or around, when that piece went unseen in the same frame. This share of the smaller box must overlap the larger. Two boxes seen in the same frame are always two pieces. 0 turns it off. Default 0.8.</li>
  <li><strong>Fastest a piece moves forward (°/s)</strong> (Matching): a detection further ahead than this speed over the time since the piece was last seen, plus 20°, is another box and not this piece. Pieces move at most about 300°/s. Default 400.</li>
  <li><strong>Max match cost</strong> (Matching): the upper bound on the colour, size and radius cost for a match. Above it, the pair is treated as one piece exiting and a different one arriving. Lower is stricter about appearance changes. Default 0.6.</li>
  <li><strong>Color weight</strong>, <strong>Size weight</strong> and <strong>Radius weight</strong> (Appearance): how strongly colour, relative box size and distance from the channel centre separate two candidates the order cannot tell apart. Defaults 1, 0.4 and 0.4.</li>
  <li><strong>Color sample (center fraction)</strong> (Appearance): the centred fraction of the box used to sample colour. 0.5 is the middle half. Smaller focuses on the piece, and too small gets noisy. Default 0.5.</li>
  <li><strong>Coast time (s)</strong> (Lifetime): how long to keep a track alive with no matching detection before dropping its id. A piece that really left the exit ages out here, and its disappearance is what marks it ejected. Default 1.5.</li>
  <li><strong>Unmatched-track cost</strong> (Lifetime): the cost of leaving a live track with no detection this frame. Raise it to hold ids harder through dropouts, lower it to give them up sooner. Default 0.7.</li>
  <li><strong>New-track cost</strong> (Lifetime): the cost of starting a new id for a detection that matched no track. A box in the drop zone is discounted. Raise it to suppress spurious new ids elsewhere. Default 0.7.</li>
  <li><strong>Activation score</strong> (Track creation): the minimum detection confidence to start a new track. Default 0.1.</li>
  <li><strong>Confirm frames (ghost filter)</strong> (Track creation): frames a new detection must persist before it gets an id and counts as a real piece. Raise it if false boxes still slip through. Lower it toward 1 if real pieces are slow to be picked up. 3 is about a quarter of a second. Default 3.</li>
  <li><strong>Tentative coast (s)</strong> (Track creation): how long an unconfirmed track is kept after it stops being detected before it is discarded. Short, so a one-frame ghost vanishes fast. Default 0.3.</li>
  <li><strong>Color smoothing (0–1)</strong> (Motion): smoothing for the running colour estimate. Higher reacts faster, lower is steadier. Default 0.5.</li>
</ul>

## Piece link (experimental)

The **Piece link (experimental)** page carries an **Experimental** badge, and the page itself is titled **Piece link matching**. Given a piece just classified on C4, it scores which of the pictures taken earlier on C2 and C3 show the same piece. It uses the pictures and the timing and position data, and it replaces the hand-tuned time and angle scoring behind the piece page's "Possibly the same piece" gallery. It is **off by default**, and costs one small model pass on the processor for each lookup.

The model only re-ranks pictures the time and angle lookup already found. It cannot find pictures that lookup missed, so turning it off always falls back to the old scoring.

<div class="img-placeholder">Screenshot of the Piece link matching page with a model installed, showing the Matching and Model panels.</div>

### Install a model first

Until a piece-link model is installed, the page says **No piece-link model is installed**, and the switch and the **Minimum confidence** box are greyed out. Open **Local models** (the link in that message goes there), and download a model with the purpose set to **Piece link (experimental)**. Then come back. A piece-link model is listed greyed out on that page, because it is used from this page and not activated there.

### Matching

<ul class="bulleted-list">
  <li><strong>Use the model to rank the possible crops:</strong> the on and off switch. When on, the piece page shows a "Model" badge and each picture's match probability in place of the old score. Default off.</li>
  <li><strong>Minimum confidence:</strong> pictures scoring at or above this, from 0 to 1, count as the same piece. Below it they still show on the piece page, unchecked, and are never added to the pictures used for the classification. This overrides the cutoff built into the model (0.5 for link-v3). Default 0.95. On save the page limits the value to between 0 and 1.</li>
</ul>

Turning this on changes which pictures are sent for classification, not only what the piece page shows.

### Model

This panel appears once a model is installed. Leave it on **Automatic**, which uses whichever model is installed, unless there is more than one and you want to pin a version. Each installed model is listed by name with its download date.

### Feature contract

Below the buttons, **Feature contract** lists the time and position features this version of the software feeds the model, in order. A model trained on anything different refuses to load rather than score nonsense. If the log shows a mismatch error, the model and the software are out of step.

### Saving

**Save** applies at once, and the next lookup uses the new model or setting without a restart. The **Save** button is disabled when there is no model installed and the switch is off.
