---
layout: default
title: Chute calibration
type: how-to
section: sorter
slug: sorter-chute-calibration
kicker: SorterOS — Operate
lede: Home the chute, teach it where the bins are, and test every bin it can reach. Do this once on a new machine, after the cameras are focused.
permalink: /sorter/chute-calibration/
warning: >-
  **SorterOS changes quickly.** This page describes what each step does, but a
  button's name, or where it is, may have changed since this page was written,
  so it keeps screenshots to a minimum.
last_verified: 2026-09-18
---

The chute is the stack in the middle of the bins. It turns as one piece to face a bin, and each layer's flap decides which layer a part leaves at. It does not know where your bins are until you tell it. This takes about fifteen minutes, all in **Settings**.

## Before you start

<ul class="bulleted-list">
  <li>The machine is powered on and the UI is open.</li>
  <li>The bins are in their bays on every layer.</li>
  <li>Nothing is resting in the chute.</li>
  <li>Each layer's <strong>Bins</strong> count is set on <strong>Settings → Storage layers</strong>: 12 on a half-size layer, 18 on a third-size one. The chute aims from these, so a wrong count sends parts to the wrong bin. If you change one, press <strong>Save the layers</strong>, then <strong>Restart the backend</strong> from the <strong>⋯</strong> menu at the top right.</li>
</ul>

**A section is the bins between two of the frame's upright columns, on one layer.** There are six sections per layer, with 2 bins each on a half-size layer and 3 on a third-size one.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/chute-calibration-sections-front-full-a1bb34517965.png" alt="The machine seen from the front at eye level: four upright columns, three layers of bins on shelves between them, the face square-on in the middle and the faces either side at an angle. On the middle layer the three bins between the two middle columns are shaded and bracketed as 1 section. The top two layers are third-size with 3 bins a section, the bottom layer half-size with 2."><figcaption>From the front: one section is the bins between two neighbouring columns, on one layer. <cite>Diagram. Render: Balloon.</cite></figcaption></figure>
</div>

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/chute-calibration-sections-full-97422dc47536.png" alt="Two top-down diagrams of one layer each, the chute in the middle and a column at each corner of the hexagonal frame. On the half-size layer one section, between two neighbouring columns, is shaded and holds 2 bins; on the third-size layer the same section holds 3 bins."><figcaption>From above: one section shaded on each layer size. <cite>Diagram. Render: Balloon.</cite></figcaption></figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Every step on this page turns the chute. Keep your hands out of the bins while it moves.</p>
</div>

## 1. Home the chute

Open **Settings**, then **Chute** (under **Hardware** in the left sidebar), then its **Chute aiming** tab. Steps 1 to 5 all happen on that tab.

Watch the chute from above, then press **Home the chute**.

**It should turn counter-clockwise** until it reaches its home switch. That point becomes 0&deg;. Then it turns back clockwise and stops at about the first bin, the one you aim at in step 2. From home, the chute always turns clockwise to reach the bins.

The switch is on the far side of the machine, above the PSU: the hammer on the back of the chute presses it. So at home, the chute itself points at the section to the left of the control board.

**If it turns clockwise instead,** press **Cancel**. Every bin would come out the same distance off, and no calibration fixes that. Reverse it: on **Settings → Chute**, tick **Invert the direction** under **Driver settings** and press **Apply the driver settings**. Then come back and home again.

Wait for **Homed.** next to the button.

