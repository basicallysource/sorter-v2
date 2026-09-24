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

You do not have to write rules. Hive has a chat that builds the profile for you: you describe the boxes you want in ordinary words, it proposes the rules, and Hive applies them. These pages are the short version of doing that for the first time.

For the file itself, field by field, see the [sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }}). You do not need it to make a working profile.

## Before you start

- A Hive account, signed in.
- An OpenRouter key saved in Hive under **Settings**, if you want the chat to write the profile for you. It is your own key and your own credit, and Hive never sees your card. See [set up an OpenRouter key]({{ '/hive/first-profile/openrouter-key/' | relative_url }}).
- Twenty minutes or so. Every save is a new version and the old ones stay, so nothing you do here is permanent.

Without a key you can still build a profile by adding rules by hand in the editor.

## The four steps

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hive/first-profile/decide-your-boxes/' | relative_url }}">Decide your boxes</a></strong>. How many bins you have and what you want to separate, settled on paper. Rules, sets and custom sets, and which of the three you want.</li>
  <li><strong><a href="{{ '/hive/first-profile/ask-in-plain-words/' | relative_url }}">Ask for it in plain words</a></strong>. What to type in the <strong>Chat</strong> tab, writing in your own language, and how to ask for colour while colour is still awkward.</li>
  <li><strong><a href="{{ '/hive/first-profile/read-what-it-proposes/' | relative_url }}">Read what it proposes</a></strong>. Rule order, conditions and <strong>Match ALL</strong>, and a worked example of four boxes in the order that makes them work.</li>
  <li><strong><a href="{{ '/hive/first-profile/send-it-to-your-machine/' | relative_url }}">Send it to your machine</a></strong>. Assigning the version in Hive, and choosing on the machine which bin each box lands in.</li>
</ol>

Work through them in order the first time. After that, most changes are one message in the chat and a new version assigned, which is steps 2 and 4 again.

## When something goes wrong

Several of the chat's error messages are bugs in Hive rather than something you did. [When the profile chat goes wrong]({{ '/hive/chat-errors/' | relative_url }}) lists every message it can show, with what to do about each one.

## Next

- [Your first sort run]({{ '/sorter/tutorials/first-sort-run/' | relative_url }}) puts the profile to work.
- [Sorting profile reference]({{ '/sorter/profile-reference/' | relative_url }}) is the file itself, field by field, for when you want to read or edit one directly.
