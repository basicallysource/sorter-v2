---
layout: default
title: Build your first sorting profile
type: tutorial
audience: operator
applies_to: Hive profile editor
section: hive
owner: hive
slug: hive-first-profile
kicker: Hive — Tutorial
lede: Ask Hive's assistant for the boxes you want, read what it proposes, and send the result to your machine. You do not write any rules by hand.
permalink: /hive/first-profile/
contributors: [brickcyclealice]
warning: >-
  **AI-generated first draft.** Written from Hive's own source and from one owner's
  first session with the chat, not from clicking through the flow start to finish.
  Correct it as you use it.
---

A sorting profile is the list of boxes your machine sorts into, plus the rules that decide which box a part belongs in. One box is one category, and a category can be spread over several bins.

You do not have to write rules. Hive has a chat that builds the profile for you: you describe the boxes you want in ordinary words, it proposes the rules, and Hive applies them. This page is the short version of doing that for the first time.

For the file itself, field by field, see the [sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }}). You do not need it to make a working profile.

## Before you start

- A Hive account, signed in.
- An OpenRouter key saved in Hive under **Settings**, if you want the chat to write the profile for you. It is your own key and your own credit, and Hive never sees your card. See [set up an OpenRouter key](#set-up-an-openrouter-key) at the bottom of this page.
- Twenty minutes or so. Every save is a new version and the old ones stay, so nothing you do here is permanent.

Without a key you can still build a profile by adding rules by hand in the editor.

## 1. Decide your boxes before you type

Two questions decide the whole profile.

**How many bins does your machine have?** Every box needs somewhere to land. Ask for fewer boxes than you have bins, and keep one spare for everything that matches nothing.

**What do you want to separate?** Sorting by part type (bricks, plates, tiles) works well today. Sorting by colour is where Hive currently struggles, and there is a workaround below.

Write your list on paper first. It is easier than thinking the boxes up in the chat.

### Three kinds of box

A box can be one of three things, and the chat can make any of them.

**A rule** describes parts: "all tiles", "everything in dark bluish grey", "Technic pins". It catches however many parts match that description, with no limit and no counting. Most boxes are rules.

**A set** is one official LEGO set, given by its set number. Hive looks up what is in that set, and the box catches exactly those parts, each in the colour the set actually uses. It also counts: the machine knows how many of each part the set needs, so it can tell you how much of the set you have found. Spare parts are left out unless you ask for them.

**A custom set** works the same way, except the part list is yours instead of LEGO's. Use it for a model of your own, a kit you sell, or a picking list. You can search for the parts and add them one at a time, or import a BrickLink CSV file with `BLItemNo`, `BLColorId` and `Qty` columns. Those are BrickLink's colour numbers, and in this one file they are the correct ones.

Choose by what you are asking. Sorting a pile into boxes is rules. "Do I have everything for this model" is a set or a custom set.

## 2. Ask for it in plain words

Open your profile, go to the **Chat** tab, and say what you want. These all work:

- `Sort by part type: bricks, plates, tiles, slopes, wedges, and one box for everything else.`
- `Sort Technic parts by function: gears, beams, pins, axles, connectors.`
- `I have 12 bins. Give me 11 boxes and one box for anything that does not match.`
- `Put all minifigure parts and accessories in their own box.`

Three things make a request work:

- **Name the boxes.** "Sort my LEGO" gives the assistant nothing to aim at. A list of box names gives it everything.
- **Say how many bins you have**, so it does not propose twenty boxes for a machine with eight.
- **One change per message.** Build the profile up in small steps: ask for the boxes, look, then ask for the next change.

Once you have the first version, keep going in the same chat. `Split the bricks box into 1xN bricks and everything larger.` `Move wedges in with slopes.` `Add a box for wheels and tyres.` Each message changes the profile you already have.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>Save before you send a message.</strong> The assistant works from the last saved version of the profile, not from what is on your screen. Hand edits you have not saved are overwritten when its answer loads, and there is no undo.</p>
</div>

### If English is not your first language

Write to the chat in your own language. Hive does not ask for English, and the assistant normally answers in the language you wrote in. There is no list of supported languages: the chat runs on the model your OpenRouter key is pointed at, so it handles whatever that model handles. If your language comes out badly, open **Settings** and pick a different **Preferred Model**.

The parts catalog itself is English, and the rules the assistant writes have to match that English text. It translates for you. Check the result anyway: a rule that searches for a word in your own language matches nothing, and the box comes out empty with no error.

Box names are only labels. Name them in any language you like, and that is the name your machine shows.

### Asking for colour

Colour is the one thing to be careful with right now. A request like `sort by colour` produces a profile Hive cannot apply, and you get an `HTTP 502` error when it tries. This is a bug in Hive and not something you did wrong.

Until it is fixed, ask for colour like this:

`Make boxes for black, white, grey, red, blue, green, yellow and brown. Use one colour per box. Do not include shade variants.`

That produces a smaller profile, which Hive can apply. A box for grey then catches plain grey and misses light bluish grey, so the shades you did not name land in your catch-all box.

**Name colours in words, not numbers.** The assistant looks the name up for you. The numbering it sorts by is [Rebrickable's colour list](https://rebrickable.com/colors/), which gives every colour a swatch, a name, and its BrickLink and LDraw numbers. Watch out for colour charts from anywhere else: BrickLink numbers colours differently, so white is 1 there and 15 in Hive.

## 3. Read what it proposes before you trust it

When the assistant answers, it changes the rules on the left. Two things are worth checking every time.

**Order matters.** Rules are tried top to bottom and the first one that matches wins. A part that could go in two boxes goes in the higher one. If everything is landing in one box, that box is probably too high in the list and too broad.

**The catch-all is doing the work you cannot see.** Anything that matches no rule goes to your default box. If that box is enormous, your rules are narrower than you think.

Click a rule to see which parts it matches. That list is what your profile actually does.

### Conditions, Match ALL, and Add child

Open a rule and you see its conditions: a field, an operator, and a value. **Add condition** adds another line to the same rule.

**The dropdown next to the rule name decides how those lines combine.** `Match ALL` means every condition has to be true, which is "and". `Match ANY` means one is enough, which is "or". A rule with two conditions on `Match ALL` catches only parts that satisfy both.

**Add child** adds a group inside the rule. A child is not a separate box. It is worked out on its own, and its answer then counts as one more true or false alongside the rule's own conditions. That is how you mix and with or.

An example: a rule on `Match ALL` with one condition, `category_id = Tile`. Inside it, a child on `Match ANY` holds `color_id = 4` and `color_id = 1`. The rule catches tiles that are red or blue, and they all go in the rule's own box.

The operators, as the editor shows them:

- `=` is exactly this value, and `!=` is anything except this value.
- `in` is any one of a list of values.
- `contains` looks for text inside a name, and `regex` is a pattern for the same job.
- `>=` and `<=` compare numbers, for fields like a year or a weight.

Which operators you get depends on the field you picked. A name can be searched with `contains`, not compared with `>=`.

### An example: four boxes in the right order

A profile with four boxes, in the order the machine tries them:

<ol class="numbered-steps">
  <li><strong>Minifigure over 5</strong>, minifigure parts worth five dollars or more.</li>
  <li><strong>Minifigure</strong>, every other minifigure part.</li>
  <li><strong>Black</strong>, anything black.</li>
  <li><strong>Red, Dark Red</strong>, anything in either red.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/hive-rule-minifigure-over-5-full-4024f25de19e.png" alt="A rule named Minifigure over 5, set to Match ALL, with two conditions: bl_price_min greater than or equal to 5, and category_name contains minifig.">
  <figcaption>The valuable parts, on <strong>Match ALL</strong>: a part has to be a minifigure part <em>and</em> worth five dollars or more. The value is typed as <code>5</code>, with no dollar sign. <cite>Screenshot courtesy of BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/hive-rule-minifigure-full-cf2141d17cb3.png" alt="A rule named Minifigure, set to Match ANY, with five conditions: category_name contains minifig heads, minifig upper, minifigs, minifig lower, minifig headwear.">
  <figcaption>One rule, five conditions, <strong>Match ANY</strong>: a part in any one of those categories is a minifigure part. <cite>Screenshot courtesy of BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/hive-rule-black-full-7d54ee69f7dd.png" alt="A rule named Black with one condition: color_id equals 0.">
  <figcaption>The black box. Colour 0 is black in Hive's numbering. <cite>Screenshot courtesy of BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/hive-rule-red-dark-red-full-9b1512b1fda9.png" alt="A rule named Red, Dark Red, set to Match ANY, with two conditions: color_id equals 320 and color_id equals 4.">
  <figcaption>Two colours in one box, on <strong>Match ANY</strong>. <cite>Screenshot courtesy of BrickCycleAlice.</cite></figcaption>
</figure>

**Put the minifigure boxes above the colour boxes.** Black hair and black legs are minifigure parts and they are also black, so whichever rule is higher takes them. In this order they go in with the rest of the minifigure parts. Put **Black** on top instead and the black box takes them, and your minifigure box comes out with no black in it.

**Put Minifigure over 5 above plain Minifigure** if you want the valuable parts separated. A five dollar hairpiece is an ordinary minifigure part as well, and the plain box takes it the moment it is the higher of the two.

**A colour box only takes the colours it names.** Everything it does not claim carries on down the list, so a black box near the bottom does not empty the boxes under it. It takes their black and leaves the rest.

**To change the order**, hover over a rule in the list and use the up and down arrows on its row.

**Type numbers on their own.** The value in the **Minifigure over 5** rule is `5`, not `$5`. A currency symbol or a unit in a number field makes the save fail with `Internal server error`, and nothing says which rule it was.

## 4. Send it to your machine

Save the version, then open **Machines** in Hive and use **Assign Profile** on your machine. You choose the profile and which version of it. The machine picks up what it has been assigned.

Hive has no button that downloads a profile as a file. If your machine is not linked to Hive, you write the profile on the machine itself instead, and its own **Profiles** page accepts a `sorting_profile.json` upload.

### Bins are chosen on the machine, not in the profile

A profile never names a bin number. It only says which boxes exist. Which bin each box lands in is decided on the machine.

The first decision is made when you activate the profile there. The machine asks how the bins should start: **Pre-assign from rules** seeds them in the order your rules are in, and **Reset bins** empties them and gives a category a bin the first time a piece needs one.

After that, the machine's **Bins** page is where you change any of it. That page also shows you which bins are the big ones.

You have two ways to do it.

**Assign by hand.** Open a bin and pick the category it holds. Do this when a box needs one particular bin, like plates that only lie flat in a large one.

**Auto-assign.** The machine counts which categories your last week of sorting actually produced, ranks them, and fills the biggest bins first, so the categories with the most pieces get the largest bins. It is a good starting point, and you can then move individual ones by hand.

One box can live in more than one bin. When it does, pieces are spread across them rather than filling one and moving to the next.

**How full a bin may get** is a separate setting, on the machine under storage layers: a maximum piece count per bin, shared by every bin on that layer. Leave it empty for no limit.

Then do a short run with twenty mixed parts and watch where they land.

## When something goes wrong

Several of the chat's error messages are bugs in Hive rather than something you did. [When the profile chat goes wrong]({{ '/hive/chat-errors/' | relative_url }}) lists every message it can show, with what to do about each one.

## Set up an OpenRouter key

The chat runs on your own OpenRouter account. Hive does not sell AI credit, and your card details stay with OpenRouter.

1. Make an account at [openrouter.ai](https://openrouter.ai).
2. Add credits at [openrouter.ai/credits](https://openrouter.ai/credits). It is prepaid, not a subscription. Building a profile costs a few cents.
3. Create a key at [openrouter.ai/keys](https://openrouter.ai/keys) and copy it. It starts with `sk-or-v1-` and is shown only once.
4. In Hive, open **Settings**, paste it into **OpenRouter API Key**, and save. The line above the field changes to `configured`.

The key is stored encrypted and is only used when you ask the assistant for something. **Remove Key** in the same place deletes it.

## Next

- [Your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }}) puts the profile to work.
- [Sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }}) is the file itself, field by field, for when you want to read or edit one directly.
