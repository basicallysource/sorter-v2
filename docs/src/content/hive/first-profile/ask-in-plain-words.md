---
layout: default
title: Ask for it in plain words
type: tutorial
audience: operator
applies_to: Hive profile editor
section: hive
owner: hive
slug: hive-ask-in-plain-words
kicker: First profile — Ask for it in plain words
lede: Describe the boxes you want to the assistant, one change per message, in Hive's editor or in an assistant you already use. Name the boxes, say how many bins you have, and save before you send.
permalink: /hive/first-profile/ask-in-plain-words/
contributors: [brickcyclealice]
warning: >-
  **AI-generated first draft.** Rewritten on 2026-10-02 from Hive's and the sorter's source after the
  sorting profiles overhaul, not from clicking through the flow start to finish.
  Correct it as you use it.
---

There are two ways to have an assistant write the profile. Both end the same way: the rules appear as a new saved version of your profile, which you read and then send to your machine.

- **Hive's own assistant**, in the profile editor. It needs your own [OpenRouter key]({{ '/hive/first-profile/openrouter-key/' | relative_url }}).
- **An assistant you already use**, pointed at Hive with a key. It needs no OpenRouter key. See [an assistant you already use](#an-assistant-you-already-use).

## In Hive's editor

Open your profile, press **Edit profile**, go to the **Assistant** tab beside the rules, and say what you want. On a narrow screen it is one of the tabs along the top. These all work, and the pieces they leave out go to **Everything else**:

- `Sort by part type: bricks, plates, tiles, slopes and wedges.`
- `Sort Technic parts by function: gears, beams, pins, axles, connectors.`
- `I have 12 bins, so give me at most 12 boxes.`
- `Put all minifigure parts and accessories in their own box.`

The assistant looks parts, colors, categories and sets up in the catalog, writes the rules, and saves them as a new version at once, showing each step it takes. It can add, change, move and delete rules, and add a LEGO set, or a parts list you give it, as a kit. It does not change the fallback, the choice for what no box takes: you make that on the **Everything else** row (see [asking for colour](#asking-for-colour)).

Three things make a request work:

- **Name the boxes.** "Sort my LEGO" gives the assistant nothing to aim at. A list of box names gives it everything.
- **Say how many bins you have**, so it does not propose twenty boxes for a machine with eight.
- **One change per message.** Build the profile up in small steps: ask for the boxes, look, then ask for the next change.

Once you have the first version, keep going in the same chat. `Split the bricks box into 1xN bricks and everything larger.` `Move wedges in with slopes.` `Add a box for wheels and tyres.` Each message changes the profile you already have.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>Save before you send a message.</strong> The assistant works from the last saved version of the profile, not from what is on your screen, and it saves its answer as the newest version. Edits you have not saved are replaced when it does, and they are not kept anywhere. Every saved version stays under <strong>Versions</strong>, where <strong>Restore</strong> saves an old one again as the newest.</p>
</div>

### If English is not your first language

Write to the assistant in your own language. Hive does not ask for English, and the assistant normally answers in the language you wrote in. There is no list of supported languages: the assistant runs on the model your OpenRouter key is pointed at, so it handles whatever that model handles. If your language comes out badly, open **Settings** and pick a different **Model** in the **AI assistant** panel.

The parts catalog itself is English, and the rules the assistant writes have to match that English text. It translates for you. Check the result anyway: a rule that searches for a word in your own language matches nothing, and the box comes out empty. Hive warns on a rule that matches nothing.

Box names are only labels. Name them in any language you like, and that is the name your machine shows.

## Asking for colour

Colour works. For one bin for each color, click **Everything else** at the bottom of your rules and choose **Color** under **Where the rest go**. Make that choice yourself: Hive's assistant does not change it. Ask for boxes of your own when you want specific colors:

`Make boxes for black, white, grey, red, blue, green, yellow and brown. Use one colour per box. Do not include shade variants.`

Each color in Hive is its own color, so a box for grey takes plain grey and not light bluish grey. Name the shades you want, or leave them to the fallback, which gives every other color a bin of its own. A box for one color only takes that color, and every other color carries on down the list.

**Name colours in words, not numbers.** The assistant looks the name up for you. The numbering it sorts by is [Rebrickable's colour list](https://rebrickable.com/colors/), which gives every colour a swatch, a name, and its BrickLink and LDraw numbers. Watch out for colour charts from anywhere else: BrickLink numbers colours differently, so white is 1 there and 15 in Hive.

A profile that sorts the rest by color needs current software on the machine. A machine on older software is not offered it. An assistant you already use can set the fallback for you.

## An assistant you already use

Any assistant that can make web requests can write your profiles, with an API key from Hive. In Hive, open **Settings** and find **Connect an assistant**.

1. Press **Make a key**. Hive makes a key, named `Assistant` (or `Assistant 2` and so on when one is in use), that can read and change your sorting profiles and kits and read what your machines sorted. It cannot run your machines.
2. Hive shows one message to copy. It points the assistant at the skill Hive serves and carries the key. Paste the whole message into your assistant.
3. Ask for what you want, in the same plain words as above.

Hive shows the key once, and it is listed under **API keys** afterwards, where you can revoke it at any time. Keep it like a password.

The skill teaches the assistant to look up parts, colors, categories and sets, draft the profile, **preview** it without saving, **test pieces** ("where does a red 3001 go, and why"), save versions, build kits, set pictures, and read what your machines sorted. That last one lets it fit a profile to your own pile: the parts that come through most get a bin each, and the long tail is grouped by category. It is told to preview before it saves, to check every piece you name, and to ask before it deletes anything or makes anything public. You can read what it reads under **What the assistant reads** on the same panel.

What it saves shows on your open profile page within seconds, marked as made through the key (`Assistant`). A machine uses it only when you activate that version there, so nothing reaches a machine behind your back. Every version it saves stays under **Versions**.

Next: [read what it proposes]({{ '/hive/first-profile/read-what-it-proposes/' | relative_url }}).

Back to [Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}).
