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
  The error messages quoted here are the ones Hive actually sends. Correct it as you
  use it.
---

A sorting profile is the list of boxes your machine sorts into, plus the rules that decide which box a part belongs in. One box is one category, and a category can be spread over several bins.

You do not have to write rules. Hive has a chat that builds the profile for you: you describe the boxes you want in ordinary words, it proposes the rules, and Hive applies them. This page is the short version of doing that for the first time.

For the shape of the file itself, once you want to understand or hand-edit one, see the [sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }}). That page is for later. You do not need it to make a working profile.

## Before you start

- A Hive account, signed in.
- An OpenRouter key saved in Hive under **Settings**, if you want the chat to write the profile for you. It is your own key and your own credit, and Hive never sees your card. See [set up an OpenRouter key](#set-up-an-openrouter-key) at the bottom of this page.
- Somewhere between five and twenty minutes. There is no rush and nothing you can break: every save is a new version, and old versions stay.

You can build a profile with no key at all by adding rules by hand in the editor. The chat is the faster route, not the only one.

## 1. Decide your boxes before you type

Two questions decide the whole profile.

**How many bins does your machine have?** Every box needs somewhere to land. Ask for fewer boxes than you have bins, and keep one spare for everything that matches nothing.

**What do you want to separate?** Sorting by part type (bricks, plates, tiles) works well today. Sorting by colour is where Hive currently struggles, and there is a workaround below.

Write your list on paper first. It is much easier to ask for eight boxes you have already named than to think them up in the chat.

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

### Asking for colour

Colour is the one thing to be careful with right now. A request like `sort by colour` produces a profile Hive cannot apply, and you get an `HTTP 502` error when it tries. This is a bug in Hive and not something you did wrong.

Until it is fixed, ask for colour like this:

`Make boxes for black, white, grey, red, blue, green, yellow and brown. Use one colour per box. Do not include shade variants.`

That produces a much smaller profile, which Hive can apply. The cost is real: a box for grey will catch plain grey and miss light bluish grey, so parts in the shades you did not name land in your catch-all box instead.

**Name colours in words, not numbers.** [BrickLink's colour guide](https://v2.bricklink.com/en-au/catalog/color-guide) is a good way to see which colours exist and what each one looks like. The numbers on that page are BrickLink's own colour IDs, and they are not the numbers Hive sorts by: white is 1 on BrickLink and 15 in Hive's catalog. Type the colour name and let the assistant pick the right one.

## 3. Read what it proposes before you trust it

When the assistant answers, it changes the rules on the left. Two things are worth checking every time.

**Order matters.** Rules are tried top to bottom and the first one that matches wins. A part that could go in two boxes goes in the higher one. If everything is landing in one box, that box is probably too high in the list and too broad.

**The catch-all is doing the work you cannot see.** Anything that matches no rule goes to your default box. If that box is enormous, your rules are narrower than you think.

Click a rule to see which parts it matches. That preview is the honest answer about what your profile does, more than the rule text is.

## 4. Send it to your machine

Save the version, then open **Machines** in Hive and use **Assign Profile** on your machine. You choose the profile and which version of it. The machine picks up what it has been assigned.

That assignment is the route today. Hive has no button that downloads a profile as a file, so if your machine is not linked to Hive, you are writing the profile on the machine itself instead. The machine's own **Profiles** page accepts a `sorting_profile.json` upload, and a machine sorts perfectly well without Hive.

Then do a short run with twenty mixed parts and watch where they land. That tells you more than another hour of editing.

## When something goes wrong

Each entry is what you see, then what to do.

### `Not authenticated`

**Cause:** Your session quietly expired. Hive signs you out of the chat after fifteen minutes of not calling anything, and the chat is the one screen that does not renew it for you.

**Fix:** Reload the page and send the message again. You are still logged in, and nothing is wrong with your account.

---

### `HTTP 502`, with no sentence after it

**Cause:** Usually a colour profile that is too large for Hive to apply. See [asking for colour](#asking-for-colour).

**Fix:** Ask for fewer colours, one colour ID per box, with no shade variants. Sending the same request again will fail the same way.

---

### `No OpenRouter key configured for this account`

**Cause:** The chat needs your own OpenRouter key and there is none saved.

**Fix:** Add one under **Settings**, see below.

---

### `Your OpenRouter account has no credits`

**Cause:** OpenRouter is prepaid and your balance is empty. Hive is not involved in the billing.

**Fix:** Add credits at [openrouter.ai/credits](https://openrouter.ai/credits) and send the message again.

---

### `OpenRouter rejected your API key`

**Cause:** The key is wrong, or it was deleted on OpenRouter after you saved it here.

**Fix:** Create a new key at [openrouter.ai/keys](https://openrouter.ai/keys) and paste it into **Settings** again.

---

### `OpenRouter is rate limiting your key`

**Cause:** Too many requests in a short time, which OpenRouter counts per key.

**Fix:** Wait a minute, then send the message again.

---

### `OpenRouter returned an empty response`

**Cause:** The model sent nothing back that Hive could use. This is not your key, whatever the error says underneath it. Hive offers you a link to your key settings for this message, and following it will not help.

**Fix:** Send the message again first. If it keeps happening, open **Settings** and choose a different **Preferred Model**, then try once more.

---

### `AI response was truncated (too long)`

**Cause:** You asked for more than fits in one answer, usually a long list of boxes with a long list of parts in each.

**Fix:** Ask for half of it, then ask for the rest in the next message.

---

### The chat describes a profile, but nothing changes on the left

**Cause:** The assistant answered in words without proposing any rules. It cannot tell that nothing was applied, so asking it to try again often produces another description.

**Fix:** Ask for something concrete and small: `Add a box for tiles.` One box landing correctly puts the chat back on track.

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
