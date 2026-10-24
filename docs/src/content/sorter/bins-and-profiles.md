---
layout: default
title: Bins and profiles
type: explanation
section: sorter
slug: sorter-bins-and-profiles
kicker: "SorterOS: Operate"
lede: Which bin each category goes in, what Hive and the machine each call things, how to keep a profile's bins when you switch profiles, and what happens when a bin is full.
permalink: /sorter/bins-and-profiles/
author: brickcyclealice
warning: >-
  **AI-generated first draft.** Written from the SorterOS source, not from using it on a
  machine. SorterOS changes quickly. This page describes what each feature does, but a
  button's name, or where it is, may have changed since this page was written.
---

A profile never says which bin a category goes in. The machine decides that, and you can change it on the **Bins** page.

## The same thing, different names

Hive and the machine use different names for the same things. One piece goes this way:

<p><strong>Rule</strong> in Hive &rarr; <strong>category</strong> on the machine &rarr; <strong>bin</strong> on the tower</p>

<table class="stack-table stack-table-long">
  <thead><tr><th>In Hive</th><th>On the machine</th><th>What it is</th></tr></thead>
  <tbody>
    <tr><td data-label="In Hive"><strong>Profile</strong>, with versions (v1, v2, ...)</td><td data-label="On the machine"><strong>Profile</strong>, on the <strong>Profiles</strong> page. You <strong>activate</strong> it.</td><td data-label="What it is">All the sorting instructions.</td></tr>
    <tr><td data-label="In Hive"><strong>Rule</strong>. A rule for a whole set is a <strong>kit</strong>.</td><td data-label="On the machine"><strong>Category</strong></td><td data-label="What it is">A group of pieces that go in the same bin.</td></tr>
    <tr><td data-label="In Hive"><strong>Everything else</strong>, with <strong>Where the rest go</strong> set to <strong>All together</strong></td><td data-label="On the machine"><strong>Discard bin</strong></td><td data-label="What it is">The pieces no rule takes, all dropped in the bucket under the tower. It is not a real bin.</td></tr>
    <tr><td data-label="In Hive"><strong>Everything else</strong>, with <strong>Where the rest go</strong> set to <strong>BrickLink categories</strong>, <strong>Rebrickable categories</strong> or <strong>Color</strong></td><td data-label="On the machine">One <strong>category</strong> per group: for example one for Plate and one for Tile, or one for each colour</td><td data-label="What it is">The pieces no rule takes, split into groups. Each group gets a bin, the same as a rule.</td></tr>
    <tr><td data-label="In Hive">Not in Hive</td><td data-label="On the machine"><strong>Bin</strong>, in a <strong>section</strong>, on a <strong>Layer</strong></td><td data-label="What it is">A place on the tower that catches pieces.</td></tr>
    <tr><td data-label="In Hive">Not in Hive</td><td data-label="On the machine"><strong>Bin layout</strong></td><td data-label="What it is">Which categories each bin takes, saved for one profile.</td></tr>
  </tbody>
</table>

Hive's profile summary also counts rules as categories, and [Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}) calls them boxes. All three are the same thing.

A category on the machine is not a BrickLink category, unless your **Everything else** sorts by BrickLink category.

## Layers, sections and bins

The bins sit in a grid around the tower:

<ul class="bulleted-list">
  <li>A <strong>layer</strong> is one level of the tower, all the way round: <strong>Layer 1</strong>, <strong>Layer 2</strong>, and so on. Each layer has its own door.</li>
  <li>A <strong>section</strong> is a column going up the tower. <strong>Section 1</strong> is in the same place on every layer.</li>
  <li>A <strong>bin</strong> is where a layer and a section meet. A half-size layer has 2 bins in each section, a third-size layer has 3.</li>
</ul>

Bin numbers start again at 1 on every layer. So a bin is named by its layer and its number, for example Layer 3, bin 4. Seen from outside the tower, the numbers count up from right to left: the bins of a third-size section read 3, 2, 1 from left to right.

The chute turns to point at a section, and the layer whose door is closed catches the piece.

## The Bins page

The page shows each layer, its sections, and their bins. Each bin shows its number, its categories, and the pieces in it. A bin with no category says **Unassigned**.

