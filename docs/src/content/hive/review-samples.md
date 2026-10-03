---
layout: default
title: Reviewing samples
type: explanation
audience: operator
applies_to: Hive review queue, machine Records page
section: hive
owner: hive
slug: hive-review-samples
kicker: "Hive: Explanation"
lede: Who the reviewers are, how a reviewer works through the queue, what they check, and what it means for you if you own a machine.
permalink: /hive/review-samples/
warning: >-
  **AI-generated first draft.** Written from Hive's and the machine UI's source and from
  community discussion, not from clicking through the flow start to finish. Correct it as
  you use it.
---

Samples are camera pictures your machine uploads to Hive while it runs. Each one has outlines drawn around the pieces in it. If that is new to you, [How Hive works]({{ '/hive/how-hive-works/' | relative_url }}) explains what a sample is first.

A program draws the outlines, so people check them. Those people are called reviewers. This page explains who they are and how they work.

## What a reviewer is

A reviewer is a person who checks samples on Hive. For each sample, they vote **accept** or **reject** on the outlines.

<ul class="bulleted-list">
  <li><strong>They see every machine's samples.</strong> A normal Hive account sees only the samples from its own machines.</li>
  <li><strong>Several of them vote on each sample.</strong> One reviewer's vote never decides a sample alone.</li>
  <li><strong>The Basically team gives out the role.</strong> Most people who use Hive are not reviewers, and you do not need to be one to build profiles or sort. If you want to help, ask in the <code>#sample-review</code> channel on Discord.</li>
</ul>

## How a reviewer works

Reviewers work through a queue. Hive serves one sample at a time.

<ol class="numbered-steps">
  <li><strong>Open the review screen.</strong> Hive shows the first sample in the queue, with its outlines drawn on the picture.</li>
  <li><strong>Judge the outlines.</strong> Is each piece outlined correctly? The next section says what to look for.</li>
  <li><strong>Vote.</strong> Accept, reject or skip. Use the buttons, or the keyboard: up accepts, down rejects, right skips and left goes back to the last sample.</li>
  <li><strong>Move on.</strong> Hive serves the next sample. A reviewer keeps going until the queue is empty or they stop.</li>
</ol>

The queue only gives out fresh work. It hides samples the reviewer already voted on and samples that already have 3 votes. It also hides samples whose outlines have not been checked yet, and badly exposed shots. Each reviewer gets a different order, so two reviewers do not vote on the same sample at the same moment.

When a reviewer is unsure, they skip. Skipping costs nothing. A wrong vote can send a sample into conflict.

## What a reviewer checks

<ul class="bulleted-list">
  <li><strong>Accept</strong> when every piece on the target c-channel has its own tight outline.</li>
  <li><strong>Accept</strong> when the channel is empty and there are no outlines.</li>
  <li><strong>Reject</strong> when an outline is almost right but not tight.</li>
  <li><strong>Reject</strong> when two touching pieces share one outline.</li>
</ul>

## How votes become a result

A sample needs 3 votes. If all 3 accept, it is **Accepted**. If all 3 reject, it is **Rejected**. If they disagree, it is a **Conflict**. A conflict stays stuck until a reviewer changes a vote.

Reviewers find conflicts on the **Samples** page. They filter the status to **Conflict** and look at the outlines again before they vote.

Accepted samples are what a new piece-finding model is trained from. That is the reason the votes matter.

## If you own a machine

You do not have to do anything. If your machine uploads samples, reviewers check them for you.

You can see your own machine's samples, and their status, under **Samples** in Hive. The status tells you how far a sample is: **Unreviewed**, **In review**, **Accepted**, **Rejected** or **Conflict**.

Voting is limited to reviewers. An account without the role cannot submit votes.

## Records page or Hive

These are two different jobs, not the same job in two places.

<ul class="bulleted-list">
  <li><strong>Records page, in your machine's own UI.</strong> You check pieces your machine actually sorted. Confirm or reject the part it named, and correct the colour. The answer goes back to the part-recognition service as feedback on that one result. Only pieces with a recognition result can be corrected. It does not count toward the 3 votes on Hive.</li>
  <li><strong>Hive review.</strong> A reviewer judges the outlines on camera samples from the channels, the classification chamber and so on. Votes here decide whether a sample goes into the training set. That set trains the model that finds pieces in the camera picture.</li>
</ul>

If your aim is to correct what your own machine got wrong on a piece it sorted, use the Records page.

## If the review queue is empty

This is for reviewers. Work down this list.

<ol class="numbered-steps">
  <li><strong>Your machine and others.</strong> New samples appear only while a machine is running with sampling switched on. If machines are offline or not uploading, nothing new arrives.</li>
  <li><strong>The filters.</strong> The default queue hides four kinds of sample: ones you already voted on, ones with 3 votes, ones whose outlines have not been checked yet, and badly exposed shots. The <strong>Unreviewed</strong> and <strong>Conflict</strong> status filters on <strong>Samples</strong> can still show work when the main queue looks empty.</li>
  <li><strong>Your role.</strong> Without the reviewer role you see only your own machines' samples and cannot vote. Ask in <code>#sample-review</code>.</li>
</ol>

## Related

<ul class="bulleted-list">
  <li><a href="{{ '/hive/' | relative_url }}">Hive overview</a></li>
  <li><a href="{{ '/hive/how-hive-works/' | relative_url }}">How Hive works</a></li>
  <li><a href="{{ '/hive/first-profile/' | relative_url }}">Build your first sorting profile</a></li>
</ul>
