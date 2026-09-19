---
layout: default
title: When the profile chat goes wrong
type: troubleshooting
audience: operator
applies_to: Hive profile editor
section: hive
owner: hive
slug: hive-chat-errors
kicker: Hive — Troubleshooting
lede: Every error message Hive's profile chat can show you, what each one means, and what to do about it.
permalink: /hive/chat-errors/
contributors: [brickcyclealice]
warning: >-
  **AI-generated first draft.** The error messages quoted here are the ones Hive actually
  sends, read from its source rather than collected from use. Correct it as you hit them.
---

Each entry is the message you see, then what to do about it. Search this page for the one in front of you.

Building a profile in the first place is [Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}).

## `Not authenticated`

**Cause:** Your session quietly expired. Hive signs you out of the chat after fifteen minutes of not calling anything, and the chat is the one screen that does not renew it for you.

**Fix:** Reload the page and send the message again. You are still logged in, and nothing is wrong with your account.

---

## `HTTP 502`, with no sentence after it

**Cause:** Usually a colour profile that is too large for Hive to apply. See [asking for colour]({{ '/hive/first-profile/#asking-for-colour' | relative_url }}). The other cause is a value that is not a number in a condition that compares numbers, such as `$5` in `bl_price_min >= $5`. Saving fails the same way, with nothing to say which rule it was.

**Fix:** For colour, ask for fewer colours, one colour per box, with no shade variants. Sending the same request again will fail the same way. For a number, open the rule and take the currency symbol or the unit out of the value, leaving the digits: `5`, not `$5`.

---

## `No OpenRouter key configured for this account`

**Cause:** The chat needs your own OpenRouter key and there is none saved.

**Fix:** Add one under **Settings**. The steps are on [Build your first sorting profile]({{ '/hive/first-profile/#set-up-an-openrouter-key' | relative_url }}).

---

## `Your OpenRouter account has no credits`

**Cause:** OpenRouter is prepaid and your balance is empty. Hive is not involved in the billing.

**Fix:** Add credits at [openrouter.ai/credits](https://openrouter.ai/credits) and send the message again.

---

## `OpenRouter rejected your API key`

**Cause:** The key is wrong, or it was deleted on OpenRouter after you saved it here.

**Fix:** Create a new key at [openrouter.ai/keys](https://openrouter.ai/keys) and paste it into **Settings** again.

---

## `OpenRouter is rate limiting your key`

**Cause:** Too many requests in a short time, which OpenRouter counts per key.

**Fix:** Wait a minute, then send the message again.

---

## `OpenRouter returned an empty response`

**Cause:** The model sent nothing back that Hive could use. This is not your key, whatever the error says underneath it. Hive offers you a link to your key settings for this message, and following it will not help.

**Fix:** Send the message again first. If it keeps happening, open **Settings** and choose a different **Preferred Model**, then try once more.

---

## `AI response was truncated (too long)`

**Cause:** You asked for more than fits in one answer, usually a long list of boxes with a long list of parts in each.

**Fix:** Ask for half of it, then ask for the rest in the next message.

---

## The chat describes a profile, but nothing changes on the left

**Cause:** The assistant answered in words without proposing any rules. It cannot tell that nothing was applied, so asking it to try again often produces another description.

**Fix:** Ask for something concrete and small: `Add a box for tiles.` One box landing correctly puts the chat back on track.