<ul class="bulleted-list">
  <li>You can turn off a layer, or one section of a layer. It then gets no pieces.</li>
  <li><strong>Sections across all layers</strong> turns a whole column off on every layer at once, or points the chute at it so you can find it.</li>
  <li>A layer in <strong>Not-in-inventory mode</strong> only takes pieces that are not in your active BrickLink inventory (<code>.bsx</code>).</li>
  <li>Pieces in the profile's <strong>Everything else</strong> do not go in a bin. They drop into the <strong>Discard bin</strong>, the bucket under the tower.</li>
  <li>A piece longer than 10 studs (80 mm) drops into the Discard bin. A smaller piece can still be too big for some bins: see <a href="#how-big-a-piece-each-layer-takes">How big a piece each layer takes</a>.</li>
</ul>

## The 3D page

The **3D** page draws your machine with every bin where it really is on the tower. Each bin shows its number, its categories, and the last 4 pieces that went in. A bin you cannot use is faded: its layer or section is off, or the chute cannot reach it.

Use it to:

<ul class="bulleted-list">
  <li><strong>Find a bin on the machine.</strong> The Bins page gives a bin's number. The 3D page shows you which bin on the tower that is, before you empty it.</li>
  <li><strong>See what a bin takes.</strong> Click a bin to see its categories, its layer, its section and its number.</li>
  <li><strong>Check the chute lines up with a bin.</strong> Pause the machine, click the bin, and press <strong>Point the chute here</strong>. The chute must be homed first.</li>
  <li><strong>See which layer catches the next piece.</strong> The <strong>Machine</strong> panel shows where the chute points and which layer's door is closed. The layer with the closed door catches the next piece.</li>
  <li><strong>See the chute and the doors.</strong> Turn on <strong>See inside</strong> to look through the frame and the bins.</li>
</ul>

The page tells you how to turn, zoom and move the view.

## Homing the chute

The chute aims at a bin by counting from its home. It never homes again by itself while it sorts, however long it runs.

<ul class="bulleted-list">
  <li><strong>After a stall</strong> the chute no longer knows where it is. The machine stops and shows <strong>Chute needs homing</strong>. Press <strong>Home chute</strong> on that card.</li>
  <li><strong>To home it yourself</strong>, pause the machine first, then press <strong>Home the chute</strong> at the top of the Bins page.</li>
  <li><strong>If pieces start landing in the wrong bin</strong>, pause the machine and home the chute before you try anything else. If that does not fix it, see <a href="{{ '/sorter/chute-calibration/' | relative_url }}">Chute calibration</a>.</li>
</ul>

## How a category gets a bin

**When you activate a profile.** A profile from Hive starts with every bin unassigned. A profile you uploaded on the **Profiles** page asks you to choose:

<ul class="bulleted-list">
  <li><strong>Reset the bins</strong>: every bin starts unassigned.</li>
  <li><strong>Pre-assign from the rules</strong>: the first rule's category goes in the first bin of Layer 1, the second rule's in the next bin, and so on.</li>
</ul>

**When the first piece arrives.** A category with no bin gets the first unassigned bin.

**By hand.** On the Bins page, open a bin and choose **Assign categories**. If the category was in another bin, it moves to this one.

**Auto-assign.** The categories with the most pieces in the last 7 days get the biggest bins. This replaces the current assignments. A profile you have not sorted with yet has no pieces to count, so Auto-assign cannot help there.

You can only assign categories from the active profile. You cannot set up the bins of a profile the machine is not running.

A category can have more than one bin. The machine then puts each piece in one of them at random.

## Name bins by part, color or both

By default a bin is named by a category. Sorting in several passes (first by category, then by part, then by color) works with other names too. Hive has three profiles that set this up when you activate them:

<ul class="bulleted-list">
  <li><strong>One bin per part</strong>: each part number gets its own bin, in any color.</li>
  <li><strong>One bin per color</strong>: each color gets its own bin, whatever the part.</li>
  <li><strong>One bin per part and color (LOT)</strong>: each combination of part and color gets its own bin, like a lot on BrickLink.</li>
</ul>

Activating one of them switches the naming and resets the bins' assignments, because bins named the old way would never match again. Activating a profile without a naming of its own switches back to categories. You can also choose the naming yourself under <strong>Name bins by</strong> on the Bins page. A piece with no known part goes to the Discard bin when the naming includes the part.

A bin can have more than one category if **Allow multiple categories per bin** is on.

## How big a piece each layer takes

The funnels on a layer set the biggest piece its bins can take:

<ul class="bulleted-list">
  <li><strong>Third-size layer</strong> (18 bins): up to 6 studs (48 mm).</li>
  <li><strong>Half-size layer</strong> (12 bins): up to 8 studs (64 mm).</li>
</ul>

