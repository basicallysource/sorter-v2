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
lede: Activate the version on your machine from its Profiles page, decide on the machine which bin each box lands in, and know where a piece goes when its box has no bin, and how a kit's counts work.
permalink: /hive/first-profile/send-it-to-your-machine/
contributors: [brickcyclealice]
warning: >-
  **AI-generated first draft.** Rewritten on 2026-10-02 from Hive's and the sorter's source after the
  sorting profiles overhaul, not from clicking through the flow start to finish.
  Correct it as you use it.
---

Save the version in Hive. A version reaches a machine only when someone activates it **on that machine**: nothing you save in Hive, and nothing an assistant saves for you, changes what a machine sorts by itself.

## Activate it on the machine

Open the machine's **Profiles** page. Under **Profiles from Hive** are your own profiles, the ones you saved to your library, and Hive's defaults. Your machine must be linked to your Hive account (**Settings**, **Hive**) for this to list anything.

- **Activate** puts a profile in place at its newest version: your own newest, or the newest the owner published of someone else's. The menu beside it picks another version and marks the drafts. Someone else's profile has to be published by its owner and saved to your library first (**Save to library** on its page).
- Activating a different profile asks you to **empty all the physical bins first**, and then resets every learned bin assignment. After that, bins are assigned again as pieces are sorted. Press **Empty the bins and activate**.
- When Hive has a newer version of the profile the machine is already running, the **On this machine** panel says so (*v3 is on Hive; this machine runs v2*), with an **Update** button. **Update** puts the new version in place and leaves the bins as they are: they keep what is in them and their assignments. A kit's counts do start again. See [kits and their counts](#kits-and-their-counts).

A machine that is linked to Hive and has no profile yet starts on Hive's first default profile, **BrickLink categories**, with no setup.

Hive has no button that downloads a profile as a file. If your machine is not linked to Hive, its own **Profiles** page accepts a profile file (`.json`) with **Upload**. Activating an uploaded profile asks how the bins should start:

- **Reset the bins** empties every assignment, and a box gets a bin the first time a piece needs one.
- **Pre-assign from the rules** gives the rules, in order, the first bins: the first rule goes to the first bin of the first section of the first layer, the second to the next bin, and so on. Read that order off the screen and put your bins where the machine expects them. Rules that are turned off are skipped.

[The profile reference]({{ '/sorter/profile-reference/' | relative_url }}) describes the file.

## Bins are chosen on the machine, not in the profile

A profile never names a bin number. It only says which boxes exist. Which bin each box lands in is decided on the machine.

A box gets a bin the first time a piece for it arrives, the first one with nothing assigned. After that, the machine's **Bins** page is where you change any of it. That page also shows you which bins are the big ones.

**A big bin is also the only kind that takes a big piece.** Every layer of the machine is either half size or third size, and the [funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}) under it sets the largest piece that layer can pass:

- A **half-size layer**, the one with 12 bins, takes a piece up to **8 studs** across (64 mm).
- A **third-size layer**, 18 bins, takes **6 studs** (48 mm).

That is tighter than the ten studs the machine accepts at the feed side, so a piece can go into the tub, be classified correctly, and still wedge on its way into the bin. Give any box holding pieces bigger than that a bin on a half-size layer; the Bins page marks which those are. If every layer on your machine is third size, six studs is the working limit for what you put in the tub. A piece that is too big for the layer its box's bin is on goes to the [discard bin](#pieces-that-go-to-the-discard-bin) instead.

You have two ways to do it.

**Assign by hand.** Open a bin and pick the category it holds. Do this when a box needs one particular bin, like plates that only lie flat in a large one.

**Auto-assign.** The machine counts which categories your last week of sorting actually produced, ranks them, and fills the biggest bins first, so the categories with the most pieces get the largest bins. It overwrites the assignments you have, so it is a good starting point, and you can then move individual ones by hand. **Auto-assign** gives bins only to as many boxes as there are bins. **Auto-assign and overlap** gives the rest a bin to share, starting from the biggest bins.

