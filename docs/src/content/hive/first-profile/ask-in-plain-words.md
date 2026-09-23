---
layout: default
title: Ask for it in plain words
type: tutorial
section: hive
slug: hive-ask-in-plain-words
kicker: First profile — Ask for it in plain words
lede: Describe the boxes you want in the Chat tab, one change per message. Name the boxes, say how many bins you have, and save before you send.
permalink: /hive/first-profile/ask-in-plain-words/
contributors: [brickcyclealice]
warning: >-
  **AI-generated first draft.** Written from Hive's own source and from one owner's
  first session with the chat, not from clicking through the flow start to finish.
  Correct it as you use it.
---

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

## If English is not your first language

Write to the chat in your own language. Hive does not ask for English, and the assistant normally answers in the language you wrote in. There is no list of supported languages: the chat runs on the model your OpenRouter key is pointed at, so it handles whatever that model handles. If your language comes out badly, open **Settings** and pick a different **Preferred Model**.

The parts catalog itself is English, and the rules the assistant writes have to match that English text. It translates for you. Check the result anyway: a rule that searches for a word in your own language matches nothing, and the box comes out empty with no error.

Box names are only labels. Name them in any language you like, and that is the name your machine shows.

## Asking for colour

Colour is the one thing to be careful with right now. A request like `sort by colour` produces a profile Hive cannot apply, and you get an `HTTP 502` error when it tries. This is a bug in Hive and not something you did wrong.

Until it is fixed, ask for colour like this:

`Make boxes for black, white, grey, red, blue, green, yellow and brown. Use one colour per box. Do not include shade variants.`

That produces a smaller profile, which Hive can apply. A box for grey then catches plain grey and misses light bluish grey, so the shades you did not name land in your catch-all box.

**Name colours in words, not numbers.** The assistant looks the name up for you. The numbering it sorts by is [Rebrickable's colour list](https://rebrickable.com/colors/), which gives every colour a swatch, a name, and its BrickLink and LDraw numbers. Watch out for colour charts from anywhere else: BrickLink numbers colours differently, so white is 1 there and 15 in Hive.

Next: [read what it proposes]({{ '/hive/first-profile/read-what-it-proposes/' | relative_url }}).

Back to [Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}).