Give a category whose pieces can be bigger than 6 studs a bin on a half-size layer. Do not count on the machine to stop a big piece going into a third-size bin.

The machine looks up the size of every part it identifies. A piece longer than 10 studs (80 mm) always goes to the Discard bin. A piece between 8 and 10 studs is still sent to its bin, and can get stuck even in a half-size funnel.

## Switch profiles and keep your bins

Activating a different profile removes every bin's categories and sets every bin's count to zero. Save the bins before you switch, and you can bring them back later.

**Save the bins**

<ol class="numbered-steps">
  <li>Go to the Bins page.</li>
  <li>In <strong>Bin layout</strong>, press <strong>Save as new</strong>.</li>
  <li>Type a name, for example the profile's name, and save.</li>
</ol>

The saved layout belongs to the active profile. It keeps each bin's categories and the layer settings.

If the bins change after you save, for example during a sort run, **Bin layout** shows **Unsaved**. Press **Save changes** to save the bins as they are now.

**Bring the bins back**

<ol class="numbered-steps">
  <li>Activate the profile.</li>
  <li>Go to the Bins page.</li>
  <li>In <strong>Bin layout</strong>, choose the layout you saved for this profile.</li>
  <li>Press <strong>Switch</strong>.</li>
</ol>

The machine restarts its software. This takes a few seconds. You can only choose a layout that belongs to the active profile.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>After you activate a different profile, <strong>Bin layout</strong> still shows the old profile's layout, marked <strong>Unsaved</strong>. Do not press <strong>Save changes</strong> then. It replaces the old profile's saved bins with the new profile's bins. For the new profile, press <strong>Save as new</strong>.</p>
</div>

## Update a profile to a newer version

A newer version of the same profile can keep its bins. A rule you edit or move in Hive is still the same rule, so its category keeps its bin.

<ul class="bulleted-list">
  <li><strong>To keep the bins</strong>, run the older version, then press <strong>Update</strong> on the <strong>Profiles</strong> page. <strong>Update</strong> appears when Hive has a newer version. The bins keep their categories and their counts.</li>
  <li><strong>If you choose the version on the profile's card instead</strong>, the bins are reset, the same as switching profiles. Then bring back the layout you saved. A saved layout works for every version of its profile.</li>
  <li><strong>A new rule's category</strong> gets a bin when its first piece arrives. You can also assign it a bin by hand.</li>
  <li><strong>A rule you deleted</strong> leaves its category in its bin, and no other category gets that bin. Empty the bin, then open its <strong>⋯</strong> menu and choose <strong>Reset this bin and clear its assignment</strong>.</li>
  <li>A rule you delete and then make again is a new rule.</li>
</ul>

## When a bin is full

A bin is full when it reaches its layer's **Bin limit**. Set the limit in **Settings**, **Storage layers**. It is the same for every bin on that layer. With no limit, a bin is never full. The machine counts pieces. It does not see how full the bin really is.

When a category's bin is full, the next piece goes to:

<ol class="numbered-steps">
  <li>Another bin with that category that is not full.</li>
  <li>If there is none, the first unassigned bin. That bin now also has the category.</li>
  <li>If there is none, and <strong>Allow multiple categories per bin</strong> is on: the bin with the fewest categories that is not full.</li>
  <li>If there is none: the Discard bin. Sorting continues.</li>
</ol>

After step 2, the category has two bins. When you empty the first bin, its pieces go into both bins at random.

To make the machine stop at step 4 instead, go to **Settings**, **Incidents**, and set **No bin for this piece** to **Manual**.

**See which bins are full.** On the Bins page, each bin on a layer with a limit has a bar and a count, for example `46 / 50`. The bar turns amber at 85% and red when the bin is full. The machine gives no other warning.

## Empty a bin

<ol class="numbered-steps">
  <li>Take the pieces out of the bin.</li>
  <li>On the Bins page, open the bin's <strong>⋯</strong> menu and choose <strong>Empty this bin</strong>.</li>
</ol>

The count goes back to zero, and the bin keeps its categories. If you skip step 2, a full bin stays full, because the machine cannot see that the bin is empty.

To empty more bins at once, use **Empty the layer** or **Empty all bins**.

**Reset this bin and clear its assignment**, **Reset the layer** and **Reset all bins** also remove the categories. Use them when you want those bins assigned again from the start.

Before you empty the bins, you can keep a record of what was in them with **Snapshots** or **Export CSV** on the Bins page. [Exporting what the machine sorted]({{ '/sorter/export-counts/' | relative_url }}) explains both.
