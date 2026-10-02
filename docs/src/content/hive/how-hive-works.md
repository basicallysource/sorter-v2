---
layout: default
title: How Hive works
type: explanation
audience: operator
applies_to: Hive, machine Settings
section: hive
owner: hive
slug: hive-how-it-works
kicker: "Hive: Explanation"
lede: What Hive is, what your machine sends it and when, and what a sample is, so the pages on profiles and reviewing make sense.
permalink: /hive/how-hive-works/
warning: >-
  **AI-generated first draft.** Written from Hive's and the machine software's source, not
  from using every screen. Correct it as you find it wrong.
---

Hive is the cloud side of the Sorter. Your machine does the sorting on its own, with or without Hive. Hive is where the community keeps the things worth sharing: sorting profiles, camera samples and the checking of them, and the vision models trained from those samples.

It lives at **[hive.basically.website](https://hive.basically.website)**.

## What is in Hive

<ul class="bulleted-list">
  <li><strong>Machines.</strong> Each machine you link to your account has a page showing whether it is online, what it has sorted and what it is running.</li>
  <li><strong>Profiles.</strong> The boxes a machine sorts into and the rules behind them. You build one in Hive and send it to your machine. See <a href="{{ '/hive/first-profile/' | relative_url }}">Build your first sorting profile</a>.</li>
  <li><strong>Kits.</strong> A list of parts in colours with quantities, such as a set or an order, which a kit bin in a profile can collect until it is full.</li>
  <li><strong>Samples.</strong> Camera images from machines, with boxes drawn on the pieces in them. Reviewers check them. See <a href="#what-a-sample-is">What a sample is</a> below.</li>
  <li><strong>Models.</strong> The vision models machines use to find pieces in the camera image, published for machines to download.</li>
  <li><strong>The leaderboard.</strong> Ranks the people who review samples and label pieces.</li>
</ul>

## How your machine and Hive are connected

There are two separate connections, and they are easy to mix up.

<ul class="bulleted-list">
  <li><strong>The status ping.</strong> Once an hour a machine sends a small anonymous report so the project knows how many machines exist and roughly how much they sort. It has no images and needs no account.</li>
  <li><strong>Your linked machine.</strong> Once you sign in to Hive and connect your machine in <a href="{{ '/sorter/first-setup/' | relative_url }}">step 8 of first setup</a>, or later under <strong>Settings</strong> → <strong>Hive</strong> on the machine, it keeps in touch with Hive and uploads what you allow. Pieces, camera frames and the rest are each a separate switch there, and you can remove the connection at any time.</li>
</ul>

The full list of what is sent, and which parts you can turn off, is on [What leaves the machine]({{ '/sorter/what-leaves-the-machine/' | relative_url }}).

You also have a role on your Hive account. A normal account sees its own machines and its own samples. The **reviewer** role lets you vote on samples, including other people's, and the Basically team grants it.

## What a sample is

A sample is one camera image from a machine, together with boxes drawn around the pieces in it. It is not a record of a piece that was sorted. It is a picture of the machine at one moment, kept so that a vision model can learn what pieces look like on that camera.

Each sample carries:

<ul class="bulleted-list">
  <li><strong>The image.</strong> A crop, and the full camera frame as well if you allow full frames to be uploaded.</li>
  <li><strong>The boxes.</strong> One box per piece the detector found. These are drawn by an AI detector, not by a person, which is why they need checking.</li>
  <li><strong>Where it came from.</strong> Which camera it was taken from, for example the classification chamber, the carousel, the classification channel or one of the feeder channels, and the reason it was captured.</li>
  <li><strong>Its review status.</strong> How many people have voted on it and what they decided.</li>
</ul>

### Where samples come from

Your machine captures them. Under **Settings** on the machine, **Capture training frames** snapshots the latest frame from each live camera and sends it to Hive. It does not change how the machine sorts, and it is off until you switch it on. Two details shape what you see in Hive:

<ul class="bulleted-list">
  <li><strong>The rate slows down.</strong> A run starts with a quick burst of captures, then slows over roughly three days to about one an hour, so the same setup stops uploading near-identical pictures.</li>
  <li><strong>Boxes need an AI detector.</strong> With <strong>Annotate with OpenRouter</strong> on, and an OpenRouter key set up, the machine draws the boxes before upload. Without it the frame arrives as a raw sample with no checked boxes, and Hive's review queue hides those by default.</li>
</ul>

### What happens to a sample

<ol class="numbered-steps">
  <li><strong>Captured.</strong> The machine takes the frame and boxes it.</li>
  <li><strong>Uploaded.</strong> It goes to Hive, and its status is <strong>Unreviewed</strong>.</li>
  <li><strong>Reviewed.</strong> Reviewers vote accept or reject on the boxes. After the first vote it is <strong>In review</strong>.</li>
  <li><strong>Decided.</strong> At 3 votes it is <strong>Accepted</strong> if all three accept, <strong>Rejected</strong> if all three reject, and <strong>Conflict</strong> if they disagree. A conflict stays stuck until someone changes a vote.</li>
</ol>

Accepted samples are the ones new vision models are trained from. That is the point of reviewing: the better the boxes in the training set, the better the models machines download.

## Two other things called samples

<ul class="bulleted-list">
  <li><strong>Piece samples</strong> in Hive, also called piece labeling, are about pieces your machine actually sorted: correcting a piece's colour, and marking which earlier crops show the same piece. They are a different job from voting on boxes.</li>
  <li><strong>The Records page</strong> on your machine is where you correct what it named. It is not part of Hive's review at all.</li>
</ul>

The next page, [Reviewing samples]({{ '/hive/review-samples/' | relative_url }}), covers how to review well and what to check when the queue is empty.
