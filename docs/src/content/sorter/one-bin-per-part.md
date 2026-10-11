---
layout: default
title: One bin per part
type: how-to
section: sorter
slug: sorter-one-bin-per-part
kicker: SorterOS — Sorting profiles
lede: Sort a mixed pile with no rules at all, so that every kind of part takes the next free bin the first time it turns up. Hive's editor cannot make this profile, so you write the file.
permalink: /sorter/one-bin-per-part/
---

Use this when you do not know in advance which parts are in the pile, and want each part number in a bin of its own. Re-sorting a batch that was sorted by something else is the usual case.

Hive's editor cannot do it. The last box there, **Everything else**, can be split by category or by color, but not by part. A profile file can: its fallback has a third choice, `part`.

## The profile

Save this as a `.json` file:

```json
{
  "schema_version": 2,
  "name": "One bin per part",
  "description": "",
  "default_category_id": "misc",
  "categories": {
    "misc": { "name": "Everything else", "kind": "default" }
  },
  "category_order": ["misc"],
  "program": {
    "format": 1,
    "rules": [],
    "fallback": { "by": "part" },
    "default": "misc"
  },
  "artifact_hash": ""
}
```

Open the machine's **Profiles** page, press **Upload JSON** under **Local profiles**, pick the file, and press **Activate** on its card. When the machine asks how the bins should start, choose **Reset the bins**, so that no bin is already taken.

## What the machine does with it

Every part gets a category of its own, named `part_` and the part's ID: `part_3001` for a 2 x 4 brick. The color does not matter, so a red and a blue 3001 share a bin.

The machine gives that category a bin the first time a piece of the part arrives, and the bin stays assigned to it. The first part to turn up takes the first free bin, the next new part takes the following one, and so on. Nothing in the profile changes when the pile does.

When every bin is taken, a new part is handled like any category that has no bin free: it joins a shared bin if **Allow multiple categories per bin** is on (on the Bins page, off by default), and otherwise the machine stops with the **No bin for this piece** incident, or sends the piece to the discard bin if you have set that incident to **Off**. [Send it to your machine]({{ '/hive/first-profile/send-it-to-your-machine/' | relative_url }}) has the full order. Know how many different parts your pile has against your bins before you start: a machine has far fewer bins than LEGO has parts.

To start over with empty bins, choose **Reset the bins** when you activate a profile, or reset them from the Bins page.

## Rules first, then one bin per part

`rules` can hold rules as well. The machine tries them in order, and the fallback takes only the pieces they leave. A rule that names a few parts and colors keeps those pieces together in one bin, and everything else gets a bin per part. The [sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }}) describes the program and its rules.
