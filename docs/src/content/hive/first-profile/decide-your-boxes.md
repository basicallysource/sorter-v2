---
layout: default
title: Decide your boxes
type: tutorial
audience: operator
applies_to: Hive profile editor
section: hive
owner: hive
slug: hive-decide-your-boxes
kicker: First profile — Decide your boxes
lede: How many bins you have and what you want to separate decide the whole profile. Settle both on paper, or start from one of Hive's defaults.
permalink: /hive/first-profile/decide-your-boxes/
contributors: [brickcyclealice]
warning: >-
  **AI-generated first draft.** Rewritten on 2026-10-02 from Hive's and the sorter's source after the
  sorting profiles overhaul, not from clicking through the flow start to finish.
  Correct it as you use it.
---

Two questions decide the whole profile.

**How many bins does your machine have?** Every box needs somewhere to land. Ask for fewer boxes than you have bins. Pieces that end up in **Everything else** do not use a bin: they drop into the [discard bin]({{ '/hive/first-profile/send-it-to-your-machine/#pieces-that-go-to-the-discard-bin' | relative_url }}) under the machine.

**Not every bin takes every piece.** The big bins are the only ones a big piece fits through, so a box holding large parts has to get one of those. [Send it to your machine]({{ '/hive/first-profile/send-it-to-your-machine/#bins-are-chosen-on-the-machine-not-in-the-profile' | relative_url }}) has the sizes and what to do about it.

**What do you want to separate?** Part type (bricks, plates, tiles), color, and the two together all work. Write your list on paper first. It is easier than thinking the boxes up in the assistant.

## Or start from a default

You do not have to build anything to sort. Hive keeps three profiles that every machine can use without anyone saving them. They are under **Hive defaults** on Hive's **Profiles** page, and on the machine's own Profiles page with a **Hive default** badge.

| Default | What it does |
|---|---|
| **BrickLink categories** | No rules. One bin for each BrickLink category (Brick, Plate, Tile, Slope, and so on), whatever the color. |
| **Colors** | One bin for each color, whatever the part. |
| **Colors and basic pieces** | Bricks, plates, tiles and slopes each get a bin, in any color. Everything else goes by color. |

A machine that is linked to Hive and has no profile yet starts on the first one, **BrickLink categories**. Pick another from the machine's **Profiles** page.

Each default sorts by one thing, so each can look unsorted if you expect another. A BrickLink categories bin of plates holds plates in every color, and a red bin in Colors holds bricks, plates and tiles. Each default also hands out a bin to every category or color that turns up, so a mixed pile can ask for more bins than the machine has. [Send it to your machine]({{ '/hive/first-profile/send-it-to-your-machine/#when-a-category-has-no-bin-free' | relative_url }}) says what the machine does then.

To change a default, press **Fork this profile** on its page. The copy is yours to edit. The defaults themselves belong to Hive and stay as they are.

## Three kinds of box

A profile is an ordered list of boxes, and a box is one of two things. What no box takes is the third.

**A rule** describes parts: "all tiles", "everything in dark bluish grey", "Technic pins". It catches however many parts match that description, with no limit and no counting. Most boxes are rules.

**A kit** is a list of parts, each in a color and with a quantity: a LEGO set, a customer order, a build. Its box collects pieces of those parts until each line has its quantity. After that, pieces of that part go on to the next box that takes them, so a kit never takes more than it needs. The machine counts what it has sent to each kit, which is how you can tell how much of the kit you have found. Make kits on Hive's **Kits** page with **New kit**:

- **By hand**: name it, then add parts with their colors and quantities.
- **From a LEGO set**: every part of the set in the set's colors. Spare parts are left out unless you tick **Include spare parts**.
- **From a BrickLink list**: a wanted list saved as a CSV file with the columns `BLItemNo`, `BLColorId` and `Qty`. Those are BrickLink's color numbers, and in this one file they are the correct ones.

A line with no color is allowed: a piece of any color then counts toward it. Hive flags such a line, because it is rarely what an order wants.

In a profile, **Add kit** puts a kit in as a box. Put a kit **above** broader rules, or those take its parts first. The editor warns when they do. [Send it to your machine]({{ '/hive/first-profile/send-it-to-your-machine/#kits-and-their-counts' | relative_url }}) covers how the counts work. **New profile** also offers a **Kit based** profile, which starts from the LEGO sets you pick. Profiles saved before kits existed keep working, and saving a version turns each of their sets into a kit of its own.

**What no box takes** is the **fallback**. You choose one thing for it:

- **All together**: every piece no box takes goes to the one **Everything else** box, which is the discard bin.
- **BrickLink categories**: one bin for each BrickLink category.
- **Rebrickable categories**: one bin for each Rebrickable category.
- **Color**: one bin for each color.

Choose by what you are asking. Sorting a pile into boxes is rules. "Do I have everything for this model" or "fill this order" is a kit. "Sort the rest somehow" is the fallback.

Next: [ask for it in plain words]({{ '/hive/first-profile/ask-in-plain-words/' | relative_url }}).

Back to [Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}).