**If Endstop reads Triggered before you press the button,** the chute takes wherever it stands as home, and every bin comes out off. See [the endstop always reads triggered]({{ '/sorter/troubleshooting/' | relative_url }}#chute-the-endstop-always-reads-triggered-or-never-does).

## 2. Aim at the first bin of the first section

**Use the first section clockwise from home**, the section to the left of the control board. A capture in any other section puts every bin in the wrong place. Measure it on a third-size layer, with 3 bins a section: the page offers 3 to 6 bins and has no 2, so it cannot measure a half-size layer. If every layer on your machine is half-size, this page cannot calibrate it yet.

Set **Bins in this section** to 3. The page says more is more accurate, but the number must match the one section you measure. Do not measure across two sections.

**The first bin is the one the chute reaches first as it turns clockwise from home.** First and last do not mean left and right. Capturing them the wrong way round is refused.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/chute-calibration-first-section-aim-full-87d0722c4b6e.png" alt="Top-down diagram of a third-size layer: the chute in the middle, its home direction at the column at the top, the home switch on the far side above the PSU, and the first section clockwise from home, left of the control board, shaded with its bins numbered 1, 2 and 3. A green arrow goes from the chute into the middle of bin 1, and a dashed blue arrow turns clockwise past bin 2 to bin 3."><figcaption>Step 2 aims into bin 1. Step 3 jogs clockwise, past bin 2, to bin 3. <cite>Diagram. Render: Balloon.</cite></figcaption></figure>
</div>

Jog the chute until it points at the middle of the first bin:

<ul class="bulleted-list">
  <li><strong>+2&deg;</strong> and <strong>&minus;2&deg;</strong> for big moves, <strong>+0.25&deg;</strong> and <strong>&minus;0.25&deg;</strong> for small ones.</li>
  <li>Plus turns the chute clockwise, minus turns it back.</li>
  <li>The arrow keys on a keyboard do the same.</li>
</ul>

Press **Capture the first bin**. The angle appears next to the button.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/chute-calibration-step2-first-bin-full-a33d44409ff8.jpg" alt="Step 2 of the calibration, saying pick any layer with more than 2 bins, with the jog pad showing 16.88 degrees, a bin count of 3 selected, and the Capture first bin button">
    <figcaption>Jog to the middle of the bin, set the bin count, then capture. <cite>UI screenshot. Render: Balloon.</cite></figcaption>
  </figure>
</div>

## 3. Aim at the last bin of the same section

Jog clockwise to the middle of the last bin of the same section, on the same layer: bin 3 in the diagram in step 2.

Press **Capture the last bin**.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/chute-calibration-step3-last-bin-w1600-9fe57ce8e553.jpg" alt="Step 3 of the calibration, with the jog pad showing 51.38 degrees and the Capture last bin button">
    <figcaption>The same section, its last bin. <cite>UI screenshot. Render: Balloon.</cite></figcaption>
  </figure>
</div>

## 4. Lock it in

The page shows what it worked out from your two captures. Type a label if you like, then press **Work it out and lock it in**.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/chute-calibration-step4-lock-in-w1600-8ffafb6cbf84.jpg" alt="Step 4 of the calibration, showing the derived section width, offset from home and pillar, a label field, and the Derive and lock in button">
    <figcaption>What the two captures produced. <cite>UI screenshot. Render: Balloon.</cite></figcaption>
  </figure>
</div>

The calibration is saved under **Saved calibrations** and marked **Active**. Old calibrations stay in that list. To return to one, press **Lock in** on its row.

## 5. Test the range of motion

Scroll down to **Reachable bins by layout**. Each circle is one layer layout, and each small ring on it is one bin. Use the circle with 3 bins per section.

Click a bin that is not crossed out, then press **Test aim at this bin**. Watch the machine: the chute should stop centred over that bin.

Test at least the first, a middle and the last bin of one section.

**Later, test any bin from the 3D page.** Once the machine is set up, open **3D** in the top bar, pause the machine, click a bin, and press **Point the chute here**. It works on every layer and needs the chute homed. See [the 3D page]({{ '/sorter/bins-and-profiles/' | relative_url }}#the-3d-page).

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/chute-calibration-reachable-bins-top-w1600-86304e186b8a.jpg" alt="The Reachable bins by layer size panel, showing ring diagrams for 1, 2 and 3 bins per section, with one bin crossed out in red in the 3-bin layout">
    <figcaption>Every bin the chute can point at, for each layer size. <cite>UI screenshot. Render: Balloon.</cite></figcaption>
  </figure>
</div>

Bins crossed out in red sit in the no-go wedge beside home. The chute cannot reach them and the machine will not send parts to them.

If a bin is not centred, run steps 1 to 4 again and take the two captures as carefully as you can. The bins at the two ends of a section are the ones that show a sloppy capture first.

## If the chute does not move

Open **Settings → Chute**. The top of the page shows where the chute is pointing, what the motor is doing, and whether it is homed.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/chute-calibration-stepper-status-full-c8e3c5e7628b.png" alt="The chute status panel showing Stopped, chute 51.4 degrees, motor 246.6 degrees, gear ratio 4.80, and a green Homed label">
    <figcaption>Settings → Chute, top of the panel. <cite>UI screenshot. Render: Balloon.</cite></figcaption>
  </figure>
</div>

<ul class="bulleted-list">
  <li><strong>A red stall message:</strong> the chute jammed. Clear the jam by hand, press <strong>Clear the stall</strong>, then home again with <strong>Home to the endstop</strong>. A stall loses the home position, so the aim is wrong until you re-home.</li>
  <li><strong>To check the motor turns at all,</strong> press <strong>CCW</strong> or <strong>CW</strong>. These move the chute without homing.</li>
  <li><strong>The endstop reads wrong:</strong> see <a href="{{ '/sorter/troubleshooting/' | relative_url }}#chute-the-endstop-always-reads-triggered-or-never-does">the endstop always reads triggered, or never does</a>.</li>
</ul>

## Run this again when

<ul class="bulleted-list">
  <li>You move or replace the home switch.</li>
  <li>The chute or its gear comes off and goes back on.</li>
  <li>The chute stalls.</li>
  <li>Parts start landing in the wrong bin. See <a href="{{ '/sorter/troubleshooting/#chute-drift--parts-land-in-the-wrong-bin-after-50-parts' | relative_url }}">Chute drift</a>.</li>
</ul>

## The finished result

One calibration saved and marked **Active**, and a test aim landing the chute centred over every bin you tried.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/chute-calibration-saved-calibrations-w1600-e00c1fdc0720.jpg" alt="The saved calibrations list with one entry labelled Bin locations set and marked ACTIVE">
    <figcaption>Saved calibrations. The active one is the one the machine aims with. <cite>UI screenshot. Render: Balloon.</cite></figcaption>
  </figure>
</div>

## Next

[Before your first sort run]({{ '/sorter/before-first-sort-run/' | relative_url }}).
