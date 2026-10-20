---
layout: default
title: Bins and profiles
type: explanation
section: sorter
slug: sorter-bins-and-profiles
kicker: "SorterOS: Operate"
lede: How the machine decides which bin takes which category, how to keep a profile's bins when you switch to another profile, and what happens when a bin fills up.
permalink: /sorter/bins-and-profiles/
author: brickcyclealice
warning: >-
  **AI-generated first draft.** Written from the SorterOS source, not from clicking
  through the flow on a machine. Correct it as you use it.
---

A sorting profile lists categories. It never names a bin. Which bin takes which category is kept on the machine, and you see and change it on the **Bins** page. Each bin holds a list of the categories it takes, and everything on this page is about that list.

## What the Bins page shows

One panel per storage layer, **Layer 1**, **Layer 2** and so on. Each layer is split into sections, and each section into bins. Every bin card shows its number, the categories it takes (or **Unassigned**), and the pieces in it.

<ul class="bulleted-list">
  <li>Every layer and every section has its own on/off switch. A layer or section that is off gets no pieces.</li>
  <li>A layer in <strong>Not-in-inventory mode</strong> only takes pieces that are missing from the active BrickLink inventory (<code>.bsx</code>). Those pieces never go to the normal bins, and normal pieces never go there.</li>
  <li>A piece that matches no rule, in a profile with no fallback for everything else, does not use a bin. It drops down the middle of the chute into the bucket under the tower. So does a piece that is too big for the layer its bin is on (<a href="{{ '/hive/first-profile/send-it-to-your-machine/' | relative_url }}">Send it to your machine</a> has the sizes).</li>
</ul>

## How a category gets a bin

**When you activate a profile.** A profile from Hive always starts with every bin unassigned. A profile uploaded on the machine's **Profiles** page asks how to start: **Reset the bins** does the same, and **Pre-assign from the rules** puts the first rule in the first bin of Layer 1, the second rule in the next bin, and so on. For an uploaded profile, the order of the rules is how you plan the bins in advance.

**As pieces arrive.** A category with no bin takes the first unassigned bin the first time one of its pieces needs one.

**By hand.** On the Bins page, open a bin (or its **⋯** menu, **Assign categories**) and pick the categories it takes. A category you assign by hand moves to that bin and leaves any other bin it was in.

**Auto-assign.** Ranks the active profile's categories by how many pieces the last seven days of sorting sent to each, then gives the busiest categories the largest bins. It overwrites the normal bins' assignments. **Auto-assign and overlap** also lets the leftover categories share bins. On a profile the machine has never sorted with, it has nothing to rank.

The category picker only lists the categories of the profile that is active. You cannot set up the bins of a profile the machine is not running.

One category can have more than one bin. Its pieces are then spread across those bins at random rather than filling one before the next. One bin can take more than one category when **Allow multiple categories per bin** is on, which matters most when the bins run out (see [When a bin fills up](#when-a-bin-fills-up)).

## Keep a profile's bins when you switch profiles

Activating a different profile clears every bin's categories and marks every bin empty. To get a profile's bins back later, save them before you switch.

**Save them.** On the Bins page, the **Bin layout** panel has **Save as new**. Give it a name. It saves every bin's categories, the layer settings (the bin limit, which sections are on) and the Not-in-inventory bins, and it belongs to the profile that is active. If bins get assigned after you save, during a run for example, the panel shows **Unsaved**; **Save changes** brings the saved layout up to date.

**Bring them back.**

<ol class="numbered-steps">
  <li>Activate the profile again.</li>
  <li>On the Bins page, open the <strong>Bin layout</strong> dropdown, pick that profile's layout and press <strong>Switch</strong>.</li>
</ol>

Switching restarts the machine's software, which takes a few seconds, and the bins come back as you saved them. The dropdown only lets you pick layouts that belong to the active profile, so activate the profile first.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>After you activate a different profile, the Bin layout panel still shows the previous profile's layout, marked <strong>Unsaved</strong>. Do not press <strong>Save changes</strong> then: it overwrites the previous profile's layout with the new profile's bins. For the new profile, use <strong>Save as new</strong>.</p>
</div>

## A newer version of the same profile

Bins remember rules, not versions. When you edit a rule in Hive, or move it, it stays the same rule, so a newer version of a profile keeps its bins.

<ul class="bulleted-list">
  <li><strong>The machine is running the older version.</strong> The Profiles page says the newer version is on Hive and offers <strong>Update</strong>. Updating keeps every bin's categories and what is in it.</li>
  <li><strong>You choose the version some other way</strong>, from the profile's card or after running another profile. That counts as switching profiles and clears the bins. Saved layouts belong to the profile, not to one version, so switch to the one you saved.</li>
  <li><strong>A rule that is new in that version</strong> has no bin until its first piece arrives, or until you assign it one. Deleting a rule and making it again counts as a new rule.</li>
  <li><strong>A rule you deleted</strong> leaves its bin assigned to a rule that no longer exists, so the bin stays taken. Open the bin and remove it under <strong>Assign categories</strong>.</li>
</ul>

## When a bin fills up

A bin is only ever full if its layer has a **Bin limit**, set under **Settings**, **Storage layers**: the most pieces one bin on that layer takes, the same for every bin on the layer. The machine counts pieces; it cannot see how full a bin really is. With no limit, it never counts a bin as full.

When a category's bin is full, its next piece goes to the first of these that exists:

<ol class="numbered-steps">
  <li>Another bin with the same category that is not full.</li>
  <li>The first unassigned bin, which then takes that category too. From then on the category has two bins, and once you empty the first, its pieces are spread across both.</li>
  <li>If <strong>Allow multiple categories per bin</strong> is on, the bin with the fewest categories that is not full.</li>
  <li>The bucket under the tower, and sorting carries on. If <strong>Settings</strong>, <strong>Incidents</strong>, <strong>No bin for this piece</strong> is set to <strong>Call the operator</strong>, the machine stops instead and waits for you to assign a bin, free one up, or send that piece to the bucket.</li>
</ol>

**How you find out.** On the Bins page, every bin on a layer with a limit has a bar and a count, such as `46 / 50`. It turns amber at 85% and red when the bin is full. Nothing else tells you: there is no alert when a bin fills.

## Emptying bins

Empty the bin physically first. The machine has no way to check, and takes your word for it.

<ul class="bulleted-list">
  <li><strong>Empty this bin</strong> (in the bin's <strong>⋯</strong> menu), <strong>Empty the layer</strong> and <strong>Empty all bins</strong> set the count back to zero and keep the categories. This is the one to use after you take the pieces out. Until you do, a full bin stays full.</li>
  <li><strong>Reset this bin and clear its assignment</strong>, <strong>Reset the layer</strong> and <strong>Reset all bins</strong> do the same and also remove the categories, so the bins are assigned again as pieces arrive.</li>
</ul>

To keep a record of what was in the bins before you empty them, use **Snapshots** or **Export CSV** at the top of the Bins page. [Exporting what the machine sorted]({{ '/sorter/export-counts/' | relative_url }}) covers both.
