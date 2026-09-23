---
layout: default
title: Send it to your machine
type: tutorial
audience: operator
applies_to: Hive profile editor
section: hive
owner: hive
slug: hive-send-to-machine
kicker: First profile — Send it to your machine
lede: Assign the version to your machine from Hive's Machines page, then decide on the machine which bin each box lands in.
permalink: /hive/first-profile/send-it-to-your-machine/
contributors: [brickcyclealice]
warning: >-
  **AI-generated first draft.** Written from Hive's own source and from one owner's
  first session with the chat, not from clicking through the flow start to finish.
  Correct it as you use it.
---

Save the version, then open **Machines** in Hive and use **Assign Profile** on your machine. You choose the profile and which version of it. The machine picks up what it has been assigned.

Hive has no button that downloads a profile as a file. If your machine is not linked to Hive, you write the profile on the machine itself instead, and its own **Profiles** page accepts a `sorting_profile.json` upload.

## Bins are chosen on the machine, not in the profile

A profile never names a bin number. It only says which boxes exist. Which bin each box lands in is decided on the machine.

The first decision is made when you activate the profile there. The machine asks how the bins should start: **Pre-assign from rules** seeds them in the order your rules are in, and **Reset bins** empties them and gives a category a bin the first time a piece needs one.

After that, the machine's **Bins** page is where you change any of it. That page also shows you which bins are the big ones.

You have two ways to do it.

**Assign by hand.** Open a bin and pick the category it holds. Do this when a box needs one particular bin, like plates that only lie flat in a large one.

**Auto-assign.** The machine counts which categories your last week of sorting actually produced, ranks them, and fills the biggest bins first, so the categories with the most pieces get the largest bins. It is a good starting point, and you can then move individual ones by hand.

One box can live in more than one bin. When it does, pieces are spread across them rather than filling one and moving to the next.

**How full a bin may get** is a separate setting, on the machine under storage layers: a maximum piece count per bin, shared by every bin on that layer. Leave it empty for no limit.

Then do a short run with twenty mixed parts and watch where they land.

Next: [your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }}) puts the profile to work.

Back to [Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}).
