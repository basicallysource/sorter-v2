---
layout: default
title: Hive
type: landing
section: hive
slug: hive
kicker: Community Platform
lede: Hive is the shared platform behind the Sorter family — community-maintained sorting profiles, shared samples, and crowd verification. This section is still a stub — content is being promoted here as it stabilizes.
permalink: /hive/
---

Hive itself is at **[hive.basically.website](https://hive.basically.website)**. Make an account there, then connect your machine to it in [step 8 of first setup]({{ '/sorter/first-setup/' | relative_url }}), or later under **Settings** → **Hive** in the machine's own UI.

## Start here

- **[How Hive works]({{ '/hive/how-hive-works/' | relative_url }})**: what Hive holds, what your machine sends it, and what a sample is.
- **[Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }})** — ask Hive's assistant for the boxes you want, check what it proposes, and send the result to your machine.
- **[When the profile chat goes wrong]({{ '/hive/chat-errors/' | relative_url }})** — every error message the profile chat can show, and what to do about it.
- **[Reviewing samples]({{ '/hive/review-samples/' | relative_url }})** — who the reviewers are, how they work through the queue, and Records page versus Hive review.

## Coming soon

This section will cover:

- **Platform overview** — what Hive is for and how it relates to the local SorterOS UI.
- **Shared profiles** — how sorting profiles are published, versioned, and pulled down by machines.
- **Upload pipeline** — how samples leave the machine, how they are stored, and how the community verifies them.
- **Accounts and machines** — how a local Sorter links to a Hive account and which data crosses the boundary.
- **API reference** — the endpoints the SorterOS UI uses and the contract they are held to.

Until those pages land, the authoritative source for the upload lifecycle is SorterOS's upload coordinator code and the connected memory notes in the handoff file at the repo root.