One box can live in more than one bin. When it does, pieces are spread across them at random rather than filling one and moving to the next.

**How full a bin may get** is a separate setting, on the machine under storage layers: a maximum piece count per bin, shared by every bin on that layer. Leave it empty for no limit. A bin that has reached it is full, and the machine treats it as if it were not there.

Then do a short run with twenty mixed parts and watch where they land.

## Pieces that go to the discard bin

**Everything else** in Hive is `misc` on the machine, and it is never a real bin. A piece in it falls through the doors of every layer into the **discard bin**, the box or tray under the tower. The Bins page shows it as the virtual **Discard bin**: it has no slot of its own. Put a tray under the tower before you start, and empty it by hand when it fills.

These pieces go there as well:

- A piece the machine could not identify, because the identification service gave no answer for it, or two pieces that arrived together. A profile cannot give these a bin of their own: unknown is not something a rule can test.
- A piece too big for any bin, or for the layer its box's bin is on.
- A piece whose box has no bin free, once you have approved it or when the machine is set to send it on. See below.

## When a category has no bin free

A profile can ask for more bins than a machine has. A fallback by category or by color is the usual way: it gives every category or color that turns up a box of its own. For a piece whose box is not Everything else, the machine looks for a bin in this order:

1. **A bin that already holds the box and is not full.** With several, the piece goes to one of them at random, so they fill evenly.
2. **The first bin with nothing assigned.** That bin now belongs to the box. This is how boxes get their bins as pieces arrive, and how a box whose bins are all full takes another.
3. **A bin that shares.** If every bin is assigned, and **Allow multiple categories per bin** is on (on the Bins page, off by default), the box joins the bin with the fewest boxes in it, and among those the one with the fewest pieces.
4. **No bin.** The machine stops with the **No bin for this piece** incident: *No bin takes this piece. Assign a bin or free one up, or send it to the bucket.* Assign or free a bin, and the piece goes there. **Send to bucket** drops this one piece into the discard bin and the machine carries on.

To have the machine send such pieces to the discard bin without stopping, open **Settings**, **Incidents**, and set **No bin for this piece** to **Off**.

The simplest way not to run out is a profile whose boxes are fewer than the bins and whose fallback is **All together**, because Everything else needs no bin. The pieces in it are not lost: they are in the discard bin, unsorted.

## Kits and their counts

A kit's box takes a piece of one of its parts, in one of its colors, only while the kit still needs it. The machine counts each piece it sends into a kit's bin against that line (a part in a color). When a line has its quantity, the kit stops taking that part in that color and the piece goes on to the next rule that takes it. The fifth red 2 x 4 for a kit that wants four goes to a broader box below, such as Bricks, or to the fallback or Everything else if no rule takes it. A line with no color counts a piece of any color toward it.

The counts work like this:

- **They are kept on the machine** and survive a restart. Hive's page for a profile with kits shows each of your machines' progress, found and needed for each kit, and refreshes as machines report.
- **They follow what the machine sent.** Emptying a bin does not lower a count.
- **They belong to one compiled profile.** The machine keeps one set of counts, saved with the profile's hash, a fingerprint of the compiled profile. Activating a version with a different hash starts every count again from zero. Any change to the rules, their order, the fallback or a kit's lines gives a new hash, so activating or updating to a newer version resets the counts, and going back to an earlier one does not bring the old counts back. Activating the very same version again keeps them.
- **A kit's lines are fixed when you save a version.** If you change a kit, save a new version of each profile that uses it and activate that. The counts start again from zero then, too.

Put the kit above broader rules in the list, or those take its parts first and it never fills.

## Older machine software

A machine on software from before the overhaul can still run most profiles, with two differences. It keeps sending a piece to a kit's bin after the kit is full, because it cannot pass it on. A profile that sorts the rest by color is not offered to it at all. Update the machine's software to get both.

Next: [your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }}) puts the profile to work.

Back to [Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}).
