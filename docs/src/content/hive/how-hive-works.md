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
lede: What Hive is, what your machine sends it, and what a sample is. Read this before the pages on profiles and reviewing.
permalink: /hive/how-hive-works/
warning: >-
  **AI-generated first draft.** Written from Hive's and the machine software's source, not
  from using every screen. Correct it as you find it wrong.
---

Hive is the cloud side of the Sorter. It is a website at **[hive.basically.website](https://hive.basically.website)**.

Your machine sorts on its own. It does not need Hive to sort. Hive adds two things. You can build a sorting profile there and send it to your machine. And you can help the community improve the program that finds pieces in the camera picture.

**You only need the first one.** Reviewing samples is optional, and a machine that never uploads a sample sorts the same.

## What is in Hive

<ul class="bulleted-list">
  <li><strong>Profiles.</strong> The boxes your machine sorts into, and the rules for which part goes in which box. You build one in Hive and send it to your machine. See <a href="{{ '/hive/first-profile/' | relative_url }}">Build your first sorting profile</a>.</li>
  <li><strong>Machines.</strong> Each machine you link to your account has a page. It shows whether the machine is online, what it has sorted and what it is running.</li>
  <li><strong>Kits.</strong> A list of parts in colours with quantities, such as a set or an order. A bin in a profile can be set to fill with a kit.</li>
  <li><strong>Samples.</strong> Camera pictures from machines. Each has outlines drawn around the pieces. Reviewers check the outlines. See <a href="#what-a-sample-is">What a sample is</a> below.</li>
  <li><strong>Models.</strong> The programs that find pieces in the camera picture. They are trained from reviewed samples. Machines download them from here.</li>
  <li><strong>The leaderboard.</strong> It ranks the people who review samples and label pieces.</li>
</ul>

## How your machine and Hive are connected

There are two separate connections. They are easy to mix up.

<ul class="bulleted-list">
  <li><strong>The status ping.</strong> Once an hour, a machine sends a small anonymous report. The project uses it to count machines and see roughly how much they sort. It has no pictures. It needs no account.</li>
  <li><strong>Your linked machine.</strong> You sign in to Hive and connect your machine. You do this in <a href="{{ '/sorter/first-setup/' | relative_url }}">step 8 of first setup</a>, or later under <strong>Settings</strong> → <strong>Hive</strong> on the machine. The machine then stays in touch with Hive. It uploads only what you allow, and each kind of upload has its own switch. You can remove the connection at any time.</li>
</ul>

The full list of what is sent, and what you can turn off, is on [What leaves the machine]({{ '/sorter/what-leaves-the-machine/' | relative_url }}).

A normal Hive account sees its own machines and its own samples. The people who check samples are called reviewers, and they see samples from every machine. Most users are not reviewers. [Reviewing samples]({{ '/hive/review-samples/' | relative_url }}) explains who they are and how they work.

## What a sample is

A sample is one camera picture from a machine, with outlines drawn around the pieces in it. It is not a record of a piece that was sorted. It is a picture of the machine at one moment. It is kept so the piece-finding model can learn what pieces look like on that camera.

Each sample has:

<ul class="bulleted-list">
  <li><strong>The picture.</strong> A close crop. Also the full camera frame, if you allow full frames to be uploaded.</li>
  <li><strong>The outlines.</strong> One rectangle around each piece the program found. A program draws them, not a person. This is why people check them.</li>
  <li><strong>Where it came from.</strong> Which camera took it, such as the classification chamber, the carousel, the classification channel or a feed channel. Also why it was taken.</li>
  <li><strong>Its review status.</strong> How many people voted, and what they decided.</li>
</ul>

### Where samples come from

Your machine takes them. On the machine, open **Settings**. **Capture training frames** takes the latest picture from each live camera and sends it to Hive. It does not change how the machine sorts. It is off until you switch it on.

Two details change what you see in Hive:

<ul class="bulleted-list">
  <li><strong>The rate slows down.</strong> A run starts with a quick burst of pictures. Over about three days it slows to about one an hour. This stops the same setup from uploading nearly identical pictures.</li>
  <li><strong>The outlines need an AI service.</strong> Switch on <strong>Annotate with OpenRouter</strong> and add your OpenRouter key. The machine then draws the outlines before it uploads. Without this, the sample arrives with no checked outlines, and Hive hides it from the review queue by default. To get a key, see <a href="{{ '/hive/first-profile/openrouter-key/' | relative_url }}">set up an OpenRouter key</a>.</li>
</ul>

### What happens to a sample

<ol class="numbered-steps">
  <li><strong>Captured.</strong> The machine takes the picture and draws the outlines.</li>
  <li><strong>Uploaded.</strong> It goes to Hive. Its status is <strong>Unreviewed</strong>.</li>
  <li><strong>Reviewed.</strong> Reviewers vote accept or reject on the outlines. After the first vote it is <strong>In review</strong>.</li>
  <li><strong>Decided.</strong> After 3 votes it is <strong>Accepted</strong> if all three accept. It is <strong>Rejected</strong> if all three reject. It is <strong>Conflict</strong> if they disagree. A conflict stays stuck until someone changes a vote.</li>
</ol>

New piece-finding models are trained from Accepted samples. Better outlines in the training set make better models for every machine.

## Two other things with a similar name

<ul class="bulleted-list">
  <li><strong>Piece samples</strong> in Hive, also called piece labeling, are about pieces your machine really sorted. You correct a piece's colour, and mark which earlier pictures show the same piece. This is a different job from voting on outlines.</li>
  <li><strong>The Records page</strong> on your machine is where you correct what it named. It is not part of Hive's review.</li>
</ul>

The next page is [Reviewing samples]({{ '/hive/review-samples/' | relative_url }}). It explains who the reviewers are, how they work, and what it means for you.
