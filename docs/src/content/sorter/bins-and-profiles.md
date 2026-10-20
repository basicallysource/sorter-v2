---
layout: default
title: Bins and profiles
type: explanation
section: sorter
slug: sorter-bins-and-profiles
kicker: "SorterOS: Operate"
lede: Which bin each category goes in, how to keep a profile's bins when you switch profiles, and what happens when a bin is full.
permalink: /sorter/bins-and-profiles/
author: brickcyclealice
warning: >-
  **AI-generated first draft.** Written from the SorterOS source, not from using it on a
  machine. SorterOS changes quickly. This page describes what each feature does, but a
  button's name, or where it is, may have changed since this page was written.
---

A profile sorts pieces into categories. It never says which bin a category goes in. The machine decides that, and you can change it on the **Bins** page.

## The Bins page

The page shows each storage layer: **Layer 1**, **Layer 2**, and so on. A layer has sections, and a section has bins. Each bin shows its number, its categories, and the pieces in it. A bin with no category says **Unassigned**.

<ul class="bulleted-list">
  <li>You can turn off a layer or a section. It then gets no pieces.</li>
  <li>A layer in <strong>Not-in-inventory mode</strong> only takes pieces that are not in your active BrickLink inventory (<code>.bsx</code>).</li>
  <li>Pieces in the profile's <strong>Everything else</strong> do not go in a bin. They drop into the bucket under the tower.</li>
  <li>A piece that is too big for its bin's layer also drops into the bucket. <a href="{{ '/hive/first-profile/send-it-to-your-machine/' | relative_url }}">Send it to your machine</a> has the sizes.</li>
</ul>

## How a category gets a bin

**When you activate a profile.** A profile from Hive starts with every bin unassigned. A profile you uploaded on the **Profiles** page asks you to choose:

<ul class="bulleted-list">
  <li><strong>Reset the bins</strong>: every bin starts unassigned.</li>
  <li><strong>Pre-assign from the rules</strong>: the first rule goes in the first bin of Layer 1, the second rule in the next bin, and so on.</li>
</ul>

**When the first piece arrives.** A category with no bin gets the first unassigned bin.

**By hand.** On the Bins page, open a bin and choose **Assign categories**. If the category was in another bin, it moves to this one.

**Auto-assign.** The categories with the most pieces in the last 7 days get the biggest bins. This replaces the current assignments. A profile you have not sorted with yet has no pieces to count, so Auto-assign cannot help there.

You can only assign categories from the active profile. You cannot set up the bins of a profile the machine is not running.

A category can have more than one bin. The machine then puts each piece in one of them at random.

A bin can have more than one category if **Allow multiple categories per bin** is on.

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

A newer version of the same profile can keep its bins. A rule you edit or move in Hive is still the same rule, so it keeps its bin.

<ul class="bulleted-list">
  <li><strong>To keep the bins</strong>, run the older version, then press <strong>Update</strong> on the <strong>Profiles</strong> page. <strong>Update</strong> appears when Hive has a newer version. The bins keep their categories and their counts.</li>
  <li><strong>If you choose the version on the profile's card instead</strong>, the bins are reset, the same as switching profiles. Then bring back the layout you saved. A saved layout works for every version of its profile.</li>
  <li><strong>A new rule</strong> gets a bin when its first piece arrives. You can also assign it a bin by hand.</li>
  <li><strong>A rule you deleted</strong> keeps its bin, and no other category gets that bin. Empty the bin, then open its <strong>⋯</strong> menu and choose <strong>Reset this bin and clear its assignment</strong>.</li>
  <li>A rule you delete and then make again is a new rule.</li>
</ul>

## When a bin is full

A bin is full when it reaches its layer's **Bin limit**. Set the limit in **Settings**, **Storage layers**. It is the same for every bin on that layer. With no limit, a bin is never full. The machine counts pieces. It does not see how full the bin really is.

When a category's bin is full, the next piece goes to:

<ol class="numbered-steps">
  <li>Another bin with that category that is not full.</li>
  <li>If there is none, the first unassigned bin. That bin now also has the category.</li>
  <li>If there is none, and <strong>Allow multiple categories per bin</strong> is on: the bin with the fewest categories that is not full.</li>
  <li>If there is none: the bucket under the tower. Sorting continues.</li>
</ol>

After step 2, the category has two bins. When you empty the first bin, its pieces go into both bins at random.

To make the machine stop at step 4 instead, go to **Settings**, **Incidents**, and set **No bin for this piece** to **Call the operator**.

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
