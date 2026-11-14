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
lede: Ask Hive's assistant for the boxes you want, read what it proposes, and send the result to your machine. You do not write any rules by hand, and you can start from a default instead.
permalink: /hive/first-profile/
contributors: [brickcyclealice]
warning: >-
  **AI-generated first draft.** Rewritten on 2026-10-02 from Hive's and the sorter's source after the
  sorting profiles overhaul, not from clicking through the flow start to finish.
  Correct it as you use it.
---

A sorting profile is the ordered list of boxes your machine sorts into, plus the rules that decide which box a part belongs in. One box is one category, and a category can be spread over several bins. A piece goes to the first box that takes it, and a piece no box takes goes to the profile's fallback, or into the discard bin under the machine.

You do not have to write rules. Hive has an assistant that builds the profile for you: you describe the boxes you want in ordinary words, it writes the rules and saves them as a new version. You can also use an assistant you already have, and you can skip all of it and sort with one of Hive's default profiles. These pages are the short version of doing that for the first time.

For the file itself, field by field, see the [sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }}). You do not need it to make a working profile.

## Before you start

- A Hive account, signed in, and your machine linked to it in **Settings**, **Hive** on the machine.
- An OpenRouter key saved in Hive under **Settings**, if you want Hive's own assistant to write the profile for you. It is your own key and your own credit, and Hive never sees your card. See [set up an OpenRouter key]({{ '/hive/first-profile/openrouter-key/' | relative_url }}). An assistant you already use needs no such key.
- Twenty minutes or so. Every save is a new version and the old ones stay, so nothing you do here is permanent.

Without either you can still build a profile by adding rules by hand in the editor.

## The four steps

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hive/first-profile/decide-your-boxes/' | relative_url }}">Decide your boxes</a></strong>. How many bins you have and what you want to separate, settled on paper. Rules, kits and the fallback, and Hive's three default profiles to start from.</li>
  <li><strong><a href="{{ '/hive/first-profile/ask-in-plain-words/' | relative_url }}">Ask for it in plain words</a></strong>. What to type to Hive's assistant, writing in your own language, how to ask for colour, and how to point an assistant you already use at your profiles.</li>
  <li><strong><a href="{{ '/hive/first-profile/read-what-it-proposes/' | relative_url }}">Read what it proposes</a></strong>. Rule order and falling through, conditions with <strong>all of</strong>, <strong>any of</strong> and groups, and a worked example of four boxes in the order that makes them work.</li>
  <li><strong><a href="{{ '/hive/first-profile/send-it-to-your-machine/' | relative_url }}">Send it to your machine</a></strong>. Activating the version on the machine, which bin each box lands in, what happens when a box has no bin, and how a kit's counts work.</li>
</ol>

Work through them in order the first time. After that, most changes are one message to the assistant and a new version activated, which is steps 2 and 4 again.

## When something goes wrong

[When the profile chat goes wrong]({{ '/hive/chat-errors/' | relative_url }}) lists the error messages Hive's assistant can show, with what to do about each one.

## Next

- [Your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }}) puts the profile to work.
- [Sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }}) is the file itself, field by field, for when you want to read one.
